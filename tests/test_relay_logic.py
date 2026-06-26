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
