"""ReAct investigation agent — LLM or adaptive planner chooses tools step-by-step."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from src.connectors.loaders import _extract_utr_from_narration
from src.domain.models import (
    BankEntry,
    ExceptionCode,
    InvestigationCase,
    PredictedHypothesis,
    ProposedAction,
    SettlementBatch,
)

BANK_BLOCKING = frozenset(
    {
        ExceptionCode.BANK_REFERENCE_AMBIGUOUS,
        ExceptionCode.MISSING_BANK_CREDIT,
        ExceptionCode.PROCESSED_AWAITING_BANK,
        ExceptionCode.BANK_AMOUNT_MISMATCH,
    }
)

MAX_REACT_STEPS = int(os.getenv("AGENT_MAX_STEPS", "6"))
CACHED_INVESTIGATIONS_PATH = Path(__file__).parent.parent.parent / "data" / "cached_investigations.json"

ACTION_CATALOG = {
    "human_review": "Rank bank candidates; human selects correct match. Never auto-close ambiguous UTR.",
    "escalate": "Draft bank/Razorpay support case with UTR, amount, settlement evidence.",
    "recheck": "Schedule recheck — bank credit expected within SLA window.",
    "post_journal": "Post approved fee journal template only; amounts from recon evidence.",
    "confirm_match": "Human confirms deterministic match when evidence is complete.",
}

POLICIES = {
    "bank_matching": "Auto-close bank link only on exact UTR + amount. Same-amount candidates require UTR discriminator.",
    "gl_posting": "When recon lines show fees, GL must contain balanced fee/tax journal debits.",
    "bank_sla": "Processed settlement may remain pending until bank arrival SLA (3 days) elapses.",
}


class InvestigationTools:
    """Allowlisted read-only tools for the investigation agent."""

    def __init__(
        self,
        batches: dict[str, SettlementBatch],
        bank_entries: list[BankEntry],
    ):
        self.batches = batches
        self.bank_entries = bank_entries

    def fetch_source_record(self, source: str, record_id: str) -> dict[str, Any]:
        if source == "settlement" and record_id in self.batches:
            b = self.batches[record_id]
            return {
                "settlement_id": b.settlement_id,
                "amount": b.amount,
                "utr": b.utr,
                "status": b.status,
                "line_count": len(b.lines),
            }
        if source == "bank":
            for e in self.bank_entries:
                if e.entry_id == record_id:
                    return e.model_dump(mode="json")
        return {"error": "not_found", "source": source, "id": record_id}

    def search_candidate_records(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        amount = filters.get("amount")
        results = []
        for e in self.bank_entries:
            if amount is not None and e.amount != amount:
                continue
            utr = e.utr or _extract_utr_from_narration(e.narration)
            results.append(
                {
                    "entry_id": e.entry_id,
                    "amount": e.amount,
                    "utr": utr,
                    "narration": e.narration,
                    "value_date": str(e.value_date),
                }
            )
        return results[:10]

    def calculate_batch(self, settlement_id: str) -> dict[str, Any]:
        if settlement_id not in self.batches:
            return {"error": "not_found"}
        b = self.batches[settlement_id]
        return {
            "settlement_id": settlement_id,
            "header_amount": b.amount,
            "net_from_lines": b.net_from_lines,
            "match": b.net_from_lines == b.amount,
            "total_fees": sum(l.fee for l in b.lines),
        }

    def get_policy(self, policy_id: str) -> dict[str, Any]:
        return {"policy_id": policy_id, "text": POLICIES.get(policy_id, "Unknown policy")}

    def get_action_catalog(self, case_type: str) -> dict[str, Any]:
        key = case_type.lower().replace(" ", "_")
        if key in ACTION_CATALOG:
            return {"action": key, "description": ACTION_CATALOG[key]}
        return {"actions": ACTION_CATALOG, "case_type": case_type}


from src.agent.llm_client import agent_mode_label, assistant_message_for_api, create_llm_client, get_llm_model, llm_provider, should_use_llm


def _normalize(s: str) -> str:
    return s.upper().replace(" ", "").replace("-", "")


def _summarize_result(result: Any) -> str:
    if isinstance(result, list):
        return f"[{len(result)} items]"
    if isinstance(result, dict):
        if "error" in result:
            return f"error={result['error']}"
        parts = [f"{k}={v}" for k, v in list(result.items())[:4]]
        return "{" + ", ".join(parts) + "}"
    return str(result)[:120]


def execute_tool(tools: InvestigationTools, tool_name: str, args: dict[str, Any]) -> Any:
    """Dispatch allowlisted tool — agent cannot call anything else."""
    allowlist = {
        "fetch_source_record": lambda: tools.fetch_source_record(args["source"], args["record_id"]),
        "search_candidate_records": lambda: tools.search_candidate_records(args.get("filters", args)),
        "calculate_batch": lambda: tools.calculate_batch(args["settlement_id"]),
        "get_policy": lambda: tools.get_policy(args["policy_id"]),
        "get_action_catalog": lambda: tools.get_action_catalog(args.get("case_type", "unknown")),
    }
    if tool_name not in allowlist:
        return {"error": "tool_not_allowed", "tool": tool_name}
    return allowlist[tool_name]()


def _synthesize_hypothesis(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    context: list[dict[str, Any]],
    trace: list[str],
    agent_mode: str,
) -> PredictedHypothesis:
    """Build final hypothesis from gathered evidence — rules interpret tool results."""
    supporting: list[str] = []
    contradicting: list[str] = []
    missing: list[str] = []
    summary_parts: list[str] = []
    codes = set(case.exception_codes)

    batch_info = next((c["result"] for c in context if c["tool"] == "calculate_batch"), None)
    candidates = next((c["result"] for c in context if c["tool"] == "search_candidate_records"), [])

    if batch and batch_info and not batch_info.get("error"):
        summary_parts.append(
            f"Settlement {batch.settlement_id} net {batch_info.get('net_from_lines')} paise, UTR {batch.utr}"
        )
        supporting.append(f"batch_calc:{batch.settlement_id}")

    if ExceptionCode.BANK_REFERENCE_AMBIGUOUS in codes:
        n = len(candidates) if isinstance(candidates, list) else 0
        summary_parts.append(f"{n} same-amount bank candidates — UTR discriminator required")
        if isinstance(candidates, list):
            for c in candidates:
                contradicting.append(f"bank:{c['entry_id']}")
            utr = batch.utr if batch else ""
            has_discriminator = False
            if utr:
                for c in candidates:
                    extracted = c.get("utr") or _extract_utr_from_narration(c.get("narration", ""))
                    if extracted and (
                        _normalize(extracted) == _normalize(utr) or _normalize(utr) in _normalize(extracted)
                    ):
                        supporting.append(f"utr_match:{c['entry_id']}")
                        has_discriminator = True
            if not has_discriminator:
                missing.append("Recoverable UTR fragment in bank narration to disambiguate candidates")
                return PredictedHypothesis(
                    summary="; ".join(summary_parts) + ". INSUFFICIENT_EVIDENCE to auto-match.",
                    supporting_evidence=supporting,
                    contradicting_evidence=contradicting,
                    missing_evidence=missing,
                    recommended_action="human_review",
                    sufficient_evidence=False,
                    tool_trace=trace,
                )

    if ExceptionCode.MISSING_BANK_CREDIT in codes:
        missing.append("Bank credit with matching UTR and amount")
        summary_parts.append("Settlement processed but bank credit absent after SLA")
        return PredictedHypothesis(
            summary="; ".join(summary_parts),
            supporting_evidence=supporting,
            missing_evidence=missing,
            recommended_action="escalate",
            sufficient_evidence=False,
            tool_trace=trace,
        )

    if ExceptionCode.PROCESSED_AWAITING_BANK in codes:
        missing.append("Bank credit within settlement arrival window")
        summary_parts.append("Transfer initiated — awaiting bank credit inside SLA")
        return PredictedHypothesis(
            summary="; ".join(summary_parts),
            supporting_evidence=supporting,
            missing_evidence=missing,
            recommended_action="recheck",
            sufficient_evidence=False,
            tool_trace=trace,
        )

    if ExceptionCode.LEDGER_ENTRY_MISSING in codes and batch_info:
        fees = batch_info.get("total_fees", 0)
        summary_parts.append(f"Fee journal missing (recon fees: {fees} paise)")
        return PredictedHypothesis(
            summary="; ".join(summary_parts),
            supporting_evidence=supporting,
            missing_evidence=["balanced fee/tax GL entries"],
            recommended_action="post_journal",
            sufficient_evidence=True,
            tool_trace=trace,
        )

    return PredictedHypothesis(
        summary="; ".join(summary_parts) if summary_parts else f"Investigation complete ({agent_mode})",
        supporting_evidence=supporting,
        contradicting_evidence=contradicting,
        missing_evidence=missing,
        recommended_action="human_review" if missing else "confirm_match",
        sufficient_evidence=len(missing) == 0 and len(supporting) > 0,
        tool_trace=trace,
    )


def _planner_next_step(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    context: list[dict[str, Any]],
) -> dict[str, Any]:
    """Adaptive planner: next tool depends on prior results, not a fixed script."""
    called = {c["tool"] for c in context}
    codes = set(case.exception_codes)
    sid = case.settlement_id or ""

    if batch and "calculate_batch" not in called:
        return {"type": "tool", "tool": "calculate_batch", "args": {"settlement_id": sid}, "reason": "Verify batch arithmetic"}

    if sid and "fetch_source_record" not in called:
        return {
            "type": "tool",
            "tool": "fetch_source_record",
            "args": {"source": "settlement", "record_id": sid},
            "reason": "Load settlement header evidence",
        }

    if ExceptionCode.BANK_REFERENCE_AMBIGUOUS in codes and "search_candidate_records" not in called and batch:
        return {
            "type": "tool",
            "tool": "search_candidate_records",
            "args": {"filters": {"amount": batch.amount}},
            "reason": "Find same-amount bank candidates",
        }

    if ExceptionCode.BANK_REFERENCE_AMBIGUOUS in codes and "get_policy" not in called:
        return {
            "type": "tool",
            "tool": "get_policy",
            "args": {"policy_id": "bank_matching"},
            "reason": "Check UTR matching policy before deciding",
        }

    if ExceptionCode.MISSING_BANK_CREDIT in codes and "get_policy" not in called:
        return {
            "type": "tool",
            "tool": "get_policy",
            "args": {"policy_id": "bank_sla"},
            "reason": "Confirm SLA breach policy",
        }

    if ExceptionCode.PROCESSED_AWAITING_BANK in codes and "get_policy" not in called:
        return {
            "type": "tool",
            "tool": "get_policy",
            "args": {"policy_id": "bank_sla"},
            "reason": "Confirm pending-within-SLA policy",
        }

    if ExceptionCode.LEDGER_ENTRY_MISSING in codes and "get_policy" not in called:
        return {
            "type": "tool",
            "tool": "get_policy",
            "args": {"policy_id": "gl_posting"},
            "reason": "Confirm GL posting requirement",
        }

    primary = case.exception_codes[0].value if case.exception_codes else "unknown"
    if "get_action_catalog" not in called:
        return {
            "type": "tool",
            "tool": "get_action_catalog",
            "args": {"case_type": primary},
            "reason": "Load bounded action options",
        }

    return {"type": "finish", "reason": "Evidence gathering complete"}


def _react_loop_planner(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    tools: InvestigationTools,
) -> PredictedHypothesis:
    """ReAct loop: planner chooses tools until finish or max steps."""
    context: list[dict[str, Any]] = []
    trace: list[str] = []

    for step in range(MAX_REACT_STEPS):
        decision = _planner_next_step(case, batch, context)
        if decision["type"] == "finish":
            trace.append(f"step_{step + 1}: finish — {decision.get('reason', 'done')}")
            break

        tool_name = decision["tool"]
        args = decision["args"]
        result = execute_tool(tools, tool_name, args)
        context.append({"tool": tool_name, "args": args, "result": result})
        trace.append(
            f"step_{step + 1}: {tool_name}({json.dumps(args, default=str)}) -> {_summarize_result(result)}"
        )
    else:
        trace.append(f"step_{MAX_REACT_STEPS}: max_steps_reached — abstain")

    return _synthesize_hypothesis(case, batch, context, trace, "react_planner")


def _openai_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "calculate_batch",
                "description": "Compute settlement batch net from recon lines",
                "parameters": {
                    "type": "object",
                    "properties": {"settlement_id": {"type": "string"}},
                    "required": ["settlement_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "fetch_source_record",
                "description": "Fetch settlement or bank source record by ID",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "source": {"type": "string", "enum": ["settlement", "bank"]},
                        "record_id": {"type": "string"},
                    },
                    "required": ["source", "record_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_candidate_records",
                "description": "Search bank entries matching filters (e.g. amount)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filters": {
                            "type": "object",
                            "properties": {"amount": {"type": "integer"}},
                        }
                    },
                    "required": ["filters"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_policy",
                "description": "Read merchant reconciliation policy",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "policy_id": {
                            "type": "string",
                            "enum": list(POLICIES.keys()),
                        }
                    },
                    "required": ["policy_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_action_catalog",
                "description": "List bounded actions allowed for this case type",
                "parameters": {
                    "type": "object",
                    "properties": {"case_type": {"type": "string"}},
                    "required": ["case_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "finish_investigation",
                "description": "Conclude investigation when enough evidence gathered or must abstain",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                        "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
                        "missing_evidence": {"type": "array", "items": {"type": "string"}},
                        "recommended_action": {"type": "string"},
                        "sufficient_evidence": {"type": "boolean"},
                    },
                    "required": ["summary", "recommended_action", "sufficient_evidence"],
                },
            },
        },
    ]


def _react_loop_llm(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    tools: InvestigationTools,
) -> PredictedHypothesis | None:
    """ReAct loop: Groq/OpenAI LLM chooses tools until finish_investigation or max steps."""
    try:
        client = create_llm_client()
        model = get_llm_model()
        mode = agent_mode_label(True)
        trace: list[str] = [f"provider={llm_provider()}", f"model={model}"]
        context: list[dict[str, Any]] = []

        system = """You are a finance investigation agent for Razorpay settlement reconciliation.
