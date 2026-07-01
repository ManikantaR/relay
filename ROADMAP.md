# Relay roadmap

The master index. Near-term actionable items are GitHub issues in this repo (dogfooded —
Relay builds Relay), tagged `tier-*` / `lane:*` / `effort:*` / `dogfood`. This file is the
full picture; the issues are the dispatchable backlog.

Guiding lines (Cherny/Karpathy discipline — keep scope tight, don't over-abstract):
1. Exactly two boards: **GitHub + TFS**. No generic-tracker framework.
2. **One item → one repo → one PR.** Never cross-repo atomic transactions.
3. The UI is a **dispatch + review console**, not a project-management tool.
4. The **human merge gate never weakens** as repos multiply.

---

## ✅ Completed (this session)
- **Git hygiene** — pushed the v2 redesign to `main`; cleaned stray files; ignored runtime flags.
- **Token-burn fix** — `relay_models` resolver; `claude -p --model <id> --effort <level>`; real
  model id flows into meta + the v2 session. Sonnet implements / Opus reviews.
- **Verifier loop auto-wired** — `relay_verify`; phase-aware relaunch; `close_out` routes by
  phase; reviewer auto-spawn → approve / respawn-with-feedback / cap→needs_decision; decision
  log on the PR; `RELAY_REVIEW` gate; reviewer-error fallback.
- **Global model scope** — `env > repo .crew > ~/.config/relay/models.yml > defaults`;
  alias-first; `relay-models-refresh` skill scaffolded.
- **Per-issue effort** — `effort:<level>` label + `relay dispatch --effort`.
- **Reviewer lane** — reviewer always runs claude/Opus, never the implementer's lane.
- **Dogfood setup** — Relay `.crew/` (sacred set), label set, this roadmap as issues.
- **Repo registry + picker (#1; UX for #2)** — machine-local `~/.config/relay/repos.json`
  (`$RELAY_REPOS_FILE`/XDG; stdlib-only; seeded from `RELAY_PROJECTS` for back-compat);
  `relay repo add|list|rm`; `projects()` reads registry → env → single-repo. VS Code
  "Relay: Select Repo" QuickPick (with inline "Add a repo…"), active repo in `workspaceState`,
  `pull`/`dispatch`/`board` scoped via `--repo`, repo shown in header badge + status bar.
- Tests: 66 → 97 → 105 (+8 registry).

## 🔁 In flight
- **Live-verify the verifier loop** on smartocrprocess #32 (restart the stale `relay watch`
  first so it loads current code, then dispatch #32). smartocr #9 already landed live → PR #47
  (filed by the *stale* watch, so without the review loop).

## 📋 Near-term (GitHub issues, prioritized)
| # | Item | Tier | Lane | Effort |
|---|---|---|---|---|
| [#1](https://github.com/ManikantaR/relay/issues/1) | ✅ Repo registry + `relay repo add` (multi-repo onboarding) — **first dogfood** (branch `claude/repo-registry-quickpick`) | 2 | claude | high |
| [#2](https://github.com/ManikantaR/relay/issues/2) | Backlog + dispatch-from-UI panel — 🔜 repo-picker UX landed; backlog admit/dispatch panel remains | 1 | copilot | medium |
| [#3](https://github.com/ManikantaR/relay/issues/3) | Generate `model-catalog.json` | 1 | copilot | medium |
| [#4](https://github.com/ManikantaR/relay/issues/4) | Cross-provider review (configurable reviewer lane) | 2 | claude | medium |
| [#5](https://github.com/ManikantaR/relay/issues/5) | Real nudge channel (respawn-from-brief) | 2 | claude | high |
| [#6](https://github.com/ManikantaR/relay/issues/6) | Move dispatch + supervise into `relayd` | 2 | claude | high |
| [#7](https://github.com/ManikantaR/relay/issues/7) | TFSBoard adapter (wrap PowerShell; Azure Git repos) | 2 | claude | high |
| [#8](https://github.com/ManikantaR/relay/issues/8) | Board→repo mapping in the registry | 2 | claude | medium |
| [#9](https://github.com/ManikantaR/relay/issues/9) | Multi-repo dashboard grouping + filter | 1 | copilot | medium |
| [#10](https://github.com/ManikantaR/relay/issues/10) | Cost tracking (populate session token/USD) | 1 | agy | medium |

## 🗺️ Later (not yet issues)
- Web UI (LAN) + Telegram surfaces (RELAY_V2 phases 5–6).
- NAS deployment (Docker; the always-on target). Note: production self-hosted sandbox infra is
  a 6–12 month underestimate trap — keep it minimal (restart policy + egress firewall).
- Loose ends: PR #46 (smartocr #12 rescue) CI stuck in Azure `queued`; 2 moderate Dependabot
  alerts on smartocrprocess.

## Dogfooding rules (Relay builds Relay)
- Sequence: prove the loop on smartocr first → small tier-1 Relay task → tier-2 core.
- Relay's sacred set: `.crew/tier2-paths.txt` (core modules + `lib/policy.yml` + `AGENTS.md`).
- Per the bootstrap research: **review the issue spec + brief on tier-2, not just the diff** —
  a spec error propagates to every generation.
- Self-modification is bounded by Relay's own invariants: worktree isolation, no-creds, evidence
  gate, protected tests, never auto-merge, and the running watchdog being immune to unmerged
  self-edits (code in memory; only a restart after *you* merge loads new code).
