# MEMORY.md — Relay's own running log

> The tool's changelog and handoff notes. Committed (no secrets — Relay's own evolution only).
> Newest entry on top. The control plane appends skeleton entries on key events; agents and
> the owner add color. Per-PROJECT memory lives in each project's repo, not here.

## Format
Each entry:
```
## <ISO date> · <machine: personal|work> · <author: owner|agent>
Did:   <what changed>
Next:  <what should happen next>
Blocked: <anything waiting, or "none">
```

---

## 2026-06-23 · personal · agent
Did:   Convergence: folded the smartocrprocess `orch/` prototype INTO relay (relay is the
       base; orch/ superseded). Added (1) LANES claude|agy|codex — pick_lane routes by
       label/tier, Tier-2 always forced to claude; per-lane headless harness cmds in
       relay_spawn; (2) relay_finish.py classifies worker exit DONE/RATE_LIMITED/ERROR off
       the log, not the agent's goodwill; (3) evidence-gated close_out in relay_control —
       the TRUSTED plane pushes the branch + files the PR (worker commits only: closes the
       "who pushes" gap, makes the leash structural); (4) zero-token auto_dispatch (opt-in
       RELAY_AUTODISPATCH, RELAY_PROJECT, RELAY_MAX_WORKERS cap); (5) hang detection now
       uses worker.log mtime. 15 pytest green (tests/test_relay_logic.py). Generated
       smartocrprocess/.crew/. New env in AGENTS.md §11-12.
Next:  (1) **BUILD `py/relay_lanes.py`** per AGENTS.md §12 "Lane resolution" (AGREED, not yet
       coded): explicit RELAY_LANES allowlist + startup auth-check (cached); ladder
       copilot→agy→codex→claude; failover on unavailable OR rate-limit (resume next lane,
       track tried_lanes, idle-wait only when all capped); Tier-2 never fails over (claude
       waits); work RELAY_STRICT_LANES holds explicit-unsanctioned; announce every substitution;
       add the copilot lane to relay_spawn._harness_cmd. Wire into dispatch_ticket (resolve) +
       supervise (rate-limit failover). Add tests. (2) NAS RUNTIME: confirm
       claude/agy/copilot/codex + gh + tmux + python3.10 installed AND authed on the Ugreen NAS
       (workers run there). (3) File the storage.py OAuth protected-test gap issue before
       #12/#13. (4) Dry-run one agy/copilot dispatch of #12 end-to-end. (5) Then enable AUTODISPATCH.
Blocked: NAS worker-runtime auth unverified (can't reach the NAS from this session).
Resume:  this commit is the clean checkpoint. Lane resolution is spec'd in AGENTS.md §12,
       not yet implemented — start there. Engine (convergence) is done + 15 pytest green.

---

## 2026-06-23 · personal · owner
Did:   Built Relay. Python-only control plane (cli/control/board/spawn). Two-tier leash,
       capability-ladder spawner (wt-tab→bg-job→tmux), Telegram/Teams notify, GitHub board
       done + Azure DevOps skeleton. Added CONTEXT.md + MEMORY.md + `relay note`.
Next:  (1) Fill the 4 TFSBoard TODO methods at work by wrapping existing PS scripts.
       (2) Dry-run a dispatch on each machine to validate the spawner (pwsh not testable in
       build env). (3) Onboard MoneyPulse to generate its .crew/ policy.
Blocked: none.
