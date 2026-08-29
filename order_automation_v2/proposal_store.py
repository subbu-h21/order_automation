"""Tiny JSON-file persistence for the pending proposal - no DB, matching how
every other piece of state in this project (credentials, branch config) is
just hand-managed flat files. This exists specifically so a pending review
survives a backend restart: the owner may take hours or days between a
proposal being built (Phase A) and confirming it (Phase B), and the dashboard
needs to show the same pending proposal (or its confirmed result) to anyone
who opens it later, not just the browser tab that was open when it finished.
"""

import json
from pathlib import Path

from config import OUTPUT_DIR

_PROPOSAL_PATH: Path = OUTPUT_DIR / "proposal.json"


def load_proposal() -> dict | None:
    """Returns the persisted proposal (as saved by save_proposal), or None
    if there isn't one / it can't be read. Read once at backend startup."""
    if not _PROPOSAL_PATH.exists():
        return None
    try:
        return json.loads(_PROPOSAL_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_proposal(data: dict) -> None:
    _PROPOSAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def clear_proposal() -> None:
    _PROPOSAL_PATH.unlink(missing_ok=True)
