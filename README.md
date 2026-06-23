# Relay

**Talk to one agent. It runs the rest — and resumes where it left off.**

Relay is a portable orchestrator for autonomous coding agents. One Python control plane runs
on both your machines; each project carries its own policy in an in-repo `.crew/` directory,
so the leash travels with the code it protects — the way a Claude skill or plugin travels.

You own the work item and the merge. The crew owns the diff. On sensitive files, an agent's
approval is **input, never permission**.

---

## How it fits together

```
                    ┌──────────────────────────────────────────────┐
                    │                  YOU (owner)                  │
                    │   plan · brainstorm · specs · approve merge   │
                    └───────────────┬───────────────┬──────────────┘
                                    │               │
                       talk to lead │               │ read every Tier-2 diff
                                    ▼               ▲
        ┌───────────────────────────────────────────────────────────────┐
        │              RELAY CONTROL PLANE  (Python, trusted)            │
        │   holds board creds · applies labels · files PRs · notifies    │
        │   watchdog: rate-limited → probe&resume | hung → escalate      │
        └───┬───────────────────┬────────────────────────┬──────────────┘
            │ board ops          │ spawn                   │ notify
            ▼                    ▼                         ▼
   ┌─────────────────┐  ┌──────────────────┐     ┌──────────────────┐
   │   BOARD adapter │  │  SPAWNER (ladder) │     │  Telegram / Teams │
   │  GitHub │ Azure │  │ wt-tab→bg-job→tmux│     │  tier-aware alerts│
   └─────────────────┘  └────────┬─────────┘     └──────────────────┘
                                 │ launches
                                 ▼
                  ┌────────────────────────────────┐
                  │  WORKER  (agent, no creds)      │
                  │  disposable git worktree        │
                  │  writes status.md + worker.log  │  ← the IPC contract
                  └────────────────────────────────┘
```

**The key boundary:** the worker is a pure code worker. It never holds board credentials and
cannot apply its own labels or merge itself. Only the Python control plane mutates the board.
That is what makes the leash real rather than the agent asking permission of itself.

---

## Task lifecycle

```
 work item (agent-ready, valid contract)
        │  control plane: apply agent-wip, write brief, spawn
        ▼
 worker in disposable worktree ──writes──► data/<task>/status.md
        │  implement
        ▼
 reviewer agent reviews ► comments
        │
        ▼
 implementer agent fixes ► reviewer re-checks
        │
        ▼
   ┌──────────────── tier? ────────────────┐
   ▼ tier-1                                ▼ tier-2
 PR ready (CI green)                 PR HELD for owner
 notify: skim-when-convenient        notify: needs-your-eyes (no rush)
   ▼                                        ▼
 owner skims ► merge                 owner reads raw diff line-by-line ► merge
```

## Worker state machine (what the watchdog does)

```
                         ┌─────────────┐
                         │  PROGRESS   │── no update > HANG_THRESHOLD ─► hung
                         └──────┬──────┘                                (escalate, no respawn)
            usage limit hit     │           work finishes
                  ▼             │                 ▼
          ┌──────────────┐      │           ┌──────────┐
          │ RATE_LIMITED │      │           │   DONE   │
          └──────┬───────┘      │           └────┬─────┘
   cheap-probe every N s        │        tier-1 ◄┴► tier-2
                  │             │      arm merge   hold for
   window reopens ▼             │      poll        your review
          ┌──────────────┐      │
          │ resume from  │◄─────┘  crash / no status file → respawn from worktree
          │ worktree     │
          └──────────────┘
```

No fixed backoff: if the window reopens at minute 1 of a 5-hour limit, the probe catches it
within one interval instead of sleeping the other 4h59m.

---

## Setup — do this once

### Step 1 — clone and check Python
```bash
git clone <your-relay-repo> relay && cd relay
python3 --version            # need 3.10+
```

### Step 2 — create your environment file (NEVER committed)
Copy the template and fill the TODOs for the machine you are on:

```bash
# at home:
cp env.example.txt data/captain.personal.md      # set GITHUB_REPO + TELEGRAM_* (no token — uses gh)
# at work:
cp env.example.txt data/captain.work.md          # set TFS_URL + TEAMS_* + RELAY_AREA; set RELAY_PROFILE=work
```

`.gitignore` already blocks `data/captain.*.md` — your PAT never reaches git. Load it before
running:

```bash
set -a; source data/captain.personal.md; set +a      # bash/zsh
```
```powershell
Get-Content data\captain.work.md | ForEach-Object { if ($_ -match '^(\w+)=(.*)') { [Environment]::SetEnvironmentVariable($matches[1],$matches[2]) } }
```

### Step 3 — (work only) point Relay at your existing TFS scripts
You already have PowerShell scripts that pull TFS tickets, file PRs, and comment. Relay
**wraps** them — you do not rewrite them. Fill the four TODO methods in
`py/relay_board.py -> TFSBoard` so each shells out to your script. Set their location:

```
RELAY_TFS_SCRIPTS=C:\path\to\your\tfs-scripts
```

Do **not** commit your work scripts to a personal repo — leave them at work; the adapter
calls them by path.

### Step 4 — onboard a project (generates its `.crew/` policy)
Launch your harness in the Relay directory and run the `relay-onboard` skill against a repo.
It scans to propose Tier-2 paths, interviews you to confirm, files a gap issue for any sacred
path with no protected test, and writes `.crew/` files for you to review and commit **into
that project's repo**.

### Step 5 — run it
```bash
./relay pull                 # list ready (agent-ready) tickets
./relay dispatch 1234 --project ../moneypulse
./relay watch                # supervision daemon (keep running on the NAS)
./relay status               # active workers and their states
```

On Windows use `.\relay.ps1 <cmd>`. The `watch` daemon is what you keep alive on an always-on
box (a NAS) so work continues when your laptop is closed.

---

## The two-tier leash

| | Tier-1 (everything else) | Tier-2 (keys, encryption, PII, auth, migrations) |
|---|---|---|
| Flow | implement -> agent-review -> fix -> you skim -> merge | drafts -> **you read every line at a desk** -> merge |
| Reviewer agent | sufficient to proceed | **input only — never authorizes merge** |
| Tests | normal | owner-authored, worker may not edit (CI-enforced) |
| Timing | when convenient | may wait until tomorrow — correct, not a stall |

Tier-2 paths and protected tests are per-project in `.crew/`. Rules are shared and
un-weakenable (`lib/policy.yml`): `no-mistakes` always, auto-edit inside worktrees, **never**
auto-merge, **never** yolo — identical at work and home.

## Profiles

`RELAY_PROFILE=personal|work` selects adapters only (board source + notification channel).

| | personal | work |
|---|---|---|
| Board | GitHub Issues (via `gh`, no token) | TFS (wraps your PS scripts) |
| Notify | Telegram | Teams webhook |

## Cross-platform spawning

The spawner walks a capability ladder and announces which rung it used (never a silent
degrade): **wt-tab** (Windows Terminal headless tab, tier-colored) -> **bg-job** (PowerShell
background job) -> **tmux** (Mac). All three write the same `status.md`/`worker.log` to disk,
so the watchdog is backend-agnostic. On Windows you watch a worker by opening its tab or
tailing its log; mid-run keystroke injection is not available natively — intervene by stopping
and re-dispatching.

## Honest limits

- **Continuity needs an always-on host.** On a closed laptop the crew sleeps too. Run
  `relay watch` on a NAS or similar.
- **Usage limits are not dodgeable.** When rate-limited, nothing buys compute — the crew idles
  until the window reopens. Relay resumes fast; it does not beat the ceiling.
- **PowerShell-side spawn is not machine-validated here** (this build env has no `pwsh`); the
  Python is compile-checked. Run a dry dispatch on each machine before trusting it.

## Layout

```
relay / relay.ps1             entrypoints -> py/relay_cli.py
py/relay_cli.py               command dispatcher (watch|pull|dispatch|status)
py/relay_control.py           watchdog, probe/resume state machine, notifications
py/relay_board.py             board interface + GitHub via gh (done) + TFS (TODO skeleton)
py/relay_spawn.py             capability-ladder spawner (wt-tab->bg-job->tmux)
AGENTS.md                     the orchestrator the lead reads
lib/policy.yml                shared, un-weakenable rules
skill/SKILL.md                relay-onboard: per-project .crew generator
.github/workflows/            protected-test CI guard
examples/moneypulse/.crew/    worked example policy
env.example.txt               the template you copy + rename (committed empty)
```

See `INSTALL.md` to push to your own GitHub. License: MIT.
