"""
relay_control.py — Relay orchestration control plane (cross-platform, stdlib-only).

One brain for both machines, and the TRUSTED half of the trust boundary: only this plane
(never a worker) holds board credentials, pushes branches, files PRs, and applies labels.
A worker commits locally in its worktree and stops; the plane does the rest. That is what
makes "an agent's approval is input, never permission" structural rather than polite.

It owns: zero-token auto-dispatch (pull agent-ready -> contract-gate -> spawn, capped),
worker lifecycle (rate-limited vs hung vs done), evidence-gated close-out, notifications.
No LLM runs here — tokens are spent only inside workers doing real code.
"""
from __future__ import annotations
import json, logging, os, subprocess, time
from pathlib import Path
from datetime import datetime, timezone
from enum import Enum
from urllib import request as urlrequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("relay")


class State(str, Enum):
    PROGRESS = "PROGRESS"; DONE = "DONE"; RATE_LIMITED = "RATE_LIMITED"
    ERROR = "ERROR"; HELD = "HELD"; MISSING = "MISSING"


class Config:
    """All knobs from env; secrets read from the gitignored data/captain.<profile>.md."""
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DATA_DIR", "data"))
        self.profile = os.getenv("RELAY_PROFILE", "personal")   # personal | work
        self.probe_interval = int(os.getenv("RELAY_PROBE_INTERVAL", "300"))
        self.hang_threshold = int(os.getenv("RELAY_HANG_THRESHOLD", "900"))
        self.poll = int(os.getenv("RELAY_POLL", "15"))
        self.max_workers = int(os.getenv("RELAY_MAX_WORKERS", "2"))
        self.autodispatch = os.getenv("RELAY_AUTODISPATCH", "") not in ("", "0", "false")
        self.project = os.getenv("RELAY_PROJECT", "")
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat = os.getenv("TELEGRAM_CHAT_ID", "")
        self.teams_webhook = os.getenv("TEAMS_WEBHOOK_URL", "")
        self.data_dir.mkdir(parents=True, exist_ok=True)


CFG = Config()

# --- notifications: channel by profile; waiting-on-limit and hung MUST read differently ---

_FRAMES = {
    "started":           "🟢 started · {task} · {detail}",
    "tier1-ready":       "✅ PR ready (skim when convenient) · {task}\n{detail}",
    "tier2-held":        "🔒 NEEDS YOUR EYES — no rush, review at a desk · {task}\n{detail}",
    "waiting-on-limit":  "⏳ idle — rate-limited, probing. NOT stuck. · {task}",
    "resumed":           "▶️ resumed — window reopened · {task}",
    "lane-switch":       "🔀 failed over {detail} · {task}",
    "hung":              "🛑 STUCK — no progress, needs you · {task}\n{detail}",
    "crashed-respawned": "🔁 crashed → respawned from worktree · {task}",
    "merged":            "🎉 merged · {task}\n{detail}",
    "needs-decision":    "❓ blocked — your call · {task}\n{detail}",
}


def notify(event: str, task: str, detail: str = "") -> None:
    msg = _FRAMES.get(event, "ℹ️ {task} · {detail}").format(task=task, detail=detail)
    try:
        if CFG.profile == "work":
            if not CFG.teams_webhook:
                log.warning("no TEAMS_WEBHOOK_URL; skipping notify: %s", msg); return
            body = json.dumps({"text": msg}).encode()
            req = urlrequest.Request(CFG.teams_webhook, data=body,
                                     headers={"Content-Type": "application/json"})
            urlrequest.urlopen(req, timeout=10)
        else:
            if not (CFG.telegram_token and CFG.telegram_chat):
                log.warning("no TELEGRAM_* creds; skipping notify: %s", msg); return
            from urllib.parse import urlencode
            url = (f"https://api.telegram.org/bot{CFG.telegram_token}/sendMessage?"
                   + urlencode({"chat_id": CFG.telegram_chat, "text": msg}))
            urlrequest.urlopen(url, timeout=10)
    except Exception as e:                      # notifications must never crash the loop
        log.warning("notify failed (%s): %s", event, e)


