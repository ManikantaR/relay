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

## 2026-06-26 · personal · agent
Did:   Consolidated the entire Relay v2 session sequence into one durable checkpoint. What was
       planned at the start of this run was: finish the session-centric Relay v2 runtime,
       bridge the older v1 task model into it, expose operator control/inspection through CLI
       and daemon, make the VS Code extension session-aware, make the extension installable and
       professional enough for real daily use, and then drive toward a live smartocrprocess
       trial. What is now COMPLETE, in order, is:
       (1) v2 session store/state machine/daemon scaffold; (2) review-loop runtime and daemon
       hooks; (3) v1->v2 bridge for tasks/status/close-out; (4) CLI session inspection
       (`sessions`, `session`, `timeline`, `transcript`, `evidence`, `session-diff`);
       (5) CLI/daemon session control (`terminate`, `checkpoint`, `refresh`, pause/resume/
       review actions); (6) board/dashboard feed aligned to v2 sessions; (7) VS Code
       extension made session-aware; (8) `relay doctor` readiness audit; (9) `relay
       vscode-package` and `relay vscode-install`; (10) local `vsce` install plus verified
       VSIX packaging and successful VS Code installation; (11) runtime classification fix so
       quota-blocked tasks surface as `needs_decision`; (12) Mission Control redesigned from a
       sparse kanban into a selected-session operator console and reinstalled into VS Code.
       Current live smartocrprocess state is: no `ready` items, one active session
       `task_smartocrprocess-12` in `needs_decision` (Tier-2, Claude-credit blocked), and PR
       `#45` in review for issue `#44`.
Next:  Prioritized remaining backlog:
       P1. Open the updated VS Code Mission Control and do a live UI smoke check: selected
       session hydration, grouped tree, right-rail triage, and all focus-card actions.
       P2. Unblock or replace the live trial target: either restore Claude credits and retry
       Tier-2 issue `#12`, or create/release a fresh Tier-1 `agent-ready` issue in
       smartocrprocess so the full dispatch/review loop can be exercised immediately.
       P3. Run a real end-to-end trial through the installed extension: dispatch, inspect,
       checkpoint/nudge, review handoff, and reconcile resulting session/board state.
       P4. Clean up board/workflow truth: decide how Relay should reconcile stale GitHub labels
       like `agent-ready`+`agent-wip` on dead tasks, and whether owner-facing recovery actions
       (retry/release/clear stale WIP) should be first-class commands.
       P5. Refine operator UX after live use: inline diff/evidence preview, optional
       terminal-first split mode, and possibly a smaller secondary queue-board toggle instead
       of the old board-first layout.
Blocked: external repo/provider state, not core Relay architecture. Specifically: issue `#12`
       cannot advance without Claude credits because Tier-2 never fails over; issue `#44` is
       already in review; there are no fresh `agent-ready` issues to dispatch right now.

## 2026-06-26 · personal · agent
Did:   Rebuilt the VS Code Mission Control UI around the approved focused-operator design.
       The dashboard webview is no longer a mostly empty kanban; it is now a selected-session
       console with top summary stats, a center focus card, timeline/changed-files/evidence/
       transcript panels, and a right rail for `Needs Decision`, `Review Queue`, and `Ready`
       queues. Wired it to fetch real session detail through the existing Relay CLI surfaces
       instead of inventing parallel state. Also tightened the native tree: grouped sessions
       into `Needs Decision`, `Active`, and `Done`, and fixed the status bar to count true
       active sessions. Validation is green: extension compile passes, 64 pytest tests pass,
       and the redesigned VSIX was packaged and reinstalled into VS Code successfully.
Next:  Open the updated Relay Mission Control in VS Code and verify the live interaction loop:
       selected session hydration, action buttons, right-rail triage, and grouped worker tree.
       After that, decide whether to add a terminal-first split mode or inline diff/evidence
       previews based on the live feel.
Blocked: none in Relay itself; live smartocrprocess dispatch still depends on repo/provider state (`#12` is claude-credit blocked, `#44` already in review, no fresh ready issue).

## 2026-06-26 · personal · agent
Did:   Improved the runtime classification around the real smartocrprocess blocker. Relay now
       treats provider messages like "usage credits required" as a quota/rate-cap signature in
       the finisher, and the v1->v2 bridge now maps inactive `ERROR` tasks into
       `needs_decision` instead of leaving them as dead generic `error` sessions. Revalidated:
       64 pytest tests pass, and refreshing the real `task_smartocrprocess-12` session now
       moves it into `needs_decision` with a bridge event instead of showing a bare error. The
       board/dashboard feed now reflects that owner-facing state directly.
