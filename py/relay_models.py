"""
relay_models.py — resolve a worker's provider/model/effort from policy.

The token-burn fix. Workers must NOT take the harness's implicit expensive default: an
unpinned `claude -p` falls onto the 1M-context path that gates behind usage credits (this is
what killed the smartocrprocess-12 worker) and burns the Opus-tier rate. This resolves a
concrete model + effort (+ optional budget) for every spawned worker so the claude lane is
launched with `--model`/`--effort` pinned.

Resolution order (first wins):
  1. operator env override   (RELAY_CLAUDE_MODEL / RELAY_CLAUDE_EFFORT / RELAY_MAX_BUDGET_USD)
  2. project policy file      (.crew/models.yml, honored only when PyYAML is importable)
  3. built-in role defaults   (implementer = sonnet/medium, reviewer = opus/medium)

Stdlib-only: if PyYAML is absent or the file is missing, the built-in defaults apply — the
control plane keeps working with the right cheap default and takes no hard dependency. (When
the daemon runs under an interpreter with PyYAML, .crew/models.yml is honored; the system
`python3` the `relay` launcher picks may not have it, in which case defaults stand.)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Short aliases passed to `claude --model`; the canonical id is recorded in the session/meta.
_ALIAS_ID = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-8",
    "haiku": "claude-haiku-4-5",
}

# Built-in, un-credit-gated defaults. Sonnet 4.6 implements (Anthropic's best coding model,
# 1M context at standard pricing, ~half the cost); Opus 4.8 reviews (verification is the
# leverage point and where the bug-finding edge matters).
_ROLE_DEFAULT = {
    "implementer": {"provider": "anthropic", "model": "sonnet", "effort": "medium"},
    "reviewer": {"provider": "anthropic", "model": "opus", "effort": "medium"},
}

# Lanes other than `claude` drive their own provider/model; relay injects nothing.
_LANE_PROVIDER = {"agy": "google", "copilot": "github-copilot", "codex": "openai"}


def _env() -> str:
    return "work" if os.getenv("RELAY_PROFILE", "personal") == "work" else "personal"


def _canonical_id(model: str) -> str:
    return _ALIAS_ID.get(model, model)


def _from_policy(role: str, tier: str, project: str | None) -> dict[str, Any] | None:
    """Read .crew/models.yml if present and PyYAML is importable; else None (use defaults)."""
    if not project:
        return None
    path = Path(project) / ".crew" / "models.yml"
    if not path.exists():
        return None
    try:
        import yaml  # type: ignore
    except Exception:
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models = data.get("models", {}) or {}
        out: dict[str, Any] = {}
        pref = ((models.get("defaults", {}) or {}).get(role, {}) or {}).get(_env(), {}) or {}
        top = (pref.get("preferred") or [None])[0] or {}
        if top.get("provider"):
            out["provider"] = str(top["provider"])
        if top.get("model"):
            out["model"] = str(top["model"])
        if top.get("effort"):
            out["effort"] = str(top["effort"])
        if str(tier) == "2":
            t2 = (models.get("tier2", {}) or {}).get(role, {}) or {}
            if t2.get("effort"):
                out["effort"] = str(t2["effort"])
        return out or None
    except Exception:
        return None


def resolve(lane: str, role: str = "implementer", tier: str = "1",
            project: str | None = None) -> dict[str, Any]:
    """Return {provider, model, model_id, effort, max_budget_usd, selection_mode,
    selection_reason} for a worker on `lane`. Only the claude lane carries a real model."""
    role = role if role in _ROLE_DEFAULT else "implementer"

    # Non-claude lanes manage their own model; record provenance, inject nothing.
    if lane != "claude":
        return {
            "provider": _LANE_PROVIDER.get(lane, lane),
            "model": "", "model_id": "", "effort": "",
            "max_budget_usd": None,
            "selection_mode": "lane",
            "selection_reason": f"{lane} lane uses its own model",
        }

    base = dict(_ROLE_DEFAULT[role])
    reason = f"default {role}"
    # Tier-2 reviewer reads sensitive code at higher effort (spec §10.2 / models.yml escalation).
    if str(tier) == "2" and role == "reviewer":
        base["effort"] = "high"
        reason = "tier-2 reviewer (high effort)"

    pol = _from_policy(role, tier, project)
    mode = "auto"
    if pol:
        base.update({k: v for k, v in pol.items() if v})
        mode, reason = "policy", f"policy .crew/models.yml ({role})"

    # Operator env override wins over file + defaults.
    if os.getenv("RELAY_CLAUDE_MODEL"):
        base["model"] = os.environ["RELAY_CLAUDE_MODEL"]
        mode, reason = "override", "RELAY_CLAUDE_MODEL"
    if os.getenv("RELAY_CLAUDE_EFFORT"):
        base["effort"] = os.environ["RELAY_CLAUDE_EFFORT"]
        mode = "override"

    budget = os.getenv("RELAY_MAX_BUDGET_USD")
    try:
        budget_val: float | None = float(budget) if budget else None
    except ValueError:
        budget_val = None

    return {
        "provider": base.get("provider", "anthropic"),
        "model": base["model"],
        "model_id": _canonical_id(base["model"]),
        "effort": base.get("effort", "medium"),
        "max_budget_usd": budget_val,
        "selection_mode": mode,
        "selection_reason": reason,
    }


def claude_flags(spec: dict[str, Any] | None) -> str:
    """Render `claude` CLI flags for a resolved spec; '' when there's no model to pin."""
    if not spec:
        return ""
    model = spec.get("model_id") or spec.get("model")
    if not model:
        return ""
    parts = [f"--model {model}"]
    if spec.get("effort"):
        parts.append(f"--effort {spec['effort']}")
    if spec.get("max_budget_usd"):
        parts.append(f"--max-budget-usd {spec['max_budget_usd']}")
    return " " + " ".join(parts)
