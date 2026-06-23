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
from relay_board import Ticket  # noqa: E402


# ------------------------------------------------------- lane routing
def test_lane_override_wins():
    assert spawn.pick_lane(["lane:codex"], "1", "agy") == "agy"

def test_lane_from_label():
    assert spawn.pick_lane(["lane:codex", "phase:4"], "1") == "codex"

def test_tier2_forces_claude_even_with_cheap_label():
    # sacred work never goes to a cheap lane, even if labeled
    assert spawn.pick_lane(["lane:agy", "tier-2"], "2") == "claude"

def test_lane_default_is_claude():
    assert spawn.pick_lane(["phase:2"], "1") == "claude"


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