Next:  The live smartocrprocess path is narrowed to repo state and provider state, not Relay
       ambiguity. The next practical move is to either restore Claude credits for Tier-2 issue
       `#12` and retry it, or create/release a fresh Tier-1 `agent-ready` issue so the full
       dispatch/review loop can be exercised without the sacred-lane credit dependency.
Blocked: no fresh `agent-ready` issues are currently dispatchable in smartocrprocess; issue `#12` is blocked by Claude usage credits and issue `#44` is already in PR review.

## 2026-06-26 · personal · agent
Did:   Cleared the packaged VS Code install path end to end. Installed `@vscode/vsce` as a
       local dev dependency in `vscode/`, fixed two real path bugs in `relay vscode-package`
       (local `vsce` path and VSIX output path under `cwd=vscode`), revalidated the suite
       (`62 passed`), and then exercised the actual operator flow: `./relay vscode-package`
       now produces `/Users/manikantaradhakrishna/repo/relay/vscode/relay-control-0.1.0.vsix`
       and `./relay vscode-install --force` successfully installs it into VS Code. Doctor now
       reports packaging as healthy; the installed extension is visible as
       `manikantar.relay-control@0.1.0`.
Next:  The remaining real blocker before the smartocrprocess live issue trial is GitHub CLI
       auth. After `gh auth login -h github.com`, run a real dispatch/review flow against the
       local smartocrprocess repo and exercise it through the installed extension.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Tightened `relay doctor` so VS Code install readiness is explicit. It now reports a
       separate `vscode_packaging` check, which reflects the real machine state: extension
       source and compiled bundle are present, but local VSIX packaging is not deterministic
       because `vsce` is not installed locally and the `npx` fallback stalls in this
       environment. Re-validated after the change: 62 pytest tests pass, compileall passes,
       and doctor against local smartocrprocess now cleanly reports the two remaining launch
       gates: invalid `gh` auth and missing local `vsce`.
Next:  Repair `gh auth`, install local `vsce`, then do two tests in order: package/install
       the extension through Relay and run the real smartocrprocess GitHub-issue dispatch
       trial through the updated CLI/extension surfaces.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine; packaged VS Code install remains blocked by missing local `vsce`.

## 2026-06-26 · personal · agent
Did:   Added first-class VS Code packaging/install commands to Relay itself:
       `relay vscode-package` and `relay vscode-install`. They compile the extension,
       package a VSIX via local `vsce`/global `vsce`/`npx @vscode/vsce`, and install it via
       the VS Code CLI. Added focused tests for the command wiring and documented the flow in
       [vscode/README.md](/Users/manikantaradhakrishna/repo/relay/vscode/README.md:1). A live
       probe on this machine showed the important operator behavior: without a local `vsce`,
       packaging now fails fast with a clear timeout instead of hanging while `npx` tries to
       fetch tooling.
Next:  Two concrete launch blockers remain before the full smartocrprocess trial from inside
       VS Code: repair `gh auth` for GitHub issue pickup, and install `vsce` locally (or add
       it to the extension workspace) so `relay vscode-package/install` can produce a VSIX.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine; VS Code install packaging is additionally blocked by missing local `vsce`.

## 2026-06-26 · personal · agent
Did:   Added a new `relay doctor` readiness audit so the local launch/trial path is explicit
       instead of inferred. It checks board repo config, managed project path, required
       `.crew` policy files, GitHub CLI auth health, local toolchain (`tmux`, `git`,
       `python3`, `node`, `npm`, `code`), VS Code extension source/bundle presence, and the
       indexed session store. Added tests for both a clean-ready case and the real broken-auth
       case. Validation is green: 60 pytest tests, `python3 -m compileall`, `npm run compile`,
       and `npm pack --dry-run` using a repo-local npm cache all pass. Running `relay doctor`
       against local `smartocrprocess` confirms the launch surface is otherwise ready; the
       only hard failure is still invalid `gh` auth on github.com.