def _notify_once(event: str, task: str, detail: str = "") -> None:
    """Escalations (hung/error) fire once per task, not every poll cycle."""
    marker = CFG.data_dir / task / f".notified-{event}"
    if marker.exists():
        return
    marker.touch()
    notify(event, task, detail)


# --- worker state read from disk (the IPC contract every spawner backend honors) ---

def _status_path(task: str) -> Path:
    return CFG.data_dir / task / "status.md"


def stop_reason(task: str) -> tuple[State, str]:
    p = _status_path(task)
    if not p.exists():
        return State.MISSING, ""
    text = p.read_text(encoding="utf-8").strip()
    last = text.splitlines()[-1] if text else ""
    head = last.split()[0] if last else "MISSING"
    try:
        return State(head), last
    except ValueError:
        return State.PROGRESS, last


def _log_age(task: str) -> int:
    """Seconds since the worker.log last changed — liveness without trusting the agent."""
    p = CFG.data_dir / task / "worker.log"
    if not p.exists():
        return 0
    return int(time.time() - p.stat().st_mtime)


def _clear_active(task: str) -> None:
    (CFG.data_dir / task / "active").unlink(missing_ok=True)


# --- evidence gate (ported from orch): no proof, no PR -----------------------------------

def evidence_ok(task: str) -> tuple[bool, list[str]]:
    """Passes iff evidence/summary.md exists AND (pytest.txt OR a screenshot)."""
    d = CFG.data_dir / task / "evidence"
    have: list[str] = []
    summary = (d / "summary.md").exists()
    pytest_out = (d / "pytest.txt").exists()
    shots = list((d / "screenshots").glob("*.png")) if (d / "screenshots").is_dir() else []
    if summary:
        have.append("summary.md")
    if pytest_out:
        have.append("pytest.txt")
    if shots:
        have.append(f"screenshots/*.png ({len(shots)})")
    return (summary and (pytest_out or bool(shots))), have


# --- the trusted close-out: evidence -> push -> PR -> tier gate ---------------------------

def close_out(task: str) -> None:
    """Worker finished. Gate on evidence, then the TRUSTED plane pushes + files the PR.
    The worker never pushed; this is where the leash becomes structural."""
    from relay_board import get_board
    taskdir = CFG.data_dir / task
    meta = json.loads((taskdir / "meta.json").read_text()) if (taskdir / "meta.json").exists() else {}
    tier, item, branch = meta.get("tier", "1"), meta.get("item", ""), meta.get("branch", "")
    project, worktree = meta.get("project", "."), meta.get("worktree", "")
    repo = meta.get("repo", "")
    title = meta.get("title", "") or f"relay {task}"

    ok, have = evidence_ok(task)
    if not ok:
        with _status_path(task).open("a") as f:
            f.write(f"HELD {datetime.now(timezone.utc).isoformat()}\n")
        _notify_once("needs-decision", task,
                     f"held — no evidence bundle (have: {', '.join(have) or 'none'}). No PR filed.")
        memory_append(did=f"{task} finished but evidence gate FAILED — held, no PR",
                      nxt="Owner: add summary.md + pytest/screenshot, or re-dispatch.", author="agent")
        _clear_active(task)
        return

    # trusted plane pushes the worker's local branch (worker holds no remote creds)
    push = subprocess.run(["git", "-C", worktree, "push", "-u", "origin", branch],
                          capture_output=True, text=True)
    if push.returncode != 0:
        _notify_once("needs-decision", task, f"push failed: {push.stderr.strip()[:200]}")
        _clear_active(task)
        return

    summary = (taskdir / "evidence" / "summary.md")
    body = (summary.read_text(encoding="utf-8") if summary.exists() else "")
    body += f"\n\nCloses #{item}\n\n_Lane {meta.get('lane','?')} · evidence-gated by relay · human merges._\n"
    try:
        pr = get_board(repo).file_pr(branch, f"{title} (#{item})", body, tier)
        get_board(repo).apply_label(item, "agent-review")
    except Exception as e:
        _notify_once("needs-decision", task, f"PR/label step failed: {e}")
        _clear_active(task)
        return

    if tier == "2":
        notify("tier2-held", task, f"PR {pr} — read every line at a desk, no rush")
    else:
        notify("tier1-ready", task, f"PR {pr} — skim when convenient")
    memory_append(did=f"{task} done -> PR {pr} (tier-{tier}, lane {meta.get('lane','?')})",
                  nxt=("Owner: read every line, then merge." if tier == "2"
                       else "Owner: skim + merge."), author="agent")
    _clear_active(task)