You may ONLY use the provided tools. You must NOT invent amounts or account codes.
Gather evidence step by step. Call finish_investigation when you have enough evidence to recommend an action or must abstain.
If multiple bank candidates share the same amount without UTR discriminator, set sufficient_evidence=false."""

        user = {
            "settlement_id": case.settlement_id,
            "exception_codes": [e.value for e in case.exception_codes],
            "bank_candidates_from_rules": case.bank_candidates,
            "settlement_amount_paise": batch.amount if batch else None,
            "settlement_utr": batch.utr if batch else None,
        }

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user)},
        ]

        for step in range(MAX_REACT_STEPS):
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=_openai_tool_schemas(),
                tool_choice="auto",
                temperature=0,
            )
            msg = response.choices[0].message

            if not msg.tool_calls:
                trace.append(f"step_{step + 1}: llm_no_tool — fallback to synthesis")
                break

            messages.append(assistant_message_for_api(msg))

            finished = False
            for tc in msg.tool_calls:
                fn = tc.function.name
                args = json.loads(tc.function.arguments or "{}")

                if fn == "finish_investigation":
                    trace.append(f"step_{step + 1}: finish_investigation")
                    return PredictedHypothesis(
                        summary=args.get("summary", ""),
                        supporting_evidence=args.get("supporting_evidence", []),
                        contradicting_evidence=args.get("contradicting_evidence", []),
                        missing_evidence=args.get("missing_evidence", []),
                        recommended_action=args.get("recommended_action", "human_review"),
                        sufficient_evidence=bool(args.get("sufficient_evidence", False)),
                        tool_trace=trace,
                    )

                result = execute_tool(tools, fn, args)
                context.append({"tool": fn, "args": args, "result": result})
                trace.append(f"step_{step + 1}: {fn}({json.dumps(args)}) -> {_summarize_result(result)}")

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result, default=str),
                    }
                )

            if finished:
                break
        else:
            trace.append(f"step_{MAX_REACT_STEPS}: max_steps_reached")

        return _synthesize_hypothesis(case, batch, context, trace, mode)
    except Exception:
        return None


def run_investigation(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    tools: InvestigationTools,
    use_llm: bool | None = None,
) -> PredictedHypothesis:
    """Run ReAct investigation — LLM planner if enabled, else adaptive deterministic planner."""
    if use_llm is None:
        use_llm = should_use_llm()

    if use_llm:
        hypothesis = _react_loop_llm(case, batch, tools)
        if hypothesis:
            return hypothesis

    return _react_loop_planner(case, batch, tools)


def attach_proposed_action(
    case: InvestigationCase,
    batch: SettlementBatch | None,
    hypothesis: PredictedHypothesis,
) -> InvestigationCase:
    from src.actions.ledger import propose_missing_fee_journal

    codes = set(case.exception_codes)
    sid = case.settlement_id or ""

    if ExceptionCode.BANK_REFERENCE_AMBIGUOUS in codes:
        case.proposed_action = ProposedAction(
            action_type="human_review",
            settlement_id=sid,
            description="Ambiguous bank reference — rank candidates and require human decision",
        )
    elif ExceptionCode.MISSING_BANK_CREDIT in codes:
        case.proposed_action = ProposedAction(
            action_type="escalate",
            settlement_id=sid,
            description="Draft bank/Razorpay support case with UTR, amount, and settlement evidence",
        )
    elif ExceptionCode.PROCESSED_AWAITING_BANK in codes:
        case.proposed_action = ProposedAction(
            action_type="recheck",
            settlement_id=sid,
            description="Schedule recheck — bank credit expected within SLA window",
        )
    elif ExceptionCode.LEDGER_ENTRY_MISSING in codes and batch and not (codes & BANK_BLOCKING):
        case.proposed_action = propose_missing_fee_journal(batch, case)
    elif not hypothesis.sufficient_evidence:
        case.proposed_action = ProposedAction(
            action_type="human_review",
            settlement_id=sid,
            description="Insufficient evidence — requires human review",
        )
    return case
