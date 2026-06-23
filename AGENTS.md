# AGENTS.md — Relay

> You own the work item and the merge. The crew owns the diff.
> On Tier-2 files, agent approval is **input, never permission**.

Relay is a portable orchestrator. You version it in your personal git and pull it into
any environment — personal laptop, work laptop. The engine is identical everywhere; each
**project** carries its own policy in an in-repo `.crew/` directory, so the leash travels
with the code it protects.

Any terminal coding agent (Claude Code assumed; codex/opencode also work) launched in this
directory reads this file and becomes the **lead**: it dispatches **workers**, supervises
them, and reports plain outcomes to you (the **owner**). You never talk to a worker directly.

Vocabulary: **owner** (you) · **lead** (the agent you talk to) · **worker** (an autonomous
agent on one task) · **deliver** (task that ends in a PR) · **investigate** (task that ends
in a report, pushes nothing).

---

## 0. Prime directives (from lib/policy.yml — cannot be weakened by any profile)

1. **Never auto-merge.** Every merge is a human click.
2. **Tier-2 is sacred.** Any diff touching the project's Tier-2 set is held for your
   line-by-line review. A reviewer agent's green check does NOT authorize merge.
3. **State lives on disk.** Workers are disposable. The worktree + the task's `status.md`
   are the durable truth. Any worker may die at any time; the next reconciles from disk.
4. **A work item is a contract.** Do not start one that lacks a checkable stop condition
   and a scope fence (§1). Escalate it back to the owner instead.
5. **When rate-limited, die cleanly; the watchdog resumes you** (§5). Never burn tokens
   retrying inside a limited window.
6. **An unguarded Tier-2 path stops the line.** A Tier-2 path with no protected test => file
   a gap issue and do not proceed on it (policy: `unguarded_tier2`).

---

## 1. The work-item contract

You do plan / brainstorm / specs at a desk, then freeze them into work items. Relay only
acts on items that satisfy this contract:

- **A tier label**: `tier-1` or `tier-2`.
- **A checkable stop condition** — not "add dark mode" but
  "dark-mode toggle persists across reload; existing component tests pass; no changes under `/crypto/`."
- **A scope fence** — which paths it may touch, and which it may not.

Missing any of these → the lead comments on the item asking the owner to complete the
contract, and does NOT dispatch it.

---

## 2. The label handshake (identical semantics, two surfaces)

Work items come from **GitHub Issues** (home) or **TFS** (work) — selected by profile (§9).
The label grammar is the same on both:

| Label | Applied by | Meaning |
|---|---|---|
| `agent-ready` | **owner** | Contract is complete. Relay pulls ONLY items with this. |
| `agent-wip` | lead | Picked up — visible so two workers never grab the same item. |
| `agent-review` | lead | PR is up, awaiting the tier gate. |
| `tier-2` | owner (or proposed by the skill) | Routes to the read-every-line gate. |

**Run-as-you pickup (important):** at work the agent acts as *you* — there is no separate
agent identity to assign. So pickup must NOT be "everything assigned to me." The pickup
query is:

> items tagged `agent-ready`, NOT yet `agent-wip`, AND (in the configured area path
> `RELAY_AREA` **or** containing an explicit `@relay` mention).

This keeps Relay from grabbing your whole personal ticket queue. Configure `RELAY_AREA`
per profile.

The Datadog/monitor path (work) files an item **without** `agent-ready`, tagged `tier-2`,
in a holding state. You read it, complete the contract, and apply `agent-ready` to release
it. Nothing from a production alert ever auto-dispatches.

---

## 3. Task lifecycle

```
work item (agent-ready, valid contract)
      │  lead dispatches
      ▼
worker in disposable worktree ──writes──► data/<task-id>/status.md
      │  implement
      ▼
reviewer agent reviews ► comments on PR
      │
      ▼
implementer agent fixes ► reviewer re-checks
      │
      ▼
  ┌─────────────── tier? ───────────────┐
  ▼ tier-1                              ▼ tier-2
PR ready (CI green)              PR HELD for owner
notify: skim-when-convenient    notify: needs-your-eyes (no rush)
  ▼                                     ▼
owner skims ► merge              owner reads raw diff line-by-line ► merge
```

Every transition writes `status.md` and emits a notification (§6).

---

## 4. The tier boundary (the leash)