# --- lane failover: pick the next available lane this task hasn't tried (AGENTS.md §12) ---

def _failover_lane(task: str) -> dict | None:
    """On rate-limit, switch the task to the next available untried lane and update meta.
    Returns {'from','to'} on a switch, or None when no fresh lane exists (Tier-2, or all capped
    -> the caller idle-waits instead)."""
    import relay_lanes as lanes
    metap = CFG.data_dir / task / "meta.json"
    if not metap.exists():
        return None
    meta = json.loads(metap.read_text())
    tried = meta.get("tried_lanes", [meta.get("lane")])
    nxt, _reason = lanes.resolve_lane(
        meta.get("requested", meta.get("lane")), meta.get("explicit", False),
        meta.get("tier", "1"), lanes.available_lanes(), tried=tried)
    if not nxt or nxt in tried:
        return None
    frm = meta.get("lane")
    meta["lane"] = nxt
    meta["tried_lanes"] = tried + [nxt]
    metap.write_text(json.dumps(meta))
    return {"from": frm, "to": nxt}


# --- the watchdog: rate-limited (probe&resume) | hung (escalate) | done (close) ----------

def supervise(task: str, probe, resume) -> None:
    state, line = stop_reason(task)
    if state in (State.DONE,):
        close_out(task); return
    if state is State.HELD:
        _clear_active(task); return
    if state is State.RATE_LIMITED:
        # Failover FIRST: resume on the next available lane (AGENTS.md §12). Only when every
        # lane is capped — or Tier-2 (which never downgrades) — do we idle-probe-and-wait.
        switch = _failover_lane(task)
        if switch:
            notify("lane-switch", task, f"{switch['from']}→{switch['to']} (rate limit)")
            resume(task)                          # resume reads the updated meta.lane
            return
        notify("waiting-on-limit", task, f"all lanes capped; probing every {CFG.probe_interval}s")
        while True:
            rc = probe()
            if rc == 0:
                resume(task); notify("resumed", task, "window reopened"); return
            if rc == 2:
                _notify_once("needs-decision", task, "probe hit a non-limit error"); return
            time.sleep(CFG.probe_interval)       # rc == 1: still limited
    if state is State.ERROR:
        _notify_once("needs-decision", task, line[len("ERROR"):].strip() or "worker errored")
        _clear_active(task); return
    if state is State.PROGRESS:
        if _log_age(task) > CFG.hang_threshold:   # liveness from log mtime, not trust
            _notify_once("hung", task, f"no log activity for {_log_age(task)}s")
        return
    if state is State.MISSING:
        resume(task); notify("crashed-respawned", task, "reconciled from worktree")


# --- zero-token auto-dispatch: pull agent-ready -> contract-gate -> spawn (capped) --------

def _contract_ok(ticket) -> bool:
    """A dispatchable contract: an explicit tier label + a non-trivial spec body.
    (Stop-condition/scope-fence quality is the owner's job when authoring agent-ready.)"""
    has_tier = any(l in ("tier-1", "tier-2") for l in getattr(ticket, "labels", []))
    return has_tier and len((ticket.body or "").strip()) > 30


