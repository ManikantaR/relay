"""Unit tests for relay's pure logic — lane routing, the evidence gate, the contract gate,
and worker-exit classification. The safety-critical bits (evidence gate, exit classification)
get the most coverage. Run: cd relay && python3 -m pytest -q
"""
import importlib.util
import json
import io
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

PY = Path(__file__).resolve().parents[1] / "py"
sys.path.insert(0, str(PY))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


spawn = _load("relay_spawn")
models = _load("relay_models")
ctrl = _load("relay_control")
finish = _load("relay_finish")
lanes = _load("relay_lanes")
schema = _load("relay_schema")
store = _load("relay_store")
state = _load("relay_state")
daemon = _load("relay_daemon")
review = _load("relay_review")
bridge = _load("relay_bridge")
from relay_board import Ticket  # noqa: E402


# ------------------------------------------------------- lane configuration & availability
def test_configured_lanes_default(monkeypatch):
    monkeypatch.delenv("RELAY_LANES", raising=False)
    monkeypatch.delenv("RELAY_LANE", raising=False)
    assert lanes.configured_lanes() == ["claude"]

def test_configured_lanes_custom(monkeypatch):
    monkeypatch.setenv("RELAY_LANES", "copilot,agy,invalid,claude")
    assert lanes.configured_lanes() == ["copilot", "agy", "claude"]

def test_strict_governance(monkeypatch):
    monkeypatch.delenv("RELAY_STRICT_LANES", raising=False)
    assert lanes.strict() is False
    monkeypatch.setenv("RELAY_STRICT_LANES", "1")
    assert lanes.strict() is True
    monkeypatch.setenv("RELAY_STRICT_LANES", "false")
    assert lanes.strict() is False

def test_available_lanes_uses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RELAY_LANES", "copilot,claude")
    
    # Write a mock cache
    cache = tmp_path / ".lanes.json"
    import json, time
    cache.write_text(json.dumps({"at": time.time(), "lanes": ["copilot"]}))
    
    # It should read from cache and filter by configured
    assert lanes.available_lanes(refresh=False) == ["copilot"]

def test_available_lanes_refreshes_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RELAY_LANES", "copilot,claude")
    import json
    
    # Mock auth_probe: only copilot is authed
    monkeypatch.setattr(lanes, "auth_probe", lambda l: l == "copilot")
    
    # Should run auth_probe and write cache
    assert lanes.available_lanes(refresh=True) == ["copilot"]
    
    # Verify cache file exists and has correct lanes
    cache = tmp_path / ".lanes.json"
    assert cache.exists()
    data = json.loads(cache.read_text())
    assert data["lanes"] == ["copilot"]



# ------------------------------------------------------- evidence gate (safety-critical)
def _evi(tmp_path, monkeypatch):
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    d = tmp_path / "t1" / "evidence"
    (d / "screenshots").mkdir(parents=True)
    return d

def test_evidence_fails_empty(tmp_path, monkeypatch):
    _evi(tmp_path, monkeypatch)
    ok, have = ctrl.evidence_ok("t1")
    assert ok is False and have == []

def test_evidence_fails_summary_only(tmp_path, monkeypatch):
    d = _evi(tmp_path, monkeypatch)
    (d / "summary.md").write_text("did stuff")
    ok, _ = ctrl.evidence_ok("t1")
    assert ok is False                      # summary alone is not proof

def test_evidence_passes_summary_plus_pytest(tmp_path, monkeypatch):
    d = _evi(tmp_path, monkeypatch)
    (d / "summary.md").write_text("did stuff"); (d / "pytest.txt").write_text("5 passed")
    assert ctrl.evidence_ok("t1")[0] is True

def test_evidence_passes_summary_plus_screenshot(tmp_path, monkeypatch):
    d = _evi(tmp_path, monkeypatch)
    (d / "summary.md").write_text("x"); (d / "screenshots" / "flow.png").write_bytes(b"\x89PNG")
    assert ctrl.evidence_ok("t1")[0] is True


# ------------------------------------------------------- contract gate (auto-dispatch)
def _t(body, labels):
    return Ticket("9", "title", body, "2" if "tier-2" in labels else "1", labels)

def test_contract_needs_tier_label():
    assert ctrl._contract_ok(_t("a" * 50, ["phase:2"])) is False

def test_contract_needs_real_body():
    assert ctrl._contract_ok(_t("short", ["tier-1"])) is False

def test_contract_ok_with_tier_and_body():
    assert ctrl._contract_ok(_t("a real spec with a stop condition " * 2, ["tier-1"])) is True


# ------------------------------------------------------- exit classification (no agent trust)
def _fin(tmp_path, monkeypatch, log_text=""):
    monkeypatch.setattr(finish, "DATA", tmp_path)
    (tmp_path / "t1").mkdir()
    if log_text:
        (tmp_path / "t1" / "worker.log").write_text(log_text)

def test_finish_done_on_zero(tmp_path, monkeypatch):
    _fin(tmp_path, monkeypatch, "all good\n")
    assert finish.classify("t1", "0") == "DONE"

def test_finish_error_on_nonzero(tmp_path, monkeypatch):
    _fin(tmp_path, monkeypatch, "boom traceback\n")
    assert finish.classify("t1", "1") == "ERROR exit=1"

def test_finish_rate_limited_from_log(tmp_path, monkeypatch):
    _fin(tmp_path, monkeypatch, "Error: usage limit reached, try again later\n")
    assert finish.classify("t1", "1") == "RATE_LIMITED"

def test_finish_usage_credits_required_counts_as_rate_limited(tmp_path, monkeypatch):
    _fin(tmp_path, monkeypatch, "Usage credits required for 1M context\n")
    assert finish.classify("t1", "1") == "RATE_LIMITED"

