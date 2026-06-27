"""
relay_bridge.py — bridge the existing v1 task/runtime artifacts into the v2 session store.

This keeps the current control plane running while the v2 daemon/session model grows around it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import relay_schema as schema
from relay_store import Store


def _data_dir() -> Path:
    return Path(os.getenv("DATA_DIR", "data"))


def session_id_for_task(task: str) -> str:
    return f"task_{task}"


def _meta(task: str) -> dict[str, Any]:
    p = _data_dir() / task / "meta.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _status(task: str) -> str:
    p = _data_dir() / task / "status.md"
    if not p.exists():
        return ""
    txt = p.read_text(encoding="utf-8").strip()
    return txt.splitlines()[-1] if txt else ""


def _mapped_state(task: str) -> str:
    last = _status(task)
    head = last.split()[0] if last else "MISSING"
    active = (_data_dir() / task / "active").exists()
    mapping = {
        "PROGRESS": "running" if active else "paused",
        "DONE": "done",
        "RATE_LIMITED": "rate_limited",
        "ERROR": "error" if active else "needs_decision",
        "HELD": "held",
        "MISSING": "error",
    }
    return mapping.get(head, "running" if active else "paused")


def _status_detail(task: str) -> str:
    last = _status(task).strip()
    if not last:
        return "worker state unknown"
    parts = last.split(None, 2)
    if len(parts) >= 2 and parts[0] == "ERROR":
        return parts[1]
    if len(parts) >= 2 and parts[0] == "RATE_LIMITED":
        return "worker hit provider quota/usage limit"
    return last


def ensure_session_for_task(task: str, store: Store | None = None) -> dict[str, Any]:
    store = store or Store()
    sid = session_id_for_task(task)
    try:
        return store.get_session(sid)
    except FileNotFoundError:
        meta = _meta(task)
        doc = schema.default_session(
            task_id=task,
            repo=meta.get("repo", ""),
            project_path=meta.get("project", "."),
            role=meta.get("role", "implementer"),
            tier=str(meta.get("tier", "1")),
            lane=meta.get("lane", ""),
            provider=meta.get("provider", meta.get("lane", "")),
            model=meta.get("model", meta.get("lane", "")),
            effort=meta.get("effort") or "medium",
            selection_mode=meta.get("selection_mode", "auto"),
            selection_reason=meta.get("selection_reason", "bridged from v1 runtime"),
            alternatives=[],
            max_review_rounds=3,
        )
        doc["session_id"] = sid
        doc["brief_path"] = "brief.md"
        doc["worktree_path"] = meta.get("worktree", "")
        doc["state"] = _mapped_state(task)
        created = store.create_session(doc)
        v1_brief = _data_dir() / task / "brief.md"
        if v1_brief.exists():
            (store.session_dir(sid) / "brief.md").write_text(v1_brief.read_text(encoding="utf-8"),
                                                             encoding="utf-8")
        return created


def sync_task(task: str, reason: str = "v1 sync", store: Store | None = None) -> dict[str, Any]:
    store = store or Store()
    sess = ensure_session_for_task(task, store=store)
    meta = _meta(task)
    target = _mapped_state(task)

    def mutate(doc: dict[str, Any]) -> None:
        doc["repo"] = meta.get("repo", doc.get("repo", ""))
        doc["project_path"] = meta.get("project", doc.get("project_path", "."))
        doc["tier"] = str(meta.get("tier", doc.get("tier", "1")))
        doc["lane"] = meta.get("lane", doc.get("lane", ""))
        doc["provider"] = meta.get("provider", meta.get("lane", doc.get("provider", "")))
        doc["model"] = meta.get("model", meta.get("lane", doc.get("model", "")))
        if meta.get("effort"):
            doc["effort"] = meta["effort"]
        doc["worktree_path"] = meta.get("worktree", doc.get("worktree_path", ""))

    store.update_session(sess["session_id"], mutate)
    current = store.get_session(sess["session_id"])
    if current["state"] != target:
        if target == "needs_decision":
            return mark_needs_decision(task, _status_detail(task), store=store)
        try:
            return store.transition_session(sess["session_id"], target, actor="relay-bridge", reason=reason)
        except ValueError:
            # keep the bridge resilient while v1 and v2 semantics differ
            def force(doc: dict[str, Any]) -> None:
                doc["state"] = target
            return store.update_session(sess["session_id"], force)
    return current


def mark_review_pending(task: str, tier: str, pr: str, store: Store | None = None) -> dict[str, Any]:
    store = store or Store()
    sess = ensure_session_for_task(task, store=store)
    seq = store.next_sequence(sess["session_id"])
    store.append_event(sess["session_id"], schema.make_event(
        sess["session_id"], "review_requested", "relay-bridge",
        f"PR {pr} filed for review", {"task": task, "tier": tier, "pr": pr}, sequence=seq,
    ))
    target = "held" if str(tier) == "2" else "review_requested"
    try:
        return store.transition_session(sess["session_id"], target, actor="relay-bridge", reason=f"pr {pr}")
    except ValueError:
        def force(doc: dict[str, Any]) -> None:
            doc["state"] = target
        return store.update_session(sess["session_id"], force)


def mark_needs_decision(task: str, detail: str, hold: bool = False, store: Store | None = None) -> dict[str, Any]:
    store = store or Store()
    sess = ensure_session_for_task(task, store=store)
    seq = store.next_sequence(sess["session_id"])
    store.append_event(sess["session_id"], schema.make_event(
        sess["session_id"], "needs_decision", "relay-bridge", detail,
        {"task": task, "hold": hold}, sequence=seq,
    ))
    target = "held" if hold else "needs_decision"
    try:
        return store.transition_session(sess["session_id"], target, actor="relay-bridge", reason=detail)
    except ValueError:
        def force(doc: dict[str, Any]) -> None:
            doc["state"] = target
        return store.update_session(sess["session_id"], force)


def _task_from_session(session: dict[str, Any]) -> str | None:
    sid = session.get("session_id", "")
    if isinstance(sid, str) and sid.startswith("task_"):
        return sid[len("task_"):]
    return None


def transcript_text(session_id: str, store: Store | None = None) -> str:
    store = store or Store()
    sess = store.get_session(session_id)
    task = _task_from_session(sess)
    if task:
        p = _data_dir() / task / "worker.log"
    else:
        p = store.transcript_path(session_id)
    return p.read_text(errors="ignore") if p.exists() else ""


def evidence_summary(session_id: str, store: Store | None = None) -> dict[str, Any]:
    store = store or Store()
    sess = store.get_session(session_id)
    task = _task_from_session(sess)
    if task:
        base = _data_dir() / task / "evidence"
    else:
        base = store.evidence_dir(session_id)
    shots = sorted(str(p.name) for p in (base / "screenshots").glob("*.png")) if (base / "screenshots").exists() else []
    return {
        "base_dir": str(base),
        "summary_exists": (base / "summary.md").exists(),
        "pytest_exists": (base / "pytest.txt").exists(),
        "screenshots": shots,
        "summary_text": (base / "summary.md").read_text(encoding="utf-8") if (base / "summary.md").exists() else "",
        "pytest_text": (base / "pytest.txt").read_text(encoding="utf-8") if (base / "pytest.txt").exists() else "",
    }


def session_diff_text(session_id: str, store: Store | None = None) -> str:
    store = store or Store()
    sess = store.get_session(session_id)
    wt = sess.get("worktree_path", "")
    if not wt or not Path(wt).exists():
        return ""
    base = subprocess.run(
        ["git", "-C", wt, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
        capture_output=True, text=True
    ).stdout.strip()
    base = base.split("/")[-1] if base else "main"
    committed = subprocess.run(["git", "-C", wt, "diff", f"origin/{base}...HEAD"],
                               capture_output=True, text=True).stdout
    working = subprocess.run(["git", "-C", wt, "diff"], capture_output=True, text=True).stdout
    return committed + working