def _active_count() -> int:
    if not CFG.data_dir.exists():
        return 0
    return sum(1 for d in CFG.data_dir.iterdir() if (d / "active").exists())


def _repo_slug(repo: str) -> str:
    return repo.split("/")[-1].lower() if repo else "repo"


def task_id(repo: str, issue) -> str:
    """Repo-qualified task id — the same issue number in two repos never collides."""
    return f"{_repo_slug(repo)}-{issue}"


def projects() -> list[tuple[str, str]]:
    """The (board-repo, project-path) pairs the auto-dispatcher serves. RELAY_PROJECTS is a
    comma list of `repo=path`; falls back to the single GITHUB_REPO + RELAY_PROJECT."""
    raw = os.getenv("RELAY_PROJECTS", "").strip()
    if raw:
        pairs = []
        for pair in raw.split(","):
            if "=" in pair:
                repo, path = pair.split("=", 1)
                pairs.append((repo.strip(), path.strip()))
        return pairs
    repo = os.getenv("GITHUB_REPO", "")
    return [(repo, CFG.project or ".")] if repo else []


def auto_dispatch() -> None:
    """Opt-in (RELAY_AUTODISPATCH). Pure Python — no LLM, no idle tokens. Serves EVERY repo in
    the registry, round-robin, under one global concurrency cap."""
    if not CFG.autodispatch:
        return
    from relay_board import get_board
    active = _active_count()
    for repo, project in projects():
        if active >= CFG.max_workers:
            break
        try:
            tickets = get_board(repo).pull_ready()
        except Exception as e:
            log.warning("pull from %s failed: %s", repo or "(default)", e)
            continue
        for t in tickets:
            if active >= CFG.max_workers:
                break
            if (CFG.data_dir / task_id(repo, t.id)).exists():
                continue
            if not _contract_ok(t):
                log.info("skip %s#%s: incomplete contract (needs tier label + spec)", repo, t.id)
                continue
            if dispatch_ticket(t, project, repo):   # held tickets return None — don't count them
                active += 1


# --- dispatch one ticket (shared by manual `relay dispatch` and auto_dispatch) ------------

_BRIEF = """# {title}

You are an autonomous worker on the **{lane}** lane, in a disposable git worktree. Implement
this one item to completion, unattended, then stop. The owner reviews and merges — never you.

## Item #{item} (tier-{tier})

{body}

## Hard rails — breaking any of these fails the task
1. **Commit only. Never push, never run `gh`, never open or merge a PR.** The trusted control
   plane pushes your branch and files the PR after gating your evidence. You do neither.
2. Work only inside this worktree; never touch the default branch or sibling worktrees.
3. No real secrets/PII — fictional data only. Stub all external services (no network in tests).
4. Go green by fixing code, never by deleting/skipping/`xfail`-ing tests or `--no-verify`.
   {tier2}
5. If stuck after ~3 tries at one root cause, stop and say so in evidence/summary.md.

## Liveness
Every few steps, append a line `PROGRESS <iso8601>` to **{taskdir}/status.md** so the
watchdog can tell active work from a hang.

## Evidence mandate — the PR is REFUSED without it
Write to **{evidence}/**:
- `summary.md` (required): what changed, why, and how each acceptance criterion is met.
- `pytest.txt` (required if backend touched): captured `pytest -q` output.
- `screenshots/*.png` (required if UI touched): Playwright shots of the feature working.
The control plane will not file a PR unless `summary.md` + (`pytest.txt` or a screenshot) exist.

## Done
Tests pass, evidence complete, work committed on your branch. End `summary.md` with
`done: ready for review` (or `blocked: <reason>`). Do not push — the plane takes it from here.
"""