def test_finish_zero_beats_stale_ratelimit_text(tmp_path, monkeypatch):
    # a clean exit is DONE even if the log mentions limits earlier
    _fin(tmp_path, monkeypatch, "hit rate limit once, recovered\n")
    assert finish.classify("t1", "0") == "DONE"


# ------------------------------------------------------- lane preference + resolution (§12)
def test_pref_override_is_explicit():
    assert lanes.lane_preference([], "agy") == ("agy", True)

def test_pref_label_is_explicit():
    assert lanes.lane_preference(["lane:codex", "phase:4"]) == ("codex", True)

def test_pref_default_is_top_of_ladder_not_explicit(monkeypatch):
    monkeypatch.setenv("RELAY_LANES", "copilot,claude")
    assert lanes.lane_preference(["phase:2"]) == ("copilot", False)

def test_tier2_forces_claude():
    assert lanes.resolve_lane("agy", True, "2", ["copilot", "agy", "claude"], is_strict=False) \
        == ("claude", "tier2-forced-claude")

def test_tier2_waits_when_claude_unavailable():
    lane, reason = lanes.resolve_lane("claude", True, "2", ["copilot", "agy"], is_strict=False)
    assert lane is None and reason == "tier2-claude-unavailable"

def test_preferred_when_available():
    assert lanes.resolve_lane("agy", True, "1", ["copilot", "agy", "claude"], is_strict=False) \
        == ("agy", "preferred")

def test_substitute_down_ladder_when_unavailable():
    assert lanes.resolve_lane("agy", True, "1", ["copilot", "claude"], is_strict=False) \
        == ("copilot", "substitute:agy->copilot")

def test_strict_holds_explicit_unsanctioned():
    lane, reason = lanes.resolve_lane("agy", True, "1", ["claude"], is_strict=True)
    assert lane is None and reason.startswith("strict-hold")

def test_strict_does_not_hold_implicit_default():
    # no-label issue at work just runs the sanctioned default — no hold
    assert lanes.resolve_lane("copilot", False, "1", ["claude"], is_strict=True) \
        == ("claude", "substitute:copilot->claude")

def test_failover_picks_next_untried_lane():
    # copilot capped (tried) -> next available untried is agy
    assert lanes.resolve_lane("copilot", False, "1", ["copilot", "agy", "claude"],
                              tried=["copilot"], is_strict=False) \
        == ("agy", "substitute:copilot->agy")

def test_failover_exhausted_when_all_tried():
    lane, reason = lanes.resolve_lane("copilot", False, "1", ["copilot", "agy", "claude"],
                                      tried=["copilot", "agy", "claude"], is_strict=False)
    assert lane is None and reason == "all-lanes-exhausted"


# ------------------------------------------------------- multi-repo registry
def test_task_id_is_repo_qualified_no_collision():
    # same issue number in two repos must not collide
    assert ctrl.task_id("ManikantaR/smartocrprocess", 12) == "smartocrprocess-12"
    assert ctrl.task_id("Org/MoneyPulse", 12) == "moneypulse-12"
    assert ctrl.task_id("a/x", 12) != ctrl.task_id("a/y", 12)

def test_projects_parses_registry(monkeypatch):
    monkeypatch.setenv("RELAY_PROJECTS", "a/b=/p1, c/d=/p2")
    assert ctrl.projects() == [("a/b", "/p1"), ("c/d", "/p2")]

def test_projects_falls_back_to_single_repo(monkeypatch):
    monkeypatch.delenv("RELAY_PROJECTS", raising=False)
    monkeypatch.setenv("GITHUB_REPO", "x/y")
    monkeypatch.setattr(ctrl.CFG, "project", "/proj")
    assert ctrl.projects() == [("x/y", "/proj")]

def test_get_board_uses_passed_repo(monkeypatch):
    import relay_board
    monkeypatch.setenv("RELAY_PROFILE", "personal")
    assert relay_board.get_board("owner/repo").repo == "owner/repo"


# ------------------------------------------------------- v2 session schema + state/store
def test_default_session_validates():
    sess = schema.default_session("repo-12", "o/r", "/tmp/proj")
    assert schema.validate_session(sess) == []
    assert sess["state"] == "queued"

def test_event_validates():
    ev = schema.make_event("sess_x", "session_created", "relay", "created", sequence=1)
    assert schema.validate_event(ev) == []

def test_state_machine_allows_running_to_paused():
    assert state.can_transition("running", "paused") is True
    assert state.transition("running", "paused").to == "paused"

def test_state_machine_rejects_done_to_running():
    with pytest.raises(ValueError):
        state.transition("done", "running")

