"""Unit tests for relay's pure logic — lane routing, the evidence gate, the contract gate,
and worker-exit classification. The safety-critical bits (evidence gate, exit classification)
get the most coverage. Run: cd relay && python3 -m pytest -q
"""
import importlib.util
import sys
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