def dispatch_ticket(ticket, project: str, repo: str = "",
                    lane_override: str | None = None) -> str | None:
    import relay_spawn as spawn
    import relay_lanes as lanes
    from relay_board import get_board
    task = task_id(repo, ticket.id)

    preferred, explicit = lanes.lane_preference(getattr(ticket, "labels", []), lane_override)
    lane, reason = lanes.resolve_lane(preferred, explicit, ticket.tier, lanes.available_lanes())
    if lane is None:
        # HOLD: work strict mismatch, or Tier-2 needs claude and claude is unavailable here.
        _notify_once("needs-decision", task, f"held — lane unresolved ({reason})")
        memory_append(did=f"{task} NOT dispatched — lane hold ({reason})",
                      nxt="Owner: enable/auth a lane, relabel, or make claude available.",
                      project_dir=project, author="agent")
        return None

    taskdir = CFG.data_dir / task
    taskdir.mkdir(parents=True, exist_ok=True)
    evidence = (taskdir / "evidence").resolve()
    tier2 = ("This item touches Tier-2 (sacred) paths — extra care; the owner reads every line."
             if ticket.tier == "2" else "")
    brief = taskdir / "brief.md"
    brief.write_text(_BRIEF.format(
        title=ticket.title, item=ticket.id, tier=ticket.tier, body=ticket.body or "(no spec)",
        lane=lane, taskdir=taskdir.resolve(), evidence=evidence, tier2=tier2), encoding="utf-8")

    get_board(repo).apply_label(ticket.id, "agent-wip")     # control-plane mutates the board
    mode = spawn.spawn(task, project, ticket.id, ticket.tier, str(brief), lane, ticket.title,
                       requested=preferred, explicit=explicit, repo=repo)
    tag = "" if reason == "preferred" else f" [{reason}]"        # never silent: announce subs
    notify("started", task, f"tier-{ticket.tier} · lane {lane} · {mode}{tag}")
    memory_append(did=f"Dispatched {task} ({ticket.title}) tier-{ticket.tier} lane={lane}{tag}",
                  nxt="Worker implementing; await evidence-gated PR."
                      + (" Tier-2 will HOLD." if ticket.tier == "2" else ""),
                  project_dir=project, author="agent")
    return task


# --- memory: dated handoff entries, newest on top ---

def memory_append(did: str, nxt: str = "", blocked: str = "none",
                  project_dir: str | None = None, author: str = "agent") -> None:
    machine = "work" if CFG.profile == "work" else "personal"
    stamp = datetime.now(timezone.utc).date().isoformat()
    entry = (f"## {stamp} · {machine} · {author}\n"
             f"Did:     {did}\n"
             f"Next:    {nxt}\n"
             f"Blocked: {blocked}\n")
    target = Path(project_dir) / "MEMORY.md" if project_dir else Path("MEMORY.md")
    try:
        if target.exists():
            text = target.read_text(encoding="utf-8")
            marker = "\n---\n"
            if marker in text:
                head, rest = text.split(marker, 1)
                target.write_text(head + marker + "\n" + entry + "\n" + rest.lstrip("\n"),
                                  encoding="utf-8")
            else:
                target.write_text(text.rstrip() + "\n\n---\n\n" + entry, encoding="utf-8")
        else:
            target.write_text(f"# MEMORY.md\n\n---\n\n{entry}", encoding="utf-8")
    except Exception as e:
        log.warning("memory_append failed: %s", e)


def run_loop(probe, resume) -> None:
    import relay_lanes as lanes
    log.info("Performing startup lane validation...")
    avail = lanes.available_lanes(refresh=True)
    log.info("relay control plane up (profile=%s, poll=%ss, autodispatch=%s, cap=%s)",
             CFG.profile, CFG.poll, CFG.autodispatch, CFG.max_workers)
    log.info("Available lanes (auth-checked): %s", ", ".join(avail) or "(none)")
    while True:
        if CFG.data_dir.exists():
            for d in CFG.data_dir.iterdir():
                if (d / "active").exists():
                    supervise(d.name, probe, resume)
        auto_dispatch()
        time.sleep(CFG.poll)


if __name__ == "__main__":
    from relay_spawn import probe as _probe, resume as _resume
    run_loop(_probe, _resume)
