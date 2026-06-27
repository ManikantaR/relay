---
name: relay-models-refresh
description: Refresh Relay's global model policy and catalog when Anthropic ships a new model (~every 2 months). Use when the user says "refresh relay models", "update model policy", "a new Claude model dropped", "bump relay's models", or asks to keep relay's model config current. Updates ONE global file (~/.config/relay/models.yml) + a catalog, never per-repo copies.
---

# relay-models-refresh

Keep Relay's model configuration current from a single global source. Relay routes workers by
**alias** (`sonnet`/`opus`), which the `claude` CLI auto-resolves to the latest model, so policy
rarely needs touching. What this skill maintains is the **global file** (`~/.config/relay/models.yml`,
or `$RELAY_MODELS_FILE`) and a **catalog** of current model facts (ids, pricing, context, effort)
for cost display and the dispatch UI. It never edits per-repo `.crew/models.yml` files — those are
rare overrides, and a refresh can't reach repos that aren't checked out.

## When to run
Anthropic ships a model (~every 2 months), or the user wants to verify relay's model config isn't
stale. Cadence is human-triggered, ~6×/year.

## Source of truth — do NOT hand-maintain model facts
Get current model facts from the authoritative source, in this order:
1. **The `claude-api` skill** — it carries a dated, authoritative model + pricing table that
   Anthropic maintains (model ids, $/MTok input/output, context window, max output, effort
   support). Read it / invoke it rather than recalling from memory.
2. If you need the very latest, **WebFetch** `https://platform.claude.com/docs/en/about-claude/models/overview.md`
   and `.../pricing.md`, or query the Models API (`client.models.list()`), and prefer those numbers.

Never invent or guess a model id, price, or context window. If a fact isn't in (1) or fetched
from (2), say so and stop.

## Procedure
1. **Gather** the current model facts for the active Claude models (Opus, Sonnet, Haiku tiers, plus
   any new tier) from the source above: alias → canonical id, input $/MTok, output $/MTok, context
   window, max output tokens, supported effort levels.
2. **Write the catalog** to `~/.config/relay/model-catalog.json` (alongside the policy file; honor
   `RELAY_MODELS_FILE`'s directory if set). Shape:
   ```json
   {
     "updated": "<ISO date>",
     "models": [
       {"alias": "sonnet", "id": "claude-sonnet-4-6", "input_usd_mtok": 3.0,
        "output_usd_mtok": 15.0, "context": 1000000, "max_output": 64000,
        "effort": ["low","medium","high","max"]}
     ]
   }
   ```
   This is what cost reporting and the future per-role dropdown read.
3. **Update the policy** `~/.config/relay/models.yml` ONLY where needed:
   - Keep aliases as-is — they auto-track the latest, so usually nothing changes.
   - If a default uses a *pinned dated id* that a newer model supersedes, bump it (and tell the
     user). If a model dropped an effort level a default relies on, adjust it.
   - Do not change the user's routing decisions (which role uses which tier) — that's their call;
     only surface a suggestion if a clearly-better/cheaper model now exists.
4. **Flag stale per-repo overrides you can see.** Optionally `grep` checked-out repos for
   `.crew/models.yml` files that pin dated ids; list any that look stale. You CANNOT edit repos
   that aren't present — just report them so the user can fix or (better) delete them in favor of
   the global default.
5. **Show a diff** of the policy + catalog and ask before writing. After writing, remind the user
   that `~/.config/relay/` is machine-local (per-machine for personal vs work) and isn't committed —
   re-run this skill on each machine (NAS, work laptop) that runs relay.

## Guardrails
- One global file is the source of truth. Do not scatter model config into repos.
- Aliases first; pin dated ids only on explicit request.
- Verify every model id against the `claude-api` skill before writing it — a wrong id makes
  `claude --model <id>` fail at dispatch.
