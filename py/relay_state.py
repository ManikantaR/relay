"""
relay_state.py — canonical v2 session state transitions.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Transition:
    frm: str
    to: str
    reason: str = ""


_ALLOWED = {
    "queued": {"dispatching", "running", "terminated"},
    "dispatching": {"running", "error", "terminated"},
    "running": {"paused", "review_requested", "rate_limited", "held", "needs_decision",
                "done", "error", "terminated"},
    "paused": {"running", "terminated", "needs_decision"},
    "awaiting_input": {"running", "paused", "terminated", "needs_decision"},
    "rate_limited": {"running", "needs_decision", "terminated"},
    "review_requested": {"review_running", "needs_decision", "terminated"},
    "review_running": {"changes_requested", "approved", "needs_decision", "error", "terminated"},
    "changes_requested": {"running", "needs_decision", "terminated"},
    "approved": {"held", "done", "terminated"},
    "held": {"running", "needs_decision", "done", "terminated"},
    "needs_decision": {"running", "terminated", "done"},
    "error": {"running", "terminated", "needs_decision"},
    "done": set(),
    "terminated": set(),
}


def can_transition(frm: str, to: str) -> bool:
    return to in _ALLOWED.get(frm, set())


def transition(frm: str, to: str, reason: str = "") -> Transition:
    if frm == to:
        return Transition(frm, to, reason)
    if not can_transition(frm, to):
        raise ValueError(f"invalid transition {frm}->{to}")
    return Transition(frm, to, reason)
