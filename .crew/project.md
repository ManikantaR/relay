# Relay — project context for workers (dogfooding: Relay builds Relay)

Relay is a portable, provider-agnostic control plane that turns board items (GitHub issues /
TFS work items) into **reviewed** PRs. A trusted Python control plane (stdlib-only, zero-token)
dispatches disposable workers in git worktrees; a worker commits locally and stops; the control
plane pushes the branch, files the PR, runs the evidence gate + Opus review loop, and the owner
merges. You are one such worker, now working on Relay itself.

## Invariants you must not break (these are why Relay is trusted)
- Workers never push, never run `gh`, never open or merge a PR. The control plane does that.
- **Never auto-merge.** The owner merges every PR.
- **No-creds boundary:** a worker holds no board/remote credentials; it only commits locally.
- Go green by **fixing code**, never by deleting/skipping/`xfail`-ing tests or `--no-verify`.
- The control plane (`py/`) stays **stdlib-only** — no hard third-party deps. PyYAML is optional
  (model/repo policy degrades to built-in defaults when it's absent).
- The model defaults use **aliases** (`sonnet`/`opus`) so they track the latest model.

## Layout
- `py/` — control plane: `relay_control` (dispatch / supervise / close-out / review routing),
  `relay_spawn` (worker launch + phase-aware relaunch), `relay_models` (model policy),
  `relay_verify` (review loop: brief, verdict, decision), `relay_lanes` (routing + failover),
  `relay_board` (GitHub/TFS adapters — the credential holder), `relay_cli` (CLI),
  `relay_bridge` (v1→v2), `relay_store`/`relay_schema`/`relay_state`/`relay_daemon` (v2 sessions).
- `tests/test_relay_logic.py` — the safety net. Run: `cd relay && python3 -m pytest -q`.
- `vscode/` — the mission-control extension. `skill/` — installable skills.
- `.crew/tier2-paths.txt` — sacred files (read every line). `lib/policy.yml` — un-weakenable.

## Evidence mandate
Write `evidence/summary.md` (what changed + why + how each acceptance criterion is met) and
`evidence/pytest.txt` (captured `python3 -m pytest -q`). UI changes: a screenshot. Encouraged:
`evidence/decisions.md` (what you tried and ruled out) so the reviewer isn't reconstructing cold.
Tier-2 changes to the sacred set are read line-by-line by the owner.