Each project declares its own Tier-2 set in `.crew/tier2-paths.txt` (resolved §8). Tier-2 =
files where a subtle bug leaks secrets/PII/money. Rule: if a worker's diff touches **any**
Tier-2 path, the **entire PR** is Tier-2 — no splitting to sneak a line through Tier-1.

| | Tier-1 | Tier-2 |
|---|---|---|
| Implement / review / fix | agent | agent |
| Evidence | tests pass, CI green | tests pass, CI green **+ owner reads raw diff** |
| Merge authority | owner skims → merge | owner reads every line, unrushed → merge |
| Timing | when convenient | **may wait until next day at a desk** |

A held Tier-2 PR waiting hours for a proper desk review is correct behavior. Never frame it
as "stuck" (§6).

---

## 5. Usage-limit & hang handling (watchdog)

Agents that hit a hard usage limit **error out** — no graceful in-session sleep. Safe,
because state is on disk. `bin/relay-watch.sh` distinguishes three stop reasons:

- **rate-limited** → cheap-probe mode (`bin/relay-probe.sh` on `RELAY_PROBE_INTERVAL`). Do
  NOT respawn on every probe. On the **first clean probe**, respawn the worker against its
  worktree; it reads `status.md` and continues. Emit `resumed`.
  *Why not fixed backoff: if the window reopens at 4:59 into a 5h sleep you waste the rest.
  Poll-and-detect resumes within minutes.*
- **hung** (no `status.md` progress past `RELAY_HANG_THRESHOLD`, NOT rate-limited) → do NOT
  blindly respawn (loops the same failure). Escalate `hung` to the owner.
- **completed** → close out; Tier-1 arms merge poll, Tier-2 holds. Never respawn.

Honest caveat: when rate-limited, no orchestration buys compute. The crew idles until the
window reopens. Relay resumes fast; it does not dodge the ceiling. Architect throughput,
not evasion.

---

## 6. Notifications (channel-pluggable)

`bin/relay-notify.sh <event> <task-id> [detail]` dispatches to the profile's channel —
**Telegram** (home) or **Teams** webhook (work). Same events, same framing, different
transport. **`waiting-on-limit` and `hung` MUST read differently** — both look like "no
progress" from outside; one is fine, one needs you.

| Event | Framing | Urgency |
|---|---|---|
| `started` | 🟢 picked up `<item>` · `tier-N` | info |
| `tier1-ready` | ✅ PR ready (skim when convenient) | low |
| `tier2-held` | 🔒 needs your eyes — no rush, review at a desk | review |
| `waiting-on-limit` | ⏳ idle — rate-limited, probing, **not stuck** | info |
| `resumed` | ▶️ window reopened, resumed | info |
| `hung` | 🛑 **stuck — needs you** | action |
| `crashed-respawned` | 🔁 crashed, respawned from worktree | info |
| `merged` | 🎉 merged | low |
| `needs-decision` | ❓ blocked on your call | action |

---

## 7. Continue-while-held policy

When a Tier-2 PR is held, the crew **continues on independent open items** so the queue
drains overnight — but must **not** stack new work on the held files:

- An open item whose scope fence overlaps any path in a currently-held PR is **deferred**.
- All other open items drain freely.
- Worktree isolation prevents physical collisions; this rule prevents logical ones.

---

## 8. Config resolution (in-repo first)

For any project, Relay resolves policy as: **`<project>/.crew/` first, central `data/` as
fallback.** Files:

- `.crew/tier2-paths.txt` — the project's Tier-2 globs
- `.crew/protected-tests.txt` — gating tests the worker may not edit
- `.crew/project.md` — delivery mode (always `no-mistakes`) + `RELAY_AREA` for TFS pickup

In-repo config means the leash is version-controlled in the repo it governs and visible to
teammates — required for work. Generate these per project with the skill in `skill/`.

---

## 9. Profiles

Selected by `RELAY_PROFILE` (`personal` | `work`). A profile picks **adapters only**; it
inherits `lib/policy.yml` and cannot weaken it.

| | personal | work |
|---|---|---|
| Work items | GitHub Issues | TFS |
| Notify channel | Telegram | Teams webhook |
| Mode | no-mistakes, no yolo | no-mistakes, no yolo (identical) |

Profile secrets live in `data/captain.<profile>.md` (gitignored): tokens, `RELAY_AREA`,
webhook URLs.

---

## 10. Memory discipline (continuity across sessions and machines)

Two files carry context so work resumes cleanly on the other laptop or after time away:

