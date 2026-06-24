"""
relay_spawn.py — cross-platform, LANE-AWARE worker spawner + probe + resume.

A worker runs one task in a disposable worktree under a chosen LANE (claude | agy |
codex). Lanes give relay three separate provider quotas — the structural answer to the
single-provider usage ceiling the watchdog exists to handle — and let cheap, isolated
work burn Gemini/agy credits instead of the Claude budget. Routing is by risk:
Tier-2 (sacred) always goes to the craftsmanship lane (claude); cheap isolated work can
go to agy/codex.

Every lane runs its harness NON-INTERACTIVELY to completion, then relay_finish.py writes
the terminal status line — so completion detection never depends on the agent's goodwill.

Capability ladder (chosen at spawn, logged in meta, announced in the `started` notify,
never a silent degrade): wt-tab (Windows Terminal) -> bg-job (PowerShell) -> tmux (Mac/
Linux/NAS). Lanes are fully supported on the tmux path (the NAS/Mac target); the Windows
work profile falls back to the claude lane.
"""
from __future__ import annotations
import json, os, platform, shutil, subprocess
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(os.getenv("DATA_DIR", "data"))
WORKTREES_NAME = os.getenv("RELAY_WORKTREES", ".worktrees")
DEFAULT_LANE = os.getenv("RELAY_LANE", "claude")
PY = os.getenv("RELAY_PYTHON", "python3")
HERE = Path(__file__).resolve().parent
LANES = ("claude", "agy", "copilot", "codex")
LANE_PREFIX = {"claude": "cc", "agy": "ag", "copilot": "co", "codex": "cx"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _harness_cmd(lane: str, brief: Path, mode: str) -> str:
    """Non-interactive, run-to-completion launch string for a lane.
    The worker reads the brief file itself; it holds NO board credentials and is told
    (in the brief) to commit only — the control plane pushes and files the PR."""
    if mode in ("wt-tab", "bg-job"):           # Windows work profile: claude only
        return f'claude --permission-mode acceptEdits -p (Get-Content -Raw "{brief}")'
    if lane == "claude":
        return f'claude -p "$(cat {brief})" --permission-mode acceptEdits'
    if lane == "agy":                          # script -qec: keep agy output under a non-TTY
        return f"script -qec 'agy -p \"$(cat {brief})\"' /dev/null"
    if lane == "copilot":
        return f'copilot --allow-all-tools --autopilot -p "$(cat {brief})"'
    if lane == "codex":
        return f'codex exec --sandbox workspace-write "$(cat {brief})"'
    raise ValueError(f"unknown lane {lane}")


def _detect_mode() -> str:
    if platform.system() == "Windows":
        return "wt-tab" if (shutil.which("wt") and _wt_headless_enabled()) else "bg-job"
    return "tmux"


def _wt_headless_enabled() -> bool:
    base = os.getenv("LOCALAPPDATA", "")
    if not base:
        return False
    for p in Path(base).glob("Packages/Microsoft.WindowsTerminal*/LocalState/settings.json"):
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            if cfg.get("compatibility.allowHeadless") or cfg.get("allowHeadless"):
                return True
        except Exception:
            continue
    return False


def _base_ref(project: str, default: str = "main") -> str:
    """Fresh remote tip if reachable, else local default. Never hard-fail offline."""
    ref = subprocess.run(["git", "-C", project, "symbolic-ref", "--quiet", "--short",
                          "refs/remotes/origin/HEAD"], capture_output=True, text=True)
    base = ref.stdout.strip().split("/")[-1] if ref.returncode == 0 else default
    subprocess.run(["git", "-C", project, "fetch", "--quiet", "origin", base],
                   capture_output=True)
    chk = subprocess.run(["git", "-C", project, "rev-parse", "--verify", "--quiet",
                          f"origin/{base}"], capture_output=True, text=True)
    return f"origin/{base}" if chk.returncode == 0 else "HEAD"


def spawn(task: str, project: str, item: str, tier: str, brief_path: str,
          lane: str, title: str = "", requested: str | None = None,
          explicit: bool = False) -> str:
    """Create the worktree + branch, record meta, launch the lane's harness."""
    taskdir = DATA / task
    taskdir.mkdir(parents=True, exist_ok=True)
    (taskdir / "evidence").mkdir(exist_ok=True)
    (taskdir / "evidence" / "screenshots").mkdir(exist_ok=True)

    src, dst = Path(brief_path), taskdir / "brief.md"
    if src.resolve() != dst.resolve():
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    proj = Path(project).resolve()
    wt_abs = proj.parent / WORKTREES_NAME / task
    branch = f"relay/{LANE_PREFIX.get(lane, 'cc')}-{task}"
    base = _base_ref(str(proj))
    subprocess.run(["git", "-C", str(proj), "worktree", "add", "-f",
                    str(wt_abs), "-b", branch, base], capture_output=True)

    mode = _detect_mode()
    (taskdir / "meta.json").write_text(json.dumps({
        "item": item, "tier": tier, "lane": lane, "mode": mode,
        "project": str(proj), "worktree": str(wt_abs), "branch": branch,
        "title": title, "requested": requested or lane, "explicit": explicit,
        "tried_lanes": [lane],
    }))
    (taskdir / "status.md").write_text(f"PROGRESS {_now()}\n")
    (taskdir / "active").touch()
    _launch(task, wt_abs, taskdir, tier, mode, lane)
    return mode


def resume(task: str) -> None:
    taskdir = DATA / task
    meta = json.loads((taskdir / "meta.json").read_text()) if (taskdir / "meta.json").exists() else {}
    wt = Path(meta.get("worktree", str(DATA.parent / WORKTREES_NAME / task)))
    (taskdir / "status.md").open("a").write(f"PROGRESS {_now()}  (resumed)\n")
    (taskdir / "active").touch()
    _launch(task, wt, taskdir, meta.get("tier", "1"), meta.get("mode", _detect_mode()),
            meta.get("lane", DEFAULT_LANE))


def _launch(task: str, wt: Path, taskdir: Path, tier: str, mode: str, lane: str) -> None:
    brief = taskdir / "brief.md"
    log = taskdir / "worker.log"
    harness = _harness_cmd(lane, brief, mode)
    color = "#D13438" if tier == "2" else "#0F7B0F"          # red Tier-2, green Tier-1
    # finisher classifies the exit (DONE/RATE_LIMITED/ERROR) — off the agent's goodwill.
    if mode == "wt-tab":
        fin = f"{PY} {HERE / 'relay_finish.py'} {task} $LASTEXITCODE"
        subprocess.run(["wt", "new-tab", "-t", f"relay-{task}", "-c", color,
                        "powershell.exe", "-Command",
                        f"Set-Location '{wt}'; {harness} *>&1 | Tee-Object -FilePath '{log}'; {fin}"])
    elif mode == "bg-job":
        fin = f"{PY} {HERE / 'relay_finish.py'} {task} $LASTEXITCODE"
        subprocess.run(["powershell.exe", "-Command",
                        f"Start-Job -Name relay-{task} -ScriptBlock {{ Set-Location '{wt}'; "
                        f"{harness} *>&1 | Tee-Object -FilePath '{log}'; {fin} }}"])
    else:  # tmux (Mac/Linux/NAS) — full lane support
        fin = f"{PY} '{HERE / 'relay_finish.py'}' {task} $rc"
        cmd = f"( {harness} ) 2>&1 | tee '{log}'; rc=${{PIPESTATUS[0]}}; {fin}"
        subprocess.run(["tmux", "new-session", "-d", "-s", "relay"], capture_output=True)
        subprocess.run(["tmux", "new-window", "-t", "relay", "-n", task, "-c", str(wt)])
        subprocess.run(["tmux", "send-keys", "-t", f"relay:{task}", cmd, "C-m"])


def probe() -> int:
    """0 ok / 1 still rate-limited / 2 genuine non-limit error. Cheap one-shot."""
    h = os.getenv("RELAY_PROBE_HARNESS", "claude")
    r = subprocess.run([h, "--print", "reply with: ok"], capture_output=True, text=True)
    if r.returncode == 0:
        return 0
    blob = (r.stdout + r.stderr).lower()
    if any(s in blob for s in ("rate limit", "ratelimit", "quota", "usage limit",
                               "429", "too many requests", "overloaded")):
        return 1
    return 2
