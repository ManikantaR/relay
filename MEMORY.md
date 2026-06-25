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

## 2026-06-25 · personal · agent
Did:     smartocrprocess-40 done -> PR 41 (tier-1, lane copilot)
Next:    Owner: skim + merge.
Blocked: none

## 2026-06-25 · personal · agent
Did:   UI: rebuilt the VS Code Mission Control webview as an AGENT KANBAN (Ready→Working→
       Waiting→Review) — the convergent pattern (Vibe Kanban/Nimbalyst/Cline/Conductor), cards
       auto-sort by state; Waiting≠stuck; Tier-2 "read every line". New `relay board --json`
       ({ready,active,review} across repos) + GitHubBoard.pull_review(). Applied 2026 webview
       best practice (CSP+nonce, --vscode-* theme vars, getState, a11y; Webview UI Toolkit is
       dead — hand-rolled). Added `.github/workflows/vscode-extension.yml` (npm install + tsc).
       **Extension now COMPILES GREEN in CI** (run 28138662531, 13s) — the local-tsc gap is
       closed; it type-checks with strict TS. 31 pytest green.
Next:  Owner: `cd vscode && npm install && F5` to run it live (CI already proved it compiles).
       Then the still-pending real-world steps: NAS runtime auth + dry-run #12 + AUTODISPATCH.
Blocked: none new (NAS runtime auth still owner action).

---

## 2026-06-24 · personal · agent
Did:   MULTI-REPO + UI. (1) Multi-repo: RELAY_PROJECTS="repo=path,..." registry -> projects();
       get_board(repo) per-repo; auto_dispatch serves every repo round-robin under ONE global
       RELAY_MAX_WORKERS cap; repo-qualified task ids (smartocrprocess-12 vs moneypulse-12);
       dispatch/close_out/meta carry repo; CLI pull/dispatch/status repo-aware. (2) Machine feed:
       `relay status|pull|lanes --json`. (3) Control verbs: `relay kill <task>`, `pause`/`resume`
       (.paused flag, auto_dispatch honors it). (4) VS Code extension `vscode/` ("Relay Control"):
       Workers tree + Mission Control webview + status bar + one-click pull/dispatch/kill/openPR/
       pause/attach-terminal; LOCAL ONLY; transport-agnostic via `relay.execPrefix` (local now,
       `ssh nas docker exec` / Remote-SSH later). 31 pytest green; manifests validated. Decision
       (researched, Karpathy autonomy-slider-GUI + Boris terminal+notifications): full-control
       dashboard as a VS Code EXTENSION (not a web server) — no exposed port, portable Mac+Windows.
Next:  (a) Extension is SCAFFOLDED not built — `cd vscode && npm install && npm run compile`, F5 to
       run; couldn't tsc here (no @types/vscode). Webview is basic — enrich to match the visual.
       (b) Still: NAS runtime auth + dry-run #12 + enable AUTODISPATCH (unchanged).
Blocked: extension needs local npm build (owner); NAS runtime auth (owner).

---

## 2026-06-24 · personal · agent
Did:   Finished wiring and testing `relay_lanes.py` per AGENTS.md §12. Removed obsolete `pick_lane` function from `relay_spawn.py` and its tests in `test_relay_logic.py`. Added new comprehensive tests for lane configuration, strict governance, and caching/validation behavior. Wired startup lane validation into `relay_control.py`'s `run_loop` to perform a cheap auth-check, drop dead lanes, and log the live set at startup. 27 pytest green.
Next:  (1) NAS RUNTIME: confirm claude/agy/copilot/codex + gh + tmux + python3.10 installed AND authed on the Ugreen NAS (workers run there). (2) File the storage.py OAuth protected-test gap issue before #12/#13. (3) Dry-run one agy/copilot dispatch of #12 end-to-end. (4) Then enable AUTODISPATCH.
Blocked: NAS worker-runtime/token setup is owner action (interactive logins on the Mac; can't reach the NAS from this session).

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

## 2026-06-23 · personal · agent
Did:   NAS deployment decided + documented (NAS_DEPLOYMENT.md). HOME = Docker on the UGREEN
       NAS, base image = ADOPT CLIDE (github itscooleric/clide — bundles claude/copilot/codex/gh
       + tmux + ttyd web terminal :7681 + iptables egress allowlist; audited safe, single-user;
       caveat: logs full prompts to intercept.jsonl) + layer agy + relay on top. WORK = relay
       NATIVE on the Windows laptop (no Docker; wt-tab/bg-job spawner; RELAY_STRICT_LANES=1;
       TFS+Teams). AUTH = long-lived SUBSCRIPTION TOKENS in .env (claude `setup-token` ~1yr;
       GH_TOKEN PAT w/ Copilot Requests covers gh+copilot; codex device-login or key; agy/Gemini
       creds), generated once on the Mac, injected as env — no browser in container. Egress
       allowlist += Gemini/agy hosts. Code lives in bind-mounted /workspace volume; branches
       relay/<lane>-t<id> pushed by control plane. Connect: Telegram primary + ttyd web terminal
       (LAN only) + ssh+tmux attach to intervene. Deleted the superseded smartocrprocess/orch/.
Next:  Build relay_lanes.py (still the top code task, AGENTS.md §12). Then a Dockerfile.relay +
       docker-compose on the NAS per NAS_DEPLOYMENT.md A2; one manual `relay dispatch 12 --lane
       agy` dry-run; then RELAY_AUTODISPATCH=1.
Blocked: NAS worker-runtime/token setup is owner action (interactive logins on the Mac).

---

## 2026-06-23 · personal · owner
Did:   Built Relay. Python-only control plane (cli/control/board/spawn). Two-tier leash,
       capability-ladder spawner (wt-tab→bg-job→tmux), Telegram/Teams notify, GitHub board
       done + Azure DevOps skeleton. Added CONTEXT.md + MEMORY.md + `relay note`.
Next:  (1) Fill the 4 TFSBoard TODO methods at work by wrapping existing PS scripts.
       (2) Dry-run a dispatch on each machine to validate the spawner (pwsh not testable in
       build env). (3) Onboard MoneyPulse to generate its .crew/ policy.
Blocked: none.
