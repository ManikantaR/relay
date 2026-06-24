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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import relay_control as ctrl
import relay_spawn as spawn
import relay_lanes as lanes
from relay_board import get_board


def cmd_watch(_argv: list[str]) -> int:
    ctrl.run_loop(spawn.probe, spawn.resume)
    return 0


def cmd_pull(_argv: list[str]) -> int:
    avail = lanes.available_lanes()
    for t in get_board().pull_ready():
        pref, explicit = lanes.lane_preference(t.labels)
        lane, reason = lanes.resolve_lane(pref, explicit, t.tier, avail)
        tag = lane or f"HOLD ({reason})"
        print(f"[{t.id}] tier-{t.tier}  lane={tag}  {t.title}")
    return 0


def cmd_lanes(argv: list[str]) -> int:
    refresh = "--refresh" in argv
    print(f"configured (RELAY_LANES): {', '.join(lanes.configured_lanes())}")
    print(f"available (auth-checked): {', '.join(lanes.available_lanes(refresh=refresh)) or '(none)'}")
    print(f"strict (work governance): {lanes.strict()}")
    return 0


def _opt(argv: list[str], flag: str, default=None):
    return argv[argv.index(flag) + 1] if flag in argv else default


def cmd_dispatch(argv: list[str]) -> int:
    if not argv:
        print("usage: relay dispatch <ticket-id> [--project <path>] [--lane claude|agy|codex]",
              file=sys.stderr)
        return 2
    ticket_id = argv[0]
    project = _opt(argv, "--project", ".")
    lane = _opt(argv, "--lane")
    ticket = next((t for t in get_board().pull_ready() if t.id == ticket_id), None)
    if ticket is None:
        print(f"ticket {ticket_id} not ready (must be agent-ready, not agent-wip)", file=sys.stderr)
        return 1
    task = ctrl.dispatch_ticket(ticket, project, lane_override=lane)
    if task is None:
        print(f"ticket {ticket_id} HELD — no lane could be resolved (see notify / `relay lanes`)",
              file=sys.stderr)
        return 1
    print(f"dispatched {task}")
    return 0


def cmd_status(_argv: list[str]) -> int:
    dd = ctrl.CFG.data_dir
    if not dd.exists():
        print("(no data dir)"); return 0
    any_active = False
    for d in sorted(dd.iterdir()):
        if (d / "active").exists():
            any_active = True
            state, line = ctrl.stop_reason(d.name)
            print(f"{d.name:16} {state.value:14} {line}")
    if not any_active:
        print("(no active workers)")
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


COMMANDS = {"watch": cmd_watch, "pull": cmd_pull, "dispatch": cmd_dispatch,
            "status": cmd_status, "note": cmd_note, "lanes": cmd_lanes}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: relay <{'|'.join(COMMANDS)}> [args]", file=sys.stderr)
        return 2
    return COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