Next:  Repair `gh auth` on this machine, then run the real smartocrprocess GitHub-issue
       dispatch/review trial and install the VS Code extension into a live VS Code session so
       the operator loop can be exercised end-to-end.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Aligned the board/dashboard feed with the v2 session model. `relay board --json` now
       emits active work from bridged v2 sessions instead of legacy worker rows, and the VS
       Code dashboard now peeks by `session_id` and treats session states (`running`,
       `paused`, `held`, `needs_decision`, etc.) as first-class UI states. Validation remains
       green: 58 Python tests and extension compile pass.
Next:  The runtime, daemon, CLI, and extension are now mostly on one session-centric model.
       The next practical milestone is still the live local trial against smartocrprocess once
       GitHub auth is repaired, because that is now the strongest missing evidence.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Added more session-centric operator actions to the VS Code extension: timeline and
       evidence views are now first-class commands alongside diff and peek, so the extension
       exposes the new v2 session surfaces directly instead of forcing everything through the
       old worker log mental model. Validation remains green: `npm run compile` passes and the
       Python suite is still at 57 passing tests.
Next:  The runtime and extension are in a good pre-trial state. The remaining practical gate
       for the real smartocrprocess issue trial is still GitHub auth. After that is repaired,
       run a real local dispatch and inspect it through the updated session-aware extension.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Added real session-action wrappers to the CLI (`session-terminate`,
       `session-checkpoint`, `session-refresh`) and wired the VS Code extension to use them
       for session-centric control actions. The extension now has concrete checkpoint/refresh/
       terminate commands instead of placeholder behavior, and it compiles cleanly against the
       v2 session model. Full validation is green: 57 pytest tests and `npm run compile`.
Next:  The runtime and extension are now far enough along that the main remaining practical
       blocker is the live GitHub issue trial. Once `gh auth login` is repaired, run a local
       smartocrprocess dispatch/review flow through the updated extension or CLI and observe
       how the bridged sessions behave end-to-end.
Blocked: live GitHub-backed issue pull/dispatch trial is still blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Made the VS Code extension session-aware. The Relay sidebar now reads from the v2
       `sessions` surface instead of the old active-worker-only feed, and the detail panel now
       pulls session facts plus transcript/evidence-backed content from the new session-centric
       CLI commands instead of the old `peek` path. `npm run compile` is green again after the
       refactor. Also checked the local trial path: the `smartocrprocess` repo exists locally
       and the extension can be compiled here, but a real GitHub issue trial is currently
       blocked because `gh auth status` shows the configured GitHub token is invalid.
Next:  Once GitHub auth is repaired, run a real local trial against smartocrprocess issue
       flow. In parallel, the next safe engineering move is to expose more session control and
       session views in the extension rather than keeping the old worker-centric assumptions.
Blocked: live GitHub-backed issue pull/dispatch trial is blocked by invalid `gh` auth on this machine.

## 2026-06-26 · personal · agent
Did:   Extended the daemon from read-mostly into a better session control surface. Added
       terminate, acknowledge-decision, request-checkpoint, and refresh actions through the
       daemon contract, plus a generic event append helper in the store. This gives the v2
       runtime enough control verbs to start behaving like a real operator API instead of just
       a passive inspection layer. Full suite is green: 56 passed.
Next:  Inspect the local smartocrprocess setup and see how safely we can run a real local
       trial through the current Relay flow, then check the VS Code extension build/install
       path against the new session-centric runtime.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Extended the v2 session-centric inspection path with transcript, evidence, and diff
       reads. Added CLI commands `relay transcript`, `relay evidence`, and
       `relay session-diff`, plus matching daemon endpoints under `/api/sessions/{id}/...`.
       The implementation routes through shared bridge helpers so pure v2 sessions and bridged
       v1 tasks resolve logs/evidence/worktree diffs the same way. Full suite is green:
       54 passed.
Next:  The next meaningful decision is whether to surface these v2 session reads inside the
       existing VS Code extension or keep building daemon/web endpoints first. Runtime-wise,
       the clean next step is to expose more session actions through the daemon before touching
       UI rendering.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Added read-only CLI inspection for the v2 session store: `relay sessions`,
       `relay session <id>`, and `relay timeline <id>`. These commands are bridge-aware:
       they first sync any current v1 task artifacts into the v2 store, then render session
       list/detail/timeline output without changing the existing `status`/`board` surfaces.
       Learned that dynamically loaded CLI tests need the imported `relay_control.CFG.data_dir`
       patched inside the loaded module, not only in the outer test module, otherwise the CLI
       points at the wrong store path. Full suite is green: 52 passed.
