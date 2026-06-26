"""
relay_review.py — review-loop runtime helpers for Relay v2.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import relay_schema as schema
from relay_store import Store


def append_review_feedback(brief_path: Path, comments: list[dict[str, Any]], review_round: int) -> None:
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    existing = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    lines = [existing.rstrip(), "", f"## Review Feedback Round {review_round}", ""]
    for c in comments:
        loc = c.get("path", "")
        line = c.get("line")
        msg = c.get("message", "").strip()
        if loc and line is not None:
            lines.append(f"- `{loc}:{line}` {msg}")
        elif loc:
            lines.append(f"- `{loc}` {msg}")
        else:
            lines.append(f"- {msg}")
    brief_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def spawn_reviewer(store: Store, parent_session_id: str, provider: str = "", model: str = "",
                   effort: str = "medium", selection_reason: str = "review request") -> dict[str, Any]:
    parent = store.get_session(parent_session_id)
    reviewer = schema.default_session(
        task_id=parent["task_id"],
        repo=parent["repo"],
        project_path=parent["project_path"],
        role="reviewer",
        tier=parent["tier"],
        lane=parent["lane"],
        provider=provider or parent["provider"],
        model=model or parent["model"],
        effort=effort,
        selection_mode="auto",
        selection_reason=selection_reason,
        alternatives=parent.get("alternatives", []),
        max_review_rounds=parent.get("max_review_rounds", 3),
    )
    reviewer["parent_session_id"] = parent_session_id
    reviewer["brief_path"] = parent.get("brief_path", "brief.md")
    reviewer["worktree_path"] = parent.get("worktree_path", "")
    reviewer["state"] = "review_running"
    created = store.create_session(reviewer)
    store.update_session(parent_session_id, lambda d: d.update({"review_session_id": created["session_id"]}))
    store.transition_session(parent_session_id, "review_requested", actor="relay", reason="reviewer spawned")
    return created


def submit_review(store: Store, parent_session_id: str, review_session_id: str,
                  comments: list[dict[str, Any]], approved: bool = False,
                  actor: str = "reviewer") -> dict[str, Any]:
    parent = store.get_session(parent_session_id)
    review = store.get_session(review_session_id)
    round_no = int(parent.get("review_round", 0)) + (0 if approved else 1)

    seq = store.next_sequence(parent_session_id)
    etype = "review_approved" if approved else "review_changes_requested"
    summary = "review approved" if approved else f"review requested changes ({len(comments)} comments)"
    store.append_event(parent_session_id, schema.make_event(
        parent_session_id, etype, actor, summary,
        {"review_session_id": review_session_id, "comments": comments}, sequence=seq,
    ))

    if approved:
        store.transition_session(review_session_id, "done", actor="relay", reason="review approved")
        store.transition_session(parent_session_id, "approved", actor="relay", reason="review approved")
        return store.get_session(parent_session_id)

    brief_rel = parent.get("brief_path", "brief.md")
    brief_path = store.session_dir(parent_session_id) / brief_rel
    append_review_feedback(brief_path, comments, round_no)

    def mutate_parent(doc: dict[str, Any]) -> None:
        doc["review_round"] = round_no

    store.update_session(parent_session_id, mutate_parent)
    store.transition_session(review_session_id, "done", actor="relay", reason="review comments delivered")
    if round_no >= int(parent.get("max_review_rounds", 3)):
        store.append_event(parent_session_id, schema.make_event(
            parent_session_id, "review_loop_capped", "relay", "review loop capped",
            {"review_round": round_no, "review_session_id": review_session_id},
            sequence=store.next_sequence(parent_session_id),
        ))
        store.transition_session(parent_session_id, "needs_decision", actor="relay", reason="review cap reached")
        return store.get_session(parent_session_id)

    store.transition_session(parent_session_id, "changes_requested", actor="relay", reason="review feedback")
    return store.get_session(parent_session_id)
