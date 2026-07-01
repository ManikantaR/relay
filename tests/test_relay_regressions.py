"""Regression tests that must stay outside the protected test bundle."""
import importlib
import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

PY = Path(__file__).resolve().parents[1] / "py"
sys.path.insert(0, str(PY))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, PY / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ctrl = _load("relay_control")
cli = _load("relay_cli")


def test_advance_review_unknown_caps_to_needs_decision_and_clears_active(tmp_path, monkeypatch):
    monkeypatch.setattr(ctrl.CFG, "data_dir", tmp_path)
    td = tmp_path / "t1"
    (td / "evidence" / "screenshots").mkdir(parents=True)
    (td / "meta.json").write_text('{"phase":"review","review_round":3,"tier":"1","worktree":"","max_review_rounds":3}')
    (td / "status.md").write_text("DONE x\n")
    (td / "brief.md").write_text("# brief\n")
    (td / "active").write_text("")
    monkeypatch.setattr(ctrl, "notify", lambda *a, **k: None)
    monkeypatch.setattr(ctrl, "_notify_once", lambda *a, **k: None)
    monkeypatch.setattr(ctrl, "memory_append", lambda *a, **k: None)
    calls = []
    monkeypatch.setattr(ctrl, "finalize_pr", lambda *a, **k: calls.append("finalize"))
    monkeypatch.setattr(importlib.import_module("relay_bridge"), "mark_needs_decision",
                        lambda *a, **k: calls.append("needs_decision"))
    ctrl.advance_review("t1")
    assert calls == ["needs_decision"]
    assert not (td / "active").exists()


def test_cmd_repo_add_skips_board_value_when_path_is_omitted(monkeypatch):
    import relay_repos
    monkeypatch.setattr(relay_repos, "registry_path", lambda: Path("/tmp/repos.json"))
    seen = {}

    def fake_add(name, path, board):
        seen.update({"name": name, "path": path, "board": board})
        return [{"name": name, "path": path or ".", "board": board}]

    monkeypatch.setattr(relay_repos, "add", fake_add)
    out = io.StringIO()
    with redirect_stdout(out):
        assert cli.cmd_repo(["add", "owner/repo", "--board", "tfs"]) == 0
    assert seen == {"name": "owner/repo", "path": None, "board": "tfs"}
