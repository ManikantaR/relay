"""
relay_lanes.py — lane availability + failover resolution (AGENTS.md §12).

WHICH lanes exist is a property of the environment, not the repo: `RELAY_LANES` is an
explicit ordered allowlist (home permissive, work = org-sanctioned only), validated by a
cheap auth-check cached ~daily. Resolution honors a ticket's lane preference, steps down the
ladder when a lane is unavailable OR rate-limited, forces Tier-2 to claude (never downgrades),
and at work HOLDS an explicit request for an unsanctioned lane rather than silently switching.
Every substitution is announced by the caller (never a silent degrade).
"""
from __future__ import annotations
import json, os, shutil, subprocess, time
from pathlib import Path

LANES = ("claude", "agy", "copilot", "codex")
BIN = {"claude": "claude", "agy": "agy", "copilot": "copilot", "codex": "codex"}
_RATE = ("rate limit", "ratelimit", "quota", "usage limit", "session limit", "limit reached",
         "429", "too many requests", "overloaded")


def configured_lanes() -> list[str]:
    """Ordered allowlist from RELAY_LANES (home: copilot,agy,codex,claude; work: claude)."""
    raw = os.getenv("RELAY_LANES", os.getenv("RELAY_LANE", "claude"))
    out = [l.strip() for l in raw.split(",") if l.strip() in LANES]
    return out or ["claude"]


def strict() -> bool:
    """Work governance: hold explicit requests for unsanctioned lanes instead of substituting."""
    return os.getenv("RELAY_STRICT_LANES", "") not in ("", "0", "false")


def _cache_path() -> Path:
    return Path(os.getenv("DATA_DIR", "data")) / ".lanes.json"


def installed(lane: str) -> bool:
    return shutil.which(BIN.get(lane, lane)) is not None


def auth_probe(lane: str) -> bool:
    """Installed AND authed here? A rate-limit at probe time still counts as available
    (the lane works, it's just capped). Best-effort; never raises."""
    if not installed(lane):
        return False
    cmds = {
        "claude": ["claude", "--print", "ok"],
        "agy": ["agy", "-p", "ok"],
        "copilot": ["copilot", "--allow-all-tools", "-p", "ok"],
        "codex": ["codex", "exec", "ok"],
    }
    try:
        r = subprocess.run(cmds[lane], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=int(os.getenv("RELAY_PROBE_TIMEOUT", "45")))
    except Exception:
        return False
    if r.returncode == 0:
        return True
    blob = (r.stdout + r.stderr).lower()
    return any(s in blob for s in _RATE)


def available_lanes(refresh: bool = False, ttl: int | None = None) -> list[str]:
    """Configured ∩ installed ∩ authed, in configured order. Cached ~daily in data/.lanes.json."""
    ttl = ttl if ttl is not None else int(os.getenv("RELAY_LANES_TTL", "86400"))
    configured = configured_lanes()
    if not refresh:
        cached = _read_cache(ttl)
        if cached is not None:
            return [l for l in configured if l in cached]
    live = [l for l in configured if auth_probe(l)]
    _write_cache(live)
    return live


def _read_cache(ttl: int):
    try:
        d = json.loads(_cache_path().read_text())
        if time.time() - d["at"] <= ttl:
            return set(d["lanes"])
    except Exception:
        pass
    return None


def _write_cache(lanes: list[str]) -> None:
    try:
        p = _cache_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": time.time(), "lanes": lanes}))
    except Exception:
        pass


def lane_preference(labels: list[str], override: str | None = None) -> tuple[str, bool]:
    """Return (preferred_lane, explicit). Override or a `lane:<x>` label is explicit; otherwise
    the env's top-of-ladder default (not explicit)."""
    if override in LANES:
        return override, True
    for n in labels:
        if n.startswith("lane:") and n.split(":", 1)[1] in LANES:
            return n.split(":", 1)[1], True
    return configured_lanes()[0], False


def resolve_lane(preferred: str, explicit: bool, tier: str, available: list[str],
                 tried=(), is_strict: bool | None = None) -> tuple[str | None, str]:
    """Resolve to an actual lane (or None = HOLD/WAIT) with a reason.

    - Tier-2 forces `claude`; if claude is unavailable or already tried -> None (WAIT, never
      downgrade to a cheaper model).
    - Otherwise honor `preferred` if available & untried, else the next available untried lane
      in ladder order.
    - Strict (work) + explicit request for an unavailable lane -> None (HOLD), not substitute.
    - All lanes tried -> None (every lane capped; the watchdog idle-waits).
    """
    is_strict = strict() if is_strict is None else is_strict
    tried = set(tried)

    if tier == "2":
        if "claude" in available and "claude" not in tried:
            return "claude", ("preferred" if preferred == "claude" else "tier2-forced-claude")
        return None, "tier2-claude-unavailable"

    fresh = [l for l in available if l not in tried]
    if not fresh:
        return None, "all-lanes-exhausted"
    if preferred in fresh:
        return preferred, "preferred"
    if is_strict and explicit:
        return None, f"strict-hold:{preferred}-unsanctioned"
    return fresh[0], f"substitute:{preferred}->{fresh[0]}"
