"""
relay_cli.py — command dispatcher. The entrypoints (./relay, .\relay.ps1) call this.

Subcommands:
    watch              run the control-plane supervision + auto-dispatch loop (the daemon)
    pull               list ready tickets from the board (read-only)
    dispatch <id>      pull a ticket, route a lane, apply agent-wip, spawn a worker
                       [--project <path>] [--lane claude|agy|codex]
    status             show active workers and their states
    note "<text>"      append an owner memory entry
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

sys.path.insert(0, str(Path(__file__).parent))

import relay_control as ctrl
import relay_spawn as spawn
import relay_lanes as lanes
from relay_board import get_board


def cmd_watch(_argv: list[str]) -> int:
    ctrl.run_loop(spawn.probe, spawn.resume)
    return 0


def cmd_pull(argv: list[str]) -> int:
    avail = lanes.available_lanes()
    rows = []
    for repo, _project in ctrl.projects():
        for t in get_board(repo).pull_ready():
            pref, explicit = lanes.lane_preference(t.labels)
            lane, reason = lanes.resolve_lane(pref, explicit, t.tier, avail)
            rows.append({"repo": repo, "id": t.id, "tier": t.tier, "title": t.title,
                         "lane": lane, "hold": None if lane else reason})
    if "--json" in argv:
        print(json.dumps(rows)); return 0
    for r in rows:
        tag = r["lane"] or f"HOLD ({r['hold']})"
        print(f"[{r['repo']}#{r['id']}] tier-{r['tier']}  lane={tag}  {r['title']}")
    return 0


def cmd_board(argv: list[str]) -> int:
    """The kanban feed: Ready (agent-ready) · Working/Waiting (active workers) · Review (PRs)."""
    avail = lanes.available_lanes()
    ready, review = [], []
    for repo, _project in ctrl.projects():
        b = get_board(repo)
        try:
            for t in b.pull_ready():
                pref, explicit = lanes.lane_preference(t.labels)
                lane, reason = lanes.resolve_lane(pref, explicit, t.tier, avail)
                ready.append({"repo": repo, "id": t.id, "tier": t.tier, "title": t.title,
                              "lane": lane, "hold": None if lane else reason})
        except Exception:
            pass
        try:
            review += getattr(b, "pull_review", lambda: [])()
        except Exception:
            pass
    data = {"ready": ready, "active": _workers(), "review": review}
    if "--json" in argv:
        print(json.dumps(data)); return 0
    print(f"ready:{len(ready)}  active:{len(data['active'])}  review:{len(review)}")
    return 0


def cmd_lanes(argv: list[str]) -> int:
    data = {"configured": lanes.configured_lanes(),
            "available": lanes.available_lanes(refresh="--refresh" in argv),
            "strict": lanes.strict()}
    if "--json" in argv:
        print(json.dumps(data)); return 0
    print(f"configured (RELAY_LANES): {', '.join(data['configured'])}")
    print(f"available (auth-checked): {', '.join(data['available']) or '(none)'}")
    print(f"strict (work governance): {data['strict']}")
    return 0


def _opt(argv: list[str], flag: str, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def cmd_dispatch(argv: list[str]) -> int:
    if not argv:
        print("usage: relay dispatch <ticket-id> [--repo owner/name] [--project <path>] "
              "[--lane claude|agy|copilot|codex]", file=sys.stderr)
        return 2
    ticket_id = argv[0]
    repo_opt, project_opt, lane = _opt(argv, "--repo"), _opt(argv, "--project"), _opt(argv, "--lane")
    # which (repo, project) to search: an explicit --repo, else the whole registry
    if repo_opt:
        reg = dict(ctrl.projects())
        candidates = [(repo_opt, project_opt or reg.get(repo_opt, "."))]
    else:
        candidates = ctrl.projects() or [("", project_opt or ".")]
    for repo, project in candidates:
        ticket = next((t for t in get_board(repo).pull_ready() if t.id == ticket_id), None)
        if ticket is None:
            continue
        task = ctrl.dispatch_ticket(ticket, project_opt or project, repo, lane_override=lane)
        if task is None:
            print(f"{repo}#{ticket_id} HELD — no lane could be resolved (see `relay lanes`)",
                  file=sys.stderr)
            return 1
        print(f"dispatched {task}")
        return 0
    print(f"ticket {ticket_id} not ready in any configured repo", file=sys.stderr)
    return 1


def _read_log(task: str) -> str:
    p = ctrl.CFG.data_dir / task / "worker.log"
    try:
        return p.read_text(errors="ignore") if p.exists() else ""
    except Exception:
        return ""


def _now_line(task: str) -> str:
    """The worker's last meaningful action — the at-a-glance 'what's it doing' line."""
    clean = _ANSI.sub("", _read_log(task))
    lines = [l.strip() for l in clean.splitlines() if l.strip()]
    for l in reversed(lines):                       # prefer a tool-call bullet
        if l[:1] in ("●", "•", "⏺"):
            return l[:90]
    return lines[-1][:90] if lines else ""


def _elapsed(task: str) -> str:
    txt = ((ctrl.CFG.data_dir / task / "status.md").read_text(errors="ignore")
           if (ctrl.CFG.data_dir / task / "status.md").exists() else "")
    lines = [l for l in txt.splitlines() if l.strip()]
    if not lines:
        return ""
    try:
        start = datetime.fromisoformat(lines[0].split()[1])
        secs = int((datetime.now(timezone.utc) - start).total_seconds())
        return f"{secs // 60}m{secs % 60:02d}s"
    except Exception:
        return ""


def _meta(task: str) -> dict:
    mp = ctrl.CFG.data_dir / task / "meta.json"
    try:
        return json.loads(mp.read_text()) if mp.exists() else {}
    except Exception:
        return {}


def _workers() -> list[dict]:
    """Live worker rows — the machine-readable feed any UI (VS Code ext, web) consumes."""
    dd = ctrl.CFG.data_dir
    rows = []
    if not dd.exists():
        return rows
    for d in sorted(dd.iterdir()):
        if not (d / "active").exists():
            continue
        state, line = ctrl.stop_reason(d.name)
        meta = _meta(d.name)
        rows.append({"task": d.name, "repo": meta.get("repo", ""), "issue": meta.get("item", ""),
                     "lane": meta.get("lane", ""), "tier": meta.get("tier", ""),
                     "state": state.value, "line": line, "branch": meta.get("branch", ""),
                     "now": _now_line(d.name)})
    return rows


def cmd_peek(argv: list[str]) -> int:
    """Live worker transcript + facts (the click-to-watch feed). Keeps ANSI so xterm renders it."""
    if not argv:
        print("usage: relay peek <task> [--json]", file=sys.stderr); return 2
    task = argv[0]
    meta = _meta(task)
    state, _line = ctrl.stop_reason(task)
    wt = meta.get("worktree", "")
    files = []
    if wt and Path(wt).exists():
        out = subprocess.run(["git", "-C", wt, "status", "--porcelain"],
                             capture_output=True, text=True).stdout
        files = [l[3:] for l in out.splitlines() if l.strip()][:60]
    tail = _read_log(task)[-24000:]                 # last ~24k chars, ANSI intact
    if len(tail.strip()) < 20 and files:
        # Buffered worker (e.g. `claude -p` piped) writes nothing until exit; the streamed
        # log is the real fix. Until it flushes, show the live worktree changes so the peek
        # still reflects what the agent is doing right now.
        tail = ("\x1b[33m⟳ output is buffered — this run streams only when it finishes.\x1b[0m\r\n"
                "\x1b[2mLive file changes in the worktree:\x1b[0m\r\n\r\n  "
                + "\r\n  ".join(files))
    data = {"task": task, "lane": meta.get("lane", ""), "state": state.value,
            "branch": meta.get("branch", ""), "elapsed": _elapsed(task),
            "files": files, "now": _now_line(task), "log": tail}
    if "--json" in argv:
        print(json.dumps(data)); return 0
    print(f"{task} · lane {data['lane']} · {data['state']} · {data['elapsed']} · "
          f"{len(files)} files")
    print(_ANSI.sub("", tail)[-6000:])
    return 0


def cmd_diff(argv: list[str]) -> int:
    """What the worker has changed so far — the worktree's unified diff (committed + working)."""
    if not argv:
        print("usage: relay diff <task>", file=sys.stderr); return 2
    wt = _meta(argv[0]).get("worktree", "")
    if not wt or not Path(wt).exists():
        print("(no worktree for this task)", file=sys.stderr); return 1
    base = subprocess.run(["git", "-C", wt, "symbolic-ref", "--quiet", "--short",
                           "refs/remotes/origin/HEAD"], capture_output=True, text=True).stdout.strip()
    base = base.split("/")[-1] if base else "main"
    committed = subprocess.run(["git", "-C", wt, "diff", f"origin/{base}...HEAD"],
                               capture_output=True, text=True).stdout
    working = subprocess.run(["git", "-C", wt, "diff"], capture_output=True, text=True).stdout
    sys.stdout.write(committed + working)
    return 0


