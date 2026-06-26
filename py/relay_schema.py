"""
relay_schema.py — v2 session/event/model policy schema helpers.

This is intentionally stdlib-only. The source of truth is still JSON-on-disk; SQLite is an
index. Validation here is lightweight and pragmatic rather than a full JSON Schema engine.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SESSION_STATES = {
    "queued", "dispatching", "running", "paused", "awaiting_input", "rate_limited",
    "review_requested", "review_running", "changes_requested", "approved", "held",
    "needs_decision", "done", "error", "terminated",
}
SESSION_ROLES = {"implementer", "reviewer", "triage"}
EVENT_TYPES = {
    "session_created", "session_started", "session_paused", "session_resumed",
    "session_terminated", "state_changed", "checkpoint_written", "operator_nudge",
    "operator_raw_input", "worker_acknowledged", "review_requested",
    "review_comment_added", "review_approved", "review_changes_requested",
    "review_loop_capped", "model_selected", "model_escalated", "lane_switched",
    "rate_limited", "needs_decision", "evidence_written", "cost_updated",
}
NUDGE_TYPES = {
    "goal_correction", "acceptance_clarification", "code_example", "review_feedback",
    "operator_override",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _session_required() -> dict[str, type]:
    return {
        "session_id": str,
        "task_id": str,
        "repo": str,
        "project_path": str,
        "role": str,
        "tier": str,
        "state": str,
        "lane": str,
        "provider": str,
        "model": str,
        "effort": str,
        "selection_mode": str,
        "selection_reason": str,
        "alternatives": list,
        "operator_overrides": list,
        "review_round": int,
        "max_review_rounds": int,
        "created_at": str,
        "updated_at": str,
    }


def validate_session(doc: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for key, typ in _session_required().items():
        if key not in doc:
            errs.append(f"missing {key}")
        elif not isinstance(doc[key], typ):
            errs.append(f"{key} must be {typ.__name__}")
    if "state" in doc and doc["state"] not in SESSION_STATES:
        errs.append(f"invalid state {doc['state']}")
    if "role" in doc and doc["role"] not in SESSION_ROLES:
        errs.append(f"invalid role {doc['role']}")
    if "tier" in doc and str(doc["tier"]) not in {"1", "2"}:
        errs.append(f"invalid tier {doc['tier']}")
    return errs


def validate_event(doc: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    req = {"event_id": str, "session_id": str, "type": str, "timestamp": str,
           "actor": str, "summary": str, "payload": dict, "sequence": int}
    for key, typ in req.items():
        if key not in doc:
            errs.append(f"missing {key}")
        elif not isinstance(doc[key], typ):
            errs.append(f"{key} must be {typ.__name__}")
    if "type" in doc and doc["type"] not in EVENT_TYPES:
        errs.append(f"invalid event type {doc['type']}")
    return errs


def default_session(task_id: str, repo: str, project_path: str, role: str = "implementer",
                    tier: str = "1", lane: str = "", provider: str = "", model: str = "",
                    effort: str = "medium", selection_mode: str = "auto",
                    selection_reason: str = "", alternatives: list[dict[str, Any]] | None = None,
                    max_review_rounds: int = 3) -> dict[str, Any]:
    doc = {
        "session_id": make_id("sess"),
        "task_id": task_id,
        "repo": repo,
        "project_path": project_path,
        "worktree_path": "",
        "role": role,
        "tier": str(tier),
        "state": "queued",
        "lane": lane,
        "provider": provider,
        "model": model,
        "effort": effort,
        "selection_mode": selection_mode,
        "selection_reason": selection_reason,
        "alternatives": alternatives or [],
        "operator_overrides": [],
        "review_round": 0,
        "max_review_rounds": max_review_rounds,
        "parent_session_id": None,
        "review_session_id": None,
        "brief_path": "brief.md",
        "transcript_path": "transcript.log",
        "events_path": "events.jsonl",
        "evidence_dir": "evidence",
        "cost": {"input_tokens": 0, "output_tokens": 0, "usd_estimate": 0.0},
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "started_at": None,
        "ended_at": None,
    }
    errs = validate_session(doc)
    if errs:
        raise ValueError("; ".join(errs))
    return doc


def make_event(session_id: str, etype: str, actor: str, summary: str,
               payload: dict[str, Any] | None = None, sequence: int = 1) -> dict[str, Any]:
    doc = {
        "event_id": make_id("evt"),
        "session_id": session_id,
        "type": etype,
        "timestamp": now_iso(),
        "actor": actor,
        "summary": summary,
        "payload": payload or {},
        "sequence": sequence,
    }
    errs = validate_event(doc)
    if errs:
        raise ValueError("; ".join(errs))
    return doc


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(doc, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_models_policy(path: Path) -> dict[str, Any]:
    """Load `.crew/models.yml` if PyYAML is available. Future runtime wiring will use this.
    For now this keeps the file format choice explicit without taking a hard dependency."""
    try:
        import yaml  # type: ignore
    except Exception as e:
        raise RuntimeError("Loading .crew/models.yml requires PyYAML in this environment") from e
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError("models policy must parse to a mapping")
    return data