- **CONTEXT.md** — durable cold-start briefing. Read it first. Rarely changes.
- **MEMORY.md** — running handoff log, newest entry on top. Relay's own is at the repo root
  (committed, no secrets). Each managed project has its OWN MEMORY.md in that project's repo
  (gitignored from Relay, so work context stays in the work repo).

Rules:
1. **At session start**, read CONTEXT.md then the latest MEMORY.md entry before acting. If a
   memory note conflicts with live `relay status`, live status wins.
2. **At session end (or on finishing a task)**, append a dated entry to the relevant
   project's MEMORY.md: what you Did, what's Next, what's Blocked. This is the baton-pass.
3. The control plane auto-appends skeleton entries on dispatch, Tier-2 hold, and block — you
   add the color (gotchas, decisions and why). Do not rely on memory you didn't write down.

## 11. Environment

```
RELAY_PROFILE=personal           # or: work
RELAY_AREA=                      # TFS area path (work pickup fence); empty at home
RELAY_PROBE_INTERVAL=300         # seconds between cheap rate-limit probes
RELAY_HANG_THRESHOLD=900         # no-progress seconds (if not rate-limited) = hung
RELAY_POLL=15                    # watcher cycle
RELAY_HEARTBEAT=600              # base fleet-review interval; backs off while idle
# --- lanes + autonomous dispatch (folded in from the orch prototype) ---
RELAY_LANE=claude                # default lane when an issue carries no lane:* label
RELAY_AUTODISPATCH=              # set to 1 to let the watch loop pull+dispatch agent-ready (opt-in)
RELAY_PROJECT=                   # repo path the auto-dispatcher targets (single project per profile)
RELAY_MAX_WORKERS=2              # concurrency cap on parallel workers (start 2-3)
```

## 12. Lanes + evidence-gated close-out (folded from orch)

A worker runs on one of three lanes — `claude` | `agy` | `codex` — chosen by `pick_lane`:
explicit `--lane` > a `lane:<x>` label > default. **Tier-2 always overrides to `claude`** —
sacred work never rides a cheap lane. Lanes give relay three separate provider quotas (the
structural answer to the single-provider ceiling the watchdog handles) and route cheap,
isolated work to agy/codex (Gemini credits) instead of the Claude budget.

Close-out is **evidence-gated**: the control plane refuses to file a PR unless the worker
left `data/<task>/evidence/summary.md` + (`pytest.txt` or a screenshot). The worker **commits
only**; the trusted plane pushes the branch and files the PR — the leash made structural.

### Lane resolution — availability + failover (AGREED 2026-06-23; relay_lanes.py — TODO)

The portable part of the system. Policy travels with the repo (`.crew`); **which lanes exist
travels with the environment.**

- **Allowlist, not auto-detect.** `RELAY_LANES` is an explicit ordered list in
  `captain.<profile>.md` — e.g. home `copilot,agy,codex,claude`, work `claude` (only
  org-sanctioned tools). Validated by a cheap auth-check at startup, cached ~daily (not per
  dispatch). Dead lanes dropped; the live set logged. Auto-detecting PATH is rejected: at work
  *available ≠ allowed*.
- **A `lane:<x>` label is a preference**, resolved against the live set. No label → env default.
- **Ladder order `copilot → agy → codex → claude`** (configurable via `RELAY_LANES` order).
  claude is the floor (must be last/listed). Substitution down the ladder on EITHER:
  1. **unavailable** — preferred lane not in the live set, or
  2. **rate-limited at runtime** — worker errors out capped → **resume on the next available
     lane** (from its worktree+status.md, same as crash-resume). Idle-probe-and-wait ONLY when
     *every* available lane is capped (then nothing buys compute). Track `tried_lanes` in meta;
     never re-try a capped lane; cap total failovers.
- **Tier-2 never fails over.** Sacred work forces `claude`; if claude is capped, it WAITS,
  never downgrades to a cheaper model. Sacred > throughput.
- **Work governance: hold explicit mismatches.** At work (`RELAY_STRICT_LANES=1`), an *explicit*
  `lane:X` request for an unsanctioned lane is **HELD + flagged**, not substituted. A no-label
  issue just runs on the sanctioned default — no hold.
- **Never silent.** Every substitution is recorded in meta + a notify: "ran t12 on copilot
  (agy unavailable here)" / "failed over agy→codex (rate limit)".

Copilot lane launch: `copilot --allow-all-tools --autopilot -p "$(cat brief)"` (headless).
