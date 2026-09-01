"""Load .env from project root before reading os.environ."""

from pathlib import Path

try:
    from dotenv import load_dotenv

    _root = Path(__file__).resolve().parent.parent
    load_dotenv(_root / ".env")
except ImportError:
    pass
