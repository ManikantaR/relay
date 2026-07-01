"""
relay_models.py — resolve a worker's provider/model/effort from policy.

The token-burn fix. Workers must NOT take the harness's implicit expensive default: an
unpinned `claude -p` falls onto the 1M-context path that gates behind usage credits (this is
what killed the smartocrprocess-12 worker) and burns the Opus-tier rate. This resolves a
concrete model + effort (+ optional budget) for every spawned worker so the claude lane is
launched with `--model`/`--effort` pinned.

Resolution order (first wins):
  1. operator env override   (RELAY_CLAUDE_MODEL / RELAY_CLAUDE_EFFORT / RELAY_MAX_BUDGET_USD)
  2. repo policy file         (<project>/.crew/models.yml — RARE override, only for a repo that
                               genuinely wants different routing)
  3. global policy file       ($RELAY_MODELS_FILE, else ~/.config/relay/models.yml) — the
                               operator's default for every repo; the one place to tune policy
                               and the only file the refresh skill maintains
  4. built-in role defaults   (implementer = sonnet/medium, reviewer = opus/medium)

Model routing is an OPERATOR property, not a per-codebase one — so the default lives globally,
not copied into every repo (that fan-out goes stale invisibly: a refresh can't touch a repo
that isn't checked out). Per-repo `.crew/models.yml` stays supported as the occasional override,
the way `.git/config` overrides the global git config.

Stdlib-only: if PyYAML is absent or no policy file exists, the built-in defaults apply — and
because the defaults use aliases (`sonnet`/`opus`), which the `claude` CLI resolves to the
latest, they rarely go stale even across model launches. The control plane takes no hard
dependency: the system `python3` the `relay` launcher picks may lack PyYAML, in which case the
(correct, cheap) defaults stand.
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


def _global_policy_path() -> Path:
    """The operator's global policy: $RELAY_MODELS_FILE, else ~/.config/relay/models.yml
    (honoring XDG_CONFIG_HOME). One file per machine — what the refresh skill maintains."""
    override = os.getenv("RELAY_MODELS_FILE")
    if override:
        return Path(override).expanduser()
    base = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "relay" / "models.yml"


def _repo_policy_path(project: str | None) -> Path | None:
    return Path(project) / ".crew" / "models.yml" if project else None


def _load_policy_file(path: Path | None, role: str, tier: str) -> dict[str, Any] | None:
    """Read a models.yml at `path` -> {provider?, model?, effort?} for this role/tier; None if
    the file is missing, PyYAML is unavailable, or it has nothing for this role."""
    if not path or not path.exists():
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


_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def effort_from_labels(labels: list[str] | None) -> str | None:
    """An `effort:<level>` label lets the owner dial thinking per-issue (medium vs high)."""
    for lbl in labels or []:
        if isinstance(lbl, str) and lbl.startswith("effort:"):
            v = lbl.split(":", 1)[1].strip().lower()
            if v in _EFFORT_LEVELS:
                return v
    return None


_MODEL_ALIASES = {"opus", "sonnet", "haiku"}


def review_model_from_labels(labels: list[str] | None) -> tuple[str | None, str | None]:
    """A `review:<model>[-<effort>]` label picks the reviewer's model per issue — e.g.
    `review:opus`, `review:sonnet`, `review:sonnet-medium`, `review:opus-high`. Returns
    (model_alias, effort); either may be None. Mirrors the `effort:`/`lane:` label pattern."""
    for lbl in labels or []:
        if isinstance(lbl, str) and lbl.startswith("review:"):
            parts = lbl.split(":", 1)[1].strip().lower().split("-")
            model = parts[0] if parts and parts[0] in _MODEL_ALIASES else None
            eff = next((p for p in parts[1:] if p in _EFFORT_LEVELS), None)
            if model or eff:
                return model, eff
    return None, None


# Lanes an `impl:` label may name — the claude lane plus every self-driving lane.
_IMPL_LANES = set(_LANE_PROVIDER) | {"claude"}


def _codex_model_id(suffix: str) -> str:
    """Map an `impl:codex-<suffix>` suffix to a codex-cli model id: `5.4` -> `gpt-5.4`,
    `5.4-mini` -> `gpt-5.4-mini`. Already-qualified ids (`gpt-…`) pass through unchanged."""
    suffix = suffix.strip().lower()
    return suffix if suffix.startswith("gpt-") else f"gpt-{suffix}"


def impl_from_labels(labels: list[str] | None) -> tuple[str | None, str | None]:
    """An `impl:<lane>-<model>` label pins the implementer's lane AND model per issue, mirroring
    the `review:`/`effort:`/`lane:` labels — e.g. `impl:codex-5.4` -> ("codex", "gpt-5.4"),
    `impl:codex-5.4-mini` -> ("codex", "gpt-5.4-mini"), `impl:claude-sonnet` -> ("claude",
    "sonnet"). The model is a claude alias for the claude lane (resolve() canonicalizes it) or a
    codex-cli id for the codex lane. Returns (lane, model); (None, None) if absent or malformed."""
    for lbl in labels or []:
        if isinstance(lbl, str) and lbl.startswith("impl:"):
            lane, _, suffix = lbl.split(":", 1)[1].strip().lower().partition("-")
            if lane not in _IMPL_LANES or not suffix:
                continue
            model = suffix if lane == "claude" else _codex_model_id(suffix)
            return lane, model
    return None, None


def resolve(lane: str, role: str = "implementer", tier: str = "1",
            project: str | None = None, effort_override: str | None = None,
            model_override: str | None = None) -> dict[str, Any]:
    """Return {provider, model, model_id, effort, max_budget_usd, selection_mode,
    selection_reason} for a worker on `lane`. Only the claude lane carries a real model.
    `effort_override` (from an `effort:` label or `--effort` flag) and `model_override` (from a
    `review:<model>` or `impl:<lane>-<model>` label) are per-dispatch intent and beat
    env/policy/defaults. `model_override` also pins a self-driving lane's model (e.g. codex)."""
    role = role if role in _ROLE_DEFAULT else "implementer"

    # Self-driving lanes manage their own model; relay injects nothing UNLESS an
    # `impl:<lane>-<model>` label pinned one (model_override) — then we hand that id to the lane's
    # own harness (e.g. codex `-c model=`) and record the reasoning effort alongside it.
    if lane != "claude":
        model_id = model_override or ""
        eff = (effort_override.lower() if effort_override
               and effort_override.lower() in _EFFORT_LEVELS else "")
        if model_id and not eff:
            eff = "medium"        # match codex's own default reasoning effort when we pin a model
        return {
            "provider": _LANE_PROVIDER.get(lane, lane),
            "model": model_id, "model_id": model_id, "effort": eff,
            "max_budget_usd": None,
            "selection_mode": "override" if model_id else "lane",
            "selection_reason": (f"impl model override ({lane} {model_id})" if model_id
                                 else f"{lane} lane uses its own model"),
        }

    base = dict(_ROLE_DEFAULT[role])
    reason = f"default {role}"
    # Tier-2 reviewer reads sensitive code at higher effort (spec §10.2 / models.yml escalation).
    if str(tier) == "2" and role == "reviewer":
        base["effort"] = "high"
        reason = "tier-2 reviewer (high effort)"

    mode = "auto"
    # global operator policy first, then the rare per-repo override on top.
    gpol = _load_policy_file(_global_policy_path(), role, tier)
    if gpol:
        base.update({k: v for k, v in gpol.items() if v})
        mode, reason = "policy", f"global policy ({role})"
    rpol = _load_policy_file(_repo_policy_path(project), role, tier)
    if rpol:
        base.update({k: v for k, v in rpol.items() if v})
        mode, reason = "policy", f"repo policy ({role})"

    # Operator env override wins over file + defaults.
    if os.getenv("RELAY_CLAUDE_MODEL"):
        base["model"] = os.environ["RELAY_CLAUDE_MODEL"]
        mode, reason = "override", "RELAY_CLAUDE_MODEL"
    if os.getenv("RELAY_CLAUDE_EFFORT"):
        base["effort"] = os.environ["RELAY_CLAUDE_EFFORT"]
        mode = "override"
    # per-dispatch effort (effort: label / --effort flag) is the most specific — it wins.
    if effort_override and effort_override.lower() in _EFFORT_LEVELS:
        base["effort"] = effort_override.lower()
        mode, reason = "override", f"effort override ({effort_override.lower()})"
    # per-issue reviewer model (review:<model> label) — explicit intent, beats env/policy.
    if model_override:
        base["model"] = model_override
        mode, reason = "override", f"model override ({model_override})"

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


def codex_flags(spec: dict[str, Any] | None) -> str:
    """Render `codex exec -c` overrides for a resolved spec; '' when no model is pinned (so codex
    falls back to its own ~/.codex/config.toml default). Mirrors claude_flags for the codex lane —
    only an `impl:codex-<model>` label makes resolve() set a model_id here."""
    if not spec:
        return ""
    model = spec.get("model_id") or spec.get("model")
    if not model:
        return ""
    parts = [f'-c model="{model}"']
    if spec.get("effort"):
        parts.append(f'-c model_reasoning_effort="{spec["effort"]}"')
    return " " + " ".join(parts)
