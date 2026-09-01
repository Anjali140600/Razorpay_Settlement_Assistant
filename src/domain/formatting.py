"""Shared display helpers."""

from __future__ import annotations


def format_inr(paise: int) -> str:
    return f"₹{paise / 100:,.2f}"