def test_store_creates_session_and_indexes_it(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    st.create_session(sess)
    got = st.get_session(sess["session_id"])
    assert got["task_id"] == "repo-12"
    assert st.timeline(sess["session_id"])[0]["type"] == "session_created"

def test_store_pause_and_nudge(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    st.create_session(sess)
    st.transition_session(sess["session_id"], "running")
    st.add_nudge(sess["session_id"], "owner", "goal_correction", "focus on AC2")
    got = st.get_session(sess["session_id"])
    assert got["state"] == "paused"
    types = [e["type"] for e in st.timeline(sess["session_id"])]
    assert "operator_nudge" in types

def test_store_rebuild_index_from_disk(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    st.create_session(sess)
    st.transition_session(sess["session_id"], "running")
    st.transition_session(sess["session_id"], "paused")
    st2 = store.Store(tmp_path)
    rows = st2.list_sessions()
    assert len(rows) == 1
    assert rows[0]["state"] == "paused"
    assert len(st2.timeline(sess["session_id"])) >= 3


# ------------------------------------------------------- daemon API contract
def test_daemon_health_endpoint(tmp_path):
    st = store.Store(tmp_path)
    status, body = daemon.handle_request("GET", "/api/health", {}, st)
    assert status == 200
    assert body["status"] == "ok"

def test_daemon_dispatch_pause_resume_nudge(tmp_path):
    st = store.Store(tmp_path)
    status, created = daemon.handle_request("POST", "/api/dispatch", {
        "task_id": "repo-12",
        "repo": "o/r",
        "project_path": "/proj",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "selection_reason": "test dispatch"
    }, st)
    assert status == 201
    sid = created["session_id"]

    status, body = daemon.handle_request("POST", f"/api/sessions/{sid}/resume", {}, st)
    assert status == 200
    assert body["state"] == "running"

    status, body = daemon.handle_request("POST", f"/api/sessions/{sid}/pause", {}, st)
    assert status == 200
    assert body["state"] == "paused"

    status, _body = daemon.handle_request("POST", f"/api/sessions/{sid}/nudge", {
        "actor": "owner",
        "nudge_type": "goal_correction",
        "message": "refocus"
    }, st)
    assert status == 200

    status, timeline = daemon.handle_request("GET", f"/api/sessions/{sid}/timeline", {}, st)
    assert status == 200
    assert any(e["type"] == "operator_nudge" for e in timeline["events"])

def test_daemon_request_review_and_submit_changes(tmp_path):
    st = store.Store(tmp_path)
    status, created = daemon.handle_request("POST", "/api/dispatch", {
        "task_id": "repo-12",
        "repo": "o/r",
        "project_path": "/proj",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "selection_reason": "test dispatch"
    }, st)
    assert status == 201
    sid = created["session_id"]
    daemon.handle_request("POST", f"/api/sessions/{sid}/resume", {}, st)

    status, reviewer = daemon.handle_request("POST", f"/api/sessions/{sid}/request-review", {}, st)
    assert status == 201
    assert reviewer["role"] == "reviewer"

    status, parent = daemon.handle_request("POST", f"/api/sessions/{sid}/submit-review", {
        "review_session_id": reviewer["session_id"],
        "approved": False,
        "comments": [{"path": "a.py", "line": 3, "message": "tighten this check"}]
    }, st)
    assert status == 200
    assert parent["state"] == "changes_requested"
    assert parent["review_round"] == 1

def test_daemon_request_review_and_submit_approval(tmp_path):
    st = store.Store(tmp_path)
    status, created = daemon.handle_request("POST", "/api/dispatch", {
        "task_id": "repo-12",
        "repo": "o/r",
        "project_path": "/proj",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "selection_reason": "test dispatch"
    }, st)
    assert status == 201
    sid = created["session_id"]
    daemon.handle_request("POST", f"/api/sessions/{sid}/resume", {}, st)

    status, reviewer = daemon.handle_request("POST", f"/api/sessions/{sid}/request-review", {}, st)
    assert status == 201

    status, parent = daemon.handle_request("POST", f"/api/sessions/{sid}/submit-review", {
        "review_session_id": reviewer["session_id"],
        "approved": True,
        "comments": []
    }, st)
    assert status == 200
    assert parent["state"] == "approved"

def test_daemon_terminate_ack_checkpoint(tmp_path):
    st = store.Store(tmp_path)
    status, created = daemon.handle_request("POST", "/api/dispatch", {
        "task_id": "repo-12",
        "repo": "o/r",
        "project_path": "/proj",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "selection_reason": "test dispatch"
    }, st)
    assert status == 201
    sid = created["session_id"]
    daemon.handle_request("POST", f"/api/sessions/{sid}/resume", {}, st)

    status, body = daemon.handle_request("POST", f"/api/sessions/{sid}/request-checkpoint", {
        "actor": "owner", "summary": "checkpoint now"
    }, st)
    assert status == 200
    assert any(e["type"] == "checkpoint_written" for e in st.timeline(sid))

    daemon.handle_request("POST", f"/api/sessions/{sid}/pause", {}, st)
    status, body = daemon.handle_request("POST", f"/api/sessions/{sid}/ack-decision", {
        "actor": "owner", "target_state": "running", "reason": "resume after decision"
    }, st)
    assert status == 200
    assert body["state"] == "running"

    status, body = daemon.handle_request("POST", f"/api/sessions/{sid}/terminate", {
        "actor": "owner", "reason": "stop trial"
    }, st)
    assert status == 200
    assert body["state"] == "terminated"

def test_daemon_refresh_bridged_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "active").touch()
    st = store.Store(tmp_path)
    bridge.ensure_session_for_task("smartocrprocess-12", store=st)
    status, body = daemon.handle_request("POST", "/api/sessions/task_smartocrprocess-12/refresh", {}, st)
    assert status == 200
    assert body["state"] == "running"


# ------------------------------------------------------- review loop engine
def test_spawn_reviewer_session(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    st.create_session(sess)
    st.transition_session(sess["session_id"], "running")
    reviewer = review.spawn_reviewer(st, sess["session_id"])
    assert reviewer["role"] == "reviewer"
    parent = st.get_session(sess["session_id"])
    assert parent["state"] == "review_requested"
    assert parent["review_session_id"] == reviewer["session_id"]

def test_review_changes_requested_appends_brief_and_changes_state(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    st.transition_session(created["session_id"], "running")
    reviewer = review.spawn_reviewer(st, created["session_id"])
    parent = review.submit_review(
        st,
        created["session_id"],
        reviewer["session_id"],
        comments=[{"path": "backend/main.py", "line": 12, "message": "handle missing token"}],
        approved=False,
    )
    assert parent["state"] == "changes_requested"
    assert parent["review_round"] == 1
    brief = (st.session_dir(created["session_id"]) / created["brief_path"]).read_text()
    assert "Review Feedback Round 1" in brief
    assert "backend/main.py:12" in brief

def test_review_approval_marks_parent_approved(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    st.transition_session(created["session_id"], "running")
    reviewer = review.spawn_reviewer(st, created["session_id"])
    parent = review.submit_review(st, created["session_id"], reviewer["session_id"], comments=[], approved=True)
    assert parent["state"] == "approved"

def test_review_cap_forces_needs_decision(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj", max_review_rounds=1)
    created = st.create_session(sess)
    st.transition_session(created["session_id"], "running")
    reviewer = review.spawn_reviewer(st, created["session_id"])
    parent = review.submit_review(
        st,
        created["session_id"],
        reviewer["session_id"],
        comments=[{"path": "a.py", "line": 1, "message": "fix this"}],
        approved=False,
    )
    assert parent["state"] == "needs_decision"
    assert any(e["type"] == "review_loop_capped" for e in st.timeline(created["session_id"]))


# ------------------------------------------------------- v1 -> v2 bridge
def test_bridge_sync_creates_session_from_v1_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r",
        "project": "/proj",
        "tier": "1",
        "lane": "claude",
        "worktree": "/proj/.worktrees/t12",
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "active").touch()
    st = store.Store(tmp_path)
    sess = bridge.sync_task("smartocrprocess-12", store=st)
    assert sess["session_id"] == "task_smartocrprocess-12"
    got = st.get_session(sess["session_id"])
    assert got["state"] == "running"
    assert got["repo"] == "o/r"

def test_bridge_mark_review_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    st = store.Store(tmp_path)
    bridge.ensure_session_for_task("smartocrprocess-12", store=st)
    sess = bridge.mark_review_pending("smartocrprocess-12", "1", "45", store=st)
    assert sess["state"] == "review_requested"
    assert any(e["type"] == "review_requested" for e in st.timeline(sess["session_id"]))

def test_bridge_mark_needs_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("ERROR exit=1 2026-06-26T00:00:00+00:00\n")
    st = store.Store(tmp_path)
    bridge.ensure_session_for_task("smartocrprocess-12", store=st)
    sess = bridge.mark_needs_decision("smartocrprocess-12", "worker errored", store=st)
    assert sess["state"] == "needs_decision"

def test_bridge_sync_maps_inactive_error_to_needs_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "2", "lane": "claude"
    }))
    (td / "status.md").write_text("ERROR exit=1 2026-06-26T00:00:00+00:00\n")
    st = store.Store(tmp_path)
    bridge.ensure_session_for_task("smartocrprocess-12", store=st)
    st.update_session("task_smartocrprocess-12", lambda doc: doc.update({"state": "error"}))
    sess = bridge.sync_task("smartocrprocess-12", store=st)
    assert sess["state"] == "needs_decision"
    assert any(e["type"] == "needs_decision" for e in st.timeline(sess["session_id"]))


# ------------------------------------------------------- v2 CLI session inspection
def test_cli_sessions_lists_bridged_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "active").touch()
    old = sys.stdout
    buf = io.StringIO()
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    try:
        sys.stdout = buf
        assert cli.cmd_sessions([]) == 0
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "task_smartocrprocess-12" in out
    assert "running" in out

def test_cli_session_json_detail(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_session([created["session_id"], "--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["session_id"] == created["session_id"]

def test_cli_timeline_json(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    st.transition_session(created["session_id"], "running")
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_timeline([created["session_id"], "--json"]) == 0
    finally:
        sys.stdout = old
    rows = json.loads(buf.getvalue())
    assert any(e["type"] == "state_changed" for e in rows)

def test_cli_board_uses_v2_sessions_for_active(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "active").touch()
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    monkeypatch.setattr(cli, "get_board", lambda repo: type("B", (), {
        "pull_ready": lambda self: [],
        "pull_review": lambda self: [],
    })())
    monkeypatch.setattr(cli.ctrl, "projects", lambda: [("o/r", "/proj")])
    monkeypatch.setattr(cli.lanes, "available_lanes", lambda refresh=False: ["claude"])
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_board(["--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert len(data["active"]) == 1
    assert data["active"][0]["session_id"] == "task_smartocrprocess-12"

def test_cli_doctor_reports_ready_project_and_sessions(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    project = tmp_path / "smartocrprocess"
    (project / ".crew").mkdir(parents=True)
    (project / ".git").mkdir()
    (project / ".crew" / "project.md").write_text("area: x\n")
    (project / ".crew" / "tier2-paths.txt").write_text("storage.py\n")
    (project / ".crew" / "protected-tests.txt").write_text("tests/test_storage.py\n")
    (tmp_path / "vscode" / "out").mkdir(parents=True)
    (tmp_path / "vscode" / "package.json").write_text("{}\n")
    (tmp_path / "vscode" / "out" / "extension.js").write_text("// bundle\n")
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": str(project), "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "active").touch()
    cli = _load("relay_cli")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    monkeypatch.setattr(cli.ctrl, "projects", lambda: [("o/r", str(project))])
    monkeypatch.setattr(cli.shutil, "which", lambda tool: f"/usr/bin/{tool}")

    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True, timeout=10):
        assert cmd == ["gh", "auth", "status", "-h", "github.com"]
        return Result(0, stdout="Logged in to github.com\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_doctor(["--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["status"] == "pass"
    assert data["sessions_active"] == 1
    assert any(c["key"] == "github_auth" and c["status"] == "pass" for c in data["checks"])

def test_cli_doctor_flags_invalid_github_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    project = tmp_path / "smartocrprocess"
    (project / ".crew").mkdir(parents=True)
    (project / ".crew" / "project.md").write_text("area: x\n")
    (project / ".crew" / "tier2-paths.txt").write_text("storage.py\n")
    (project / ".crew" / "protected-tests.txt").write_text("tests/test_storage.py\n")
    (tmp_path / "vscode" / "out").mkdir(parents=True)
    (tmp_path / "vscode" / "package.json").write_text("{}\n")
    (tmp_path / "vscode" / "out" / "extension.js").write_text("// bundle\n")
    cli = _load("relay_cli")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)
    monkeypatch.setattr(cli.ctrl, "projects", lambda: [("o/r", str(project))])
    monkeypatch.setattr(cli.shutil, "which", lambda tool: None if tool in {"tmux", "vsce"} else f"/usr/bin/{tool}")

    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output=True, text=True, timeout=10):
        return Result(1, stderr="The token in default is invalid.\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_doctor(["--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["status"] == "fail"
    assert any(c["key"] == "github_auth" and c["status"] == "fail" for c in data["checks"])
    assert any(c["key"] == "vscode_packaging" and c["status"] == "warn" for c in data["checks"])
    assert any("gh auth login -h github.com" in step for step in data["next_actions"])

def test_cli_vscode_package_uses_local_vsce(tmp_path, monkeypatch):
    cli = _load("relay_cli")
    vscode = tmp_path / "vscode"
    (vscode / "node_modules" / ".bin").mkdir(parents=True)
    (vscode / "node_modules" / ".bin" / "vsce").write_text("")
    (vscode / "package.json").write_text(json.dumps({"name": "relay-control", "version": "0.1.0"}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda tool: "/usr/bin/npm" if tool == "npm" else None)

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=60):
        calls.append((cmd, cwd))
        return Result(stdout="ok\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_vscode_package(["--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["vsix"].endswith("vscode/relay-control-0.1.0.vsix")
    assert calls[0][0] == ["npm", "run", "compile"]
    assert calls[1][0][0].endswith("vscode/node_modules/.bin/vsce")
    assert calls[1][0][1:4] == ["package", "--no-dependencies", "-o"]

def test_cli_vscode_install_invokes_code_with_vsix(tmp_path, monkeypatch):
    cli = _load("relay_cli")
    vscode = tmp_path / "vscode"
    vscode.mkdir()
    (vscode / "relay-control-0.1.0.vsix").write_text("vsix")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda tool: "/opt/homebrew/bin/code" if tool == "code" else None)

    calls = []

    class Result:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, cwd=None, capture_output=True, text=True, timeout=60):
        calls.append((cmd, cwd))
        return Result(stdout="installed\n")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_vscode_install(["--vsix", str(vscode / "relay-control-0.1.0.vsix"), "--force", "--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["vsix"].endswith("relay-control-0.1.0.vsix")
    assert calls[0][0] == [
        "/opt/homebrew/bin/code",
        "--install-extension",
        str(vscode / "relay-control-0.1.0.vsix"),
        "--force",
    ]

def test_cli_transcript_and_evidence_json_for_bridged_session(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "smartocrprocess-12"
    (td / "evidence" / "screenshots").mkdir(parents=True)
    td.mkdir(exist_ok=True)
    (td / "meta.json").write_text(json.dumps({
        "repo": "o/r", "project": "/proj", "tier": "1", "lane": "claude"
    }))
    (td / "status.md").write_text("PROGRESS 2026-06-26T00:00:00+00:00\n")
    (td / "worker.log").write_text("worker output\n")
    (td / "evidence" / "summary.md").write_text("did stuff\n")
    (td / "evidence" / "pytest.txt").write_text("5 passed\n")
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)

    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_transcript(["task_smartocrprocess-12", "--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert "worker output" in data["transcript"]

    buf = io.StringIO()
    old = sys.stdout
    try:
        sys.stdout = buf
        assert cli.cmd_evidence(["task_smartocrprocess-12", "--json"]) == 0
    finally:
        sys.stdout = old
    evidence = json.loads(buf.getvalue())
    assert evidence["summary_exists"] is True
    assert evidence["pytest_exists"] is True

def test_daemon_transcript_and_evidence_endpoints(tmp_path):
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    (st.transcript_path(created["session_id"])).write_text("hello transcript\n")
    (st.evidence_dir(created["session_id"]) / "summary.md").write_text("summary\n")
    status, body = daemon.handle_request("GET", f"/api/sessions/{created['session_id']}/transcript", {}, st)
    assert status == 200
    assert "hello transcript" in body["transcript"]
    status, body = daemon.handle_request("GET", f"/api/sessions/{created['session_id']}/evidence", {}, st)
    assert status == 200
    assert body["summary_exists"] is True

def test_cli_session_action_commands(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    st = store.Store(tmp_path)
    sess = schema.default_session("repo-12", "o/r", "/proj")
    created = st.create_session(sess)
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)

    assert cli.cmd_session_checkpoint([created["session_id"], "--summary", "save point"]) == 0
    assert any(e["type"] == "checkpoint_written" for e in st.timeline(created["session_id"]))
    assert cli.cmd_session_terminate([created["session_id"]]) == 0
    assert st.get_session(created["session_id"])["state"] == "terminated"

def test_cli_session_reconcile_marks_needs_decision_tasks_not_ready(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "smartocrprocess-12"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "item": "12", "repo": "o/r", "project": "/proj", "tier": "2", "lane": "claude"
    }))
    (td / "status.md").write_text("ERROR exit=1 2026-06-26T00:00:00+00:00\n")
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)

    actions = []
    class FakeBoard:
        def remove_label(self, ticket_id, label): actions.append(("remove", ticket_id, label))
        def apply_label(self, ticket_id, label): actions.append(("add", ticket_id, label))

    monkeypatch.setattr(cli, "get_board", lambda repo: FakeBoard())
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_session_reconcile(["task_smartocrprocess-12", "--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["state"] == "needs_decision"
    assert ("remove", "12", "agent-wip") in actions
    assert ("remove", "12", "agent-ready") in actions

def test_cli_session_reconcile_marks_done_tasks_reviewing(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "smartocrprocess-44"
    td.mkdir()
    (td / "meta.json").write_text(json.dumps({
        "item": "44", "repo": "o/r", "project": "/proj", "tier": "1", "lane": "copilot"
    }))
    (td / "status.md").write_text("DONE 2026-06-26T00:00:00+00:00\n")
    cli = _load("relay_cli")
    monkeypatch.setattr(cli.ctrl.CFG, "data_dir", tmp_path)

    actions = []
    class FakeBoard:
        def remove_label(self, ticket_id, label): actions.append(("remove", ticket_id, label))
        def apply_label(self, ticket_id, label): actions.append(("add", ticket_id, label))

    monkeypatch.setattr(cli, "get_board", lambda repo: FakeBoard())
    old = sys.stdout
    buf = io.StringIO()
    try:
        sys.stdout = buf
        assert cli.cmd_session_reconcile(["task_smartocrprocess-44", "--json"]) == 0
    finally:
        sys.stdout = old
    data = json.loads(buf.getvalue())
    assert data["state"] == "done"
    assert ("remove", "44", "agent-ready") in actions
    assert ("remove", "44", "agent-wip") in actions
    assert ("add", "44", "agent-review") in actions


# ------------------------------------------------------- model policy (token-burn fix, §11)
def _clear_model_env(mp):
    for k in ("RELAY_CLAUDE_MODEL", "RELAY_CLAUDE_EFFORT", "RELAY_MAX_BUDGET_USD", "RELAY_PROFILE"):
        mp.delenv(k, raising=False)
    # neutralize any real ~/.config/relay/models.yml so default tests are hermetic
    mp.setenv("RELAY_MODELS_FILE", "/nonexistent/relay-models-test.yml")


def test_resolve_implementer_defaults_to_sonnet(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("claude")
    assert spec["model"] == "sonnet"
    assert spec["model_id"] == "claude-sonnet-4-6"
    assert spec["provider"] == "anthropic"
    assert spec["effort"] == "medium"
    assert spec["selection_mode"] == "auto"


def test_resolve_reviewer_defaults_to_opus(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("claude", role="reviewer")
    assert spec["model_id"] == "claude-opus-4-8"
    assert spec["effort"] == "medium"


def test_resolve_tier2_reviewer_uses_high_effort(monkeypatch):
    _clear_model_env(monkeypatch)
    assert models.resolve("claude", role="reviewer", tier="2")["effort"] == "high"
    # tier-2 implementer stays on the cheap default
    assert models.resolve("claude", role="implementer", tier="2")["model"] == "sonnet"


def test_resolve_env_override_wins(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("RELAY_CLAUDE_MODEL", "opus")
    monkeypatch.setenv("RELAY_CLAUDE_EFFORT", "high")
    spec = models.resolve("claude")
    assert spec["model"] == "opus" and spec["effort"] == "high"
    assert spec["selection_mode"] == "override"


def test_resolve_noclaude_lane_injects_nothing(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("copilot")
    assert spec["model"] == "" and spec["model_id"] == ""
    assert spec["provider"] == "github-copilot"
    assert models.claude_flags(spec) == ""


def test_claude_harness_pins_model_and_effort(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("claude")
    cmd = spawn._harness_cmd("claude", Path("/tmp/brief.md"), "tmux", spec)
    assert "--model claude-sonnet-4-6" in cmd
    assert "--effort medium" in cmd
    assert "claude -p" in cmd


def test_noclaude_harness_has_no_model_flag(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("copilot")
    cmd = spawn._harness_cmd("copilot", Path("/tmp/brief.md"), "tmux", spec)
    assert "--model" not in cmd
    assert "copilot" in cmd


def test_claude_flags_includes_budget_when_set(monkeypatch):
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("RELAY_MAX_BUDGET_USD", "2.50")
    flags = models.claude_flags(models.resolve("claude"))
    assert "--max-budget-usd 2.5" in flags


def test_bridge_carries_real_model_id_from_meta(tmp_path, monkeypatch):
    # the token-burn fix must reach the v2 session: provider/model/effort come from meta,
    # not the lane name. Without it the session recorded model="claude" (the lane).
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    task = "repo-12"
    td = tmp_path / task
    (td / "evidence").mkdir(parents=True)
    (td / "meta.json").write_text(json.dumps({
        "tier": "2", "lane": "claude", "role": "implementer", "repo": "o/r",
        "project": "/proj", "worktree": "/wt", "provider": "anthropic",
        "model": "claude-sonnet-4-6", "effort": "medium",
        "selection_mode": "auto", "selection_reason": "default implementer",
    }))
    (td / "status.md").write_text("PROGRESS x\n")
    st = store.Store(tmp_path)
    sess = bridge.ensure_session_for_task(task, store=st)
    assert sess["model"] == "claude-sonnet-4-6"
    assert sess["provider"] == "anthropic"
    assert sess["effort"] == "medium"
    assert sess["role"] == "implementer"


# ------------------------------------------------------- verifier loop (§9, auto-wired review)
verify = _load("relay_verify")


def _wjson(d, **kw):
    (d / "review.json").write_text(json.dumps(kw))


def test_parse_review_normalizes_verdicts(tmp_path):
    ev = tmp_path / "ev"; ev.mkdir()
    _wjson(ev, verdict="LGTM", comments=[], summary="ok")
    assert verify.parse_review(ev)[0] == "approved"
    _wjson(ev, verdict="request_changes", comments=[{"path": "a.py", "line": 1, "message": "x"}])
    v, c, _ = verify.parse_review(ev)
    assert v == "changes_requested" and c[0]["path"] == "a.py"


def test_parse_review_missing_or_bad_is_unknown(tmp_path):
    ev = tmp_path / "ev"; ev.mkdir()
    assert verify.parse_review(ev)[0] == "unknown"
    (ev / "review.json").write_text("{not json")
    assert verify.parse_review(ev)[0] == "unknown"


def test_review_decision_table():
    assert verify.review_decision("approved", 1, 3) == "finalize"
    assert verify.review_decision("unknown", 1, 3) == "finalize"     # never block on a flaky reviewer
    assert verify.review_decision("changes_requested", 1, 3) == "respawn"
    assert verify.review_decision("changes_requested", 3, 3) == "needs_decision"


def test_append_feedback_writes_section(tmp_path):
    b = tmp_path / "brief.md"; b.write_text("# brief\n")
    verify.append_feedback(b, 2, [{"path": "s.py", "line": 9, "message": "fix retry"}])
    text = b.read_text()
    assert "Review feedback — round 2" in text and "`s.py:9` fix retry" in text


def test_decision_log_prefers_decisions_md(tmp_path):
    ev = tmp_path / "ev"; ev.mkdir()
    (ev / "decisions.md").write_text("Chose resumable upload; ruled out v3 chunked.")
    assert "Decision log" in verify.decision_log(ev) and "resumable" in verify.decision_log(ev)


def test_decision_log_falls_back_to_summary(tmp_path):
    ev = tmp_path / "ev"; ev.mkdir()
    (ev / "summary.md").write_text("Did the thing.\nRuled out the slow path.\nDone.")
    out = verify.decision_log(ev)
    assert "Decision log" in out and "Ruled out the slow path" in out


def test_render_review_brief_is_read_only_and_asks_for_json():
    b = verify.render_review_brief("T", "12", "2", "/ev", base="origin/main", round_no=1)
    assert "read-only" in b and "review.json" in b and "Do NOT" in b


# --- control-flow routing (mock the launches / board) -----------------------------------
def _quiet(monkeypatch):
    monkeypatch.setattr(ctrl, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ctrl, "_notify_once", lambda *a, **k: None)
    monkeypatch.setattr(ctrl, "memory_append", lambda *a, **k: None)


def _task(tmp_path, monkeypatch, meta, evidence=None, status="DONE x\n"):
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "t1"
    (td / "evidence" / "screenshots").mkdir(parents=True)
    (td / "meta.json").write_text(json.dumps(meta))
    (td / "status.md").write_text(status)
    (td / "brief.md").write_text("# brief\n")
    for name, content in (evidence or {}).items():
        (td / "evidence" / name).write_text(content)
    return td


def test_close_out_implementer_routes_to_review(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    _task(tmp_path, monkeypatch, {"phase": "implement", "worktree": ""})
    monkeypatch.setenv("RELAY_REVIEW", "1")
    monkeypatch.setattr(ctrl, "_collect_evidence", lambda t, w: None)
    monkeypatch.setattr(ctrl, "evidence_ok", lambda t: (True, ["summary.md"]))
    calls = []
    monkeypatch.setattr(ctrl, "start_review", lambda t: calls.append("review"))
    monkeypatch.setattr(ctrl, "finalize_pr", lambda t, review_note="": calls.append("finalize"))
    ctrl.close_out("t1")
    assert calls == ["review"]


def test_close_out_finalizes_when_review_disabled(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    _task(tmp_path, monkeypatch, {"phase": "implement", "worktree": ""})
    monkeypatch.setenv("RELAY_REVIEW", "0")
    monkeypatch.setattr(ctrl, "_collect_evidence", lambda t, w: None)
    monkeypatch.setattr(ctrl, "evidence_ok", lambda t: (True, ["summary.md"]))
    calls = []
    monkeypatch.setattr(ctrl, "start_review", lambda t: calls.append("review"))
    monkeypatch.setattr(ctrl, "finalize_pr", lambda t, review_note="": calls.append("finalize"))
    ctrl.close_out("t1")
    assert calls == ["finalize"]


def test_close_out_reviewer_routes_to_advance(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    _task(tmp_path, monkeypatch, {"phase": "review", "worktree": ""})
    calls = []
    monkeypatch.setattr(ctrl, "advance_review", lambda t: calls.append("advance"))
    ctrl.close_out("t1")
    assert calls == ["advance"]


def test_advance_review_approved_finalizes_and_clears_phase(tmp_path, monkeypatch):
    _quiet(monkeypatch)
    td = _task(tmp_path, monkeypatch, {"phase": "review", "review_round": 1, "tier": "1",
                                       "worktree": ""},
               evidence={"summary.md": "ok"})
    _wjson(td / "evidence", verdict="approved", comments=[], summary="great")
    notes = []
    monkeypatch.setattr(ctrl, "finalize_pr", lambda t, review_note="": notes.append(review_note))
    ctrl.advance_review("t1")
    assert notes and "approved" in notes[0]
    assert json.loads((td / "meta.json").read_text())["phase"] == "implement"


def test_advance_review_changes_respawns_implementer(tmp_path, monkeypatch):
    import importlib
    _quiet(monkeypatch)
    td = _task(tmp_path, monkeypatch, {"phase": "review", "review_round": 1, "tier": "1",
                                       "worktree": "", "max_review_rounds": 3})
    _wjson(td / "evidence", verdict="changes_requested",
           comments=[{"path": "s.py", "line": 4, "message": "add retry"}])
    relaunched = []
    monkeypatch.setattr(importlib.import_module("relay_spawn"), "relaunch",
                        lambda task, brief, role="implementer", note="": relaunched.append((brief, role)))
    monkeypatch.setattr(ctrl, "finalize_pr", lambda *a, **k: relaunched.append("FINALIZE"))
    ctrl.advance_review("t1")
    assert relaunched == [("brief.md", "implementer")]
    assert "Review feedback" in (td / "brief.md").read_text()


def test_advance_review_caps_to_needs_decision(tmp_path, monkeypatch):
    import importlib
    _quiet(monkeypatch)
    td = _task(tmp_path, monkeypatch, {"phase": "review", "review_round": 3, "tier": "1",
                                       "worktree": "", "max_review_rounds": 3})
    _wjson(td / "evidence", verdict="changes_requested", comments=[])
    seq = []
    monkeypatch.setattr(ctrl, "finalize_pr", lambda t, review_note="": seq.append(("finalize", review_note)))
    monkeypatch.setattr(importlib.import_module("relay_bridge"), "mark_needs_decision",
                        lambda *a, **k: seq.append("needs_decision"))
    ctrl.advance_review("t1")
    assert seq[0][0] == "finalize" and "cap reached" in seq[0][1]
    assert "needs_decision" in seq


def test_start_review_writes_brief_and_relaunches_reviewer(tmp_path, monkeypatch):
    import importlib
    _quiet(monkeypatch)
    td = _task(tmp_path, monkeypatch, {"phase": "implement", "review_round": 0, "tier": "2",
                                       "title": "Drive", "item": "12", "worktree": ""})
    launched = []
    monkeypatch.setattr(importlib.import_module("relay_spawn"), "relaunch",
                        lambda task, brief, role="implementer", note="": launched.append((brief, role)))
    ctrl.start_review("t1")
    meta = json.loads((td / "meta.json").read_text())
    assert meta["phase"] == "review" and meta["review_round"] == 1
    assert (td / "review-brief.md").exists()
    assert launched == [("review-brief.md", "reviewer")]


def test_finalize_pr_embeds_decision_log_and_review_note(tmp_path, monkeypatch):
    import importlib
    _quiet(monkeypatch)
    td = _task(tmp_path, monkeypatch, {"phase": "implement", "tier": "1", "item": "12",
                                       "branch": "relay/cc-t1", "repo": "o/r", "worktree": "/wt",
                                       "lane": "claude", "title": "Drive"},
               evidence={"summary.md": "did it", "decisions.md": "chose resumable upload"})

    class _R:
        returncode = 0; stderr = ""
    monkeypatch.setattr(ctrl.subprocess, "run", lambda *a, **k: _R())

    class _Board:
        def __init__(self): self.body = None
        def file_pr(self, branch, title, body, tier): self.body = body; return "99"
        def apply_label(self, item, label): pass
    board = _Board()
    monkeypatch.setattr(importlib.import_module("relay_board"), "get_board", lambda repo=None: board)
    monkeypatch.setattr(importlib.import_module("relay_bridge"), "mark_review_pending",
                        lambda *a, **k: None)
    ctrl.finalize_pr("t1", review_note="✅ reviewed by claude-opus-4-8 — approved")
    assert "reviewed by claude-opus-4-8" in board.body
    assert "Decision log" in board.body and "resumable upload" in board.body
    assert "Closes #12" in board.body


def test_resolve_reads_global_policy_file(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    _clear_model_env(monkeypatch)
    gf = tmp_path / "models.yml"
    gf.write_text(
        "models:\n"
        "  defaults:\n"
        "    reviewer:\n"
        "      personal:\n"
        "        preferred:\n"
        "          - provider: anthropic\n"
        "            model: sonnet\n"
        "            effort: low\n")
    monkeypatch.setenv("RELAY_MODELS_FILE", str(gf))
    spec = models.resolve("claude", role="reviewer")     # default would be opus/medium
    assert spec["model"] == "sonnet" and spec["effort"] == "low"
    assert spec["selection_reason"].startswith("global policy")


def test_repo_crew_overrides_global(tmp_path, monkeypatch):
    pytest.importorskip("yaml")
    _clear_model_env(monkeypatch)
    gf = tmp_path / "global.yml"
    gf.write_text(
        "models:\n  defaults:\n    implementer:\n      personal:\n        preferred:\n"
        "          - model: opus\n")
    monkeypatch.setenv("RELAY_MODELS_FILE", str(gf))
    proj = tmp_path / "proj"
    (proj / ".crew").mkdir(parents=True)
    (proj / ".crew" / "models.yml").write_text(
        "models:\n  defaults:\n    implementer:\n      personal:\n        preferred:\n"
        "          - model: haiku\n")
    spec = models.resolve("claude", role="implementer", project=str(proj))
    assert spec["model"] == "haiku"                       # repo override wins over global
    assert spec["selection_reason"].startswith("repo policy")


def test_global_policy_path_respects_env_and_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("RELAY_MODELS_FILE", "/x/y.yml")
    assert str(models._global_policy_path()) == "/x/y.yml"
    monkeypatch.delenv("RELAY_MODELS_FILE", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert models._global_policy_path() == tmp_path / "relay" / "models.yml"


# ------------------------------------------------------- per-issue effort (medium vs high)
def test_effort_from_labels():
    assert models.effort_from_labels(["tier-1", "effort:high", "lane:copilot"]) == "high"
    assert models.effort_from_labels(["effort:bogus"]) is None
    assert models.effort_from_labels(["tier-1"]) is None


def test_resolve_effort_override_wins(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("claude", role="implementer", effort_override="high")
    assert spec["effort"] == "high" and spec["selection_mode"] == "override"
    assert "effort override" in spec["selection_reason"]


def test_resolve_effort_override_ignores_bogus(monkeypatch):
    _clear_model_env(monkeypatch)
    spec = models.resolve("claude", role="implementer", effort_override="turbo")
    assert spec["effort"] == "medium"        # default stands; bogus ignored