Next:  Decide whether to make existing `status`/`board` session-aware or keep those as v1
       views while the VS Code extension grows a parallel v2 session surface. The next clean
       runtime step is probably exposing transcript/evidence/diff through session-centric CLI
       and daemon endpoints.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Added the first v1->v2 bridge. New `relay_bridge.py` now mirrors existing task
       artifacts (`meta.json`, `status.md`, `active`, `brief.md`) into deterministic v2
       sessions, syncs watchdog state into the session store, and marks review-pending or
       needs-decision outcomes during close-out. Wired the bridge into dispatch, watchdog
       supervision, and close-out paths. Learned that the bridge must snapshot the v1 brief
       into the v2 session directory instead of pointing at `../task/brief.md`, otherwise the
       store tries to create invalid relative paths inside the session tree. Full suite is
       green: 49 passed.
Next:  Decide how aggressively to route live CLI/status surfaces onto the v2 session store.
       The next low-risk move is to expose bridged sessions via CLI/daemon status views before
       replacing more of the v1 lifecycle.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Wired the review-loop runtime into the daemon/API contract. Added
       `/api/sessions/{id}/request-review` to spawn reviewer sessions and
       `/api/sessions/{id}/submit-review` to deliver approval or line-specific change requests
       back into the parent session through the store. Added request-level tests for both
       change-request and approval flows. Full suite remains green: 46 passed.
Next:  Start joining the v2 daemon/runtime with the older orchestration path: map task
       dispatch and status artifacts into sessions, then decide whether to route new work
       through the v2 store first or keep v1/v2 side-by-side behind a narrower adapter.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Added the first review-loop runtime slice for Relay v2. Implemented review helpers for
       spawning branchless reviewer sessions, appending line-specific feedback back into the
       same brief, tracking review rounds, forcing `needs_decision` on cap, and marking
       parent sessions `approved` or `changes_requested`. The test pass exposed that the
       state machine lagged the real review protocol, so the transition table was updated to
       let reviewer sessions finish cleanly and let parent sessions move from
       `review_requested` into review outcomes. Full suite is green: 44 passed.
Next:  Wire review runtime into daemon/API orchestration flows: request-review endpoints,
       review submission payloads, and parent/reviewer session coordination through the
       session store rather than manual helper calls.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Hardened the initial v2 daemon/storage slice. Added SQLite rebuild-from-disk logic so
       the DB can be regenerated from canonical session/event artifacts, refactored daemon
       routing into a pure `handle_request()` path so the API contract is testable without
       socket permissions, and added tests for session rebuild plus daemon dispatch/pause/
       resume/nudge flows. Learned that this sandbox blocks ephemeral localhost binds in
       pytest, so the request contract now lives behind a pure handler function instead of
       being coupled to socket setup. Full suite is green: 40 passed.
Next:  Start the review-loop engine on top of the new session store: reviewer session
       lifecycle, same-brief feedback append, capped review rounds, and first escalation
       hooks. After that, wire the daemon endpoints deeper into real orchestration flows.
Blocked: none

## 2026-06-26 · personal · agent
Did:   Added the first Relay v2 runtime slice. Wrote [RELAY_V2.md] as the architecture
       contract, then implemented v2 session/event schema helpers, SQLite-backed indexing,
       a canonical state-transition module, schema artifacts under `schemas/`, and an
       initial `relayd` REST scaffold (`/api/health`, `/api/sessions`, dispatch, pause,
       resume, nudge). Restored local testability by creating a repo-local `.venv` and
       installing `pytest`; suite is now green again (37 passed). Also ignored `.venv/`.
Next:  Exercise and harden daemon/API behavior next: add HTTP-level tests, rebuild SQLite
       state from disk artifacts, then start wiring the review-loop engine onto the new
       session store instead of growing more UI first.
Blocked: none

## 2026-06-26 · personal · agent
Did:     smartocrprocess-44 done -> PR 45 (tier-1, lane copilot)
Next:    Owner: skim + merge.
Blocked: none

## 2026-06-25 · personal · agent
Did:     smartocrprocess-42 done -> PR 43 (tier-1, lane copilot)
Next:    Owner: skim + merge.
Blocked: none

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