def cmd_status(argv: list[str]) -> int:
    workers = _workers()
    if "--json" in argv:
        print(json.dumps(workers)); return 0
    if not workers:
        print("(no active workers)"); return 0
    for w in workers:
        repo = (w["repo"] or "").split("/")[-1] or "-"
        print(f"{w['task']:22} {repo:16} {w['lane'] or '-':8} {w['state']:14} {w['line']}")
    return 0


def cmd_note(argv: list[str]) -> int:
    if not argv:
        print('usage: relay note "<text>" [--project <path>] [--next "<text>"] [--blocked "<text>"]',
              file=sys.stderr)
        return 2
    ctrl.memory_append(did=argv[0], nxt=_opt(argv, "--next", ""),
                       blocked=_opt(argv, "--blocked", "none"),
                       project_dir=_opt(argv, "--project"), author="owner")
    print("noted.")
    return 0


def cmd_kill(argv: list[str]) -> int:
    if not argv:
        print("usage: relay kill <task>", file=sys.stderr); return 2
    task = argv[0]
    subprocess.run(["tmux", "kill-window", "-t", f"relay:{task}"], capture_output=True)
    td = ctrl.CFG.data_dir / task
    if (td / "status.md").parent.exists():
        with (td / "status.md").open("a", encoding="utf-8") as f:
            f.write(f"ERROR killed-by-owner {datetime.now(timezone.utc).isoformat()}\n")
    ctrl._clear_active(task)
    print(f"killed {task}")
    return 0


def cmd_pause(_argv: list[str]) -> int:
    (ctrl.CFG.data_dir / ".paused").touch()
    print("auto-dispatch PAUSED (running workers continue; no new ones start)")
    return 0


def cmd_resume(_argv: list[str]) -> int:
    (ctrl.CFG.data_dir / ".paused").unlink(missing_ok=True)
    print("auto-dispatch RESUMED")
    return 0


COMMANDS = {"watch": cmd_watch, "pull": cmd_pull, "dispatch": cmd_dispatch,
            "status": cmd_status, "board": cmd_board, "peek": cmd_peek, "diff": cmd_diff,
            "note": cmd_note, "lanes": cmd_lanes,
            "kill": cmd_kill, "pause": cmd_pause, "resume": cmd_resume}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: relay <{'|'.join(COMMANDS)}> [args]", file=sys.stderr)
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
