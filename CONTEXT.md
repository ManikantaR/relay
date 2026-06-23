# CONTEXT.md — read this first

> Cold-start briefing. If you are an agent or a human picking up Relay (or a project Relay
> manages) after time away or on the other machine, read this before doing anything.
> This file is durable and human-authored. It changes rarely. For "what happened recently /
> what's in flight," read **MEMORY.md** instead.

## What Relay is

A portable orchestrator for autonomous coding agents. One Python control plane runs on both
the owner's machines (personal Mac, work Windows). The owner talks to a **lead** agent; the
lead dispatches **workers** (one per task, each in a disposable git worktree). The owner owns
the work item and the merge; the crew owns the diff.

## The rules an agent must NEVER break (from lib/policy.yml)

1. **Never auto-merge.** Every merge is a human click.
2. **Tier-2 is sacred.** Any diff touching a project's Tier-2 paths (keys, encryption, PII,
   auth, migrations — see that project's `.crew/tier2-paths.txt`) is HELD for the owner's
   line-by-line review. A reviewer agent's approval is **input, never permission**.
3. **Protected tests are owner-owned.** A worker may not edit any file in
   `.crew/protected-tests.txt`. CI fails the PR if it does.
4. **No work without a contract.** Only act on items tagged `agent-ready` with a checkable
   stop condition and a scope fence. Otherwise comment asking the owner to complete it.
5. **State lives on disk.** You are disposable. Write progress to `status.md`; the next worker
   reconciles from it. Never assume the session persists.
6. **No board credentials in worker context.** Only the Python control plane mutates the board.

## Where things live

```
AGENTS.md            orchestrator spec (how the lead dispatches/supervises)
CONTEXT.md           this file — cold-start briefing
MEMORY.md            running handoff log (recent changes, in-flight, blocked)  ← read for "what now"
lib/policy.yml       the un-weakenable rules
py/                  control plane (cli, control, board, spawn)
<project>/.crew/     that project's tier paths + protected tests + pickup fence
```

## How to continue work (the move that matters)

1. Read **MEMORY.md** — the latest dated entry tells you what the last session did, what is
   in flight, and what is blocked.
2. Run `./relay status` (or `.\relay.ps1 status`) to see live worker states.
3. Pick up from the "Next" line of the latest memory entry. If it conflicts with live status,
   live status wins — a worker may have moved since the note was written.

## Profiles

`RELAY_PROFILE=personal` (home: GitHub + Telegram) or `work` (Azure DevOps/TFS + Teams).
Rules are identical across both; only the board adapter and notification channel differ.

## If you are unsure

Stop and ask the owner. Surfacing a question is always cheaper than guessing on a codebase
where a wrong diff can leak PII. That caution IS the job, not a failure of it.
