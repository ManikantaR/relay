"""
relay_repos.py — the machine-local repo registry.

The set of repos Relay pulls issues from used to live only in `RELAY_PROJECTS` (a comma list
of `repo=path` in the gitignored data/captain.<profile>.md). Editing an env line to onboard a
repo doesn't scale to dozens of repos and can't be driven from the VS Code UI. This module
holds that list in a real file instead:

    $RELAY_REPOS_FILE, else $XDG_CONFIG_HOME/relay/repos.json, else ~/.config/relay/repos.json

— one file per machine, the same XDG shape as the global model policy (~/.config/relay/models.yml).

Format (JSON so the control plane stays stdlib-only; PyYAML is optional and only used when the
override path ends in .yml/.yaml):

    {"repos": [{"name": "owner/repo", "path": "/abs/worktree", "board": "github"}, ...]}

Back-compat: when the file is absent we DERIVE the list from RELAY_PROJECTS (or a single
GITHUB_REPO + RELAY_PROJECT), so nothing breaks before the operator runs `relay repo add`.
`seed_from_env()` writes that derived list out once, turning the env into a real registry.

This pairs with issue #1 (Repo registry + `relay repo add`). `board` is carried through for the
future TFS/github split; today everything is "github".
"""
from __future__ import annotations
import json
import os
from pathlib import Path


def registry_path() -> Path:
    """$RELAY_REPOS_FILE, else $XDG_CONFIG_HOME/relay/repos.json, else ~/.config/relay/repos.json."""
    override = os.getenv("RELAY_REPOS_FILE")
    if override:
        return Path(override).expanduser()
    base = os.getenv("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(base) / "relay" / "repos.json"


def _is_yaml(path: Path) -> bool:
    return path.suffix.lower() in (".yml", ".yaml")


def _normalize(entry: dict) -> dict | None:
    """A registry entry needs at least a name; path/board default sensibly."""
    name = str(entry.get("name") or entry.get("repo") or "").strip()
    if not name:
        return None
    return {
        "name": name,
        "path": str(entry.get("path") or ".").strip() or ".",
        "board": str(entry.get("board") or "github").strip() or "github",
    }


def _read_file(path: Path) -> list[dict]:
    """Parse the registry file into normalized entries. JSON always; YAML only if PyYAML is here."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    data: object
    if _is_yaml(path):
        try:
            import yaml  # type: ignore
        except Exception:
            return []                       # YAML file but no PyYAML — degrade to env, don't crash
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or "{}")
    raw = data.get("repos", []) if isinstance(data, dict) else (data or [])
    out = []
    for e in raw:
        if isinstance(e, dict):
            n = _normalize(e)
            if n:
                out.append(n)
    return out


def _from_env() -> list[dict]:
    """The legacy source: RELAY_PROJECTS (`repo=path,repo=path`), else GITHUB_REPO + RELAY_PROJECT."""
    raw = os.getenv("RELAY_PROJECTS", "").strip()
    out: list[dict] = []
    if raw:
        for pair in raw.split(","):
            if "=" in pair:
                repo, path = pair.split("=", 1)
                n = _normalize({"name": repo, "path": path})
                if n:
                    out.append(n)
        return out
    repo = os.getenv("GITHUB_REPO", "").strip()
    if repo:
        n = _normalize({"name": repo, "path": os.getenv("RELAY_PROJECT", "") or "."})
        if n:
            out.append(n)
    return out


def load() -> list[dict]:
    """The active registry. Precedence: the registry FILE if it exists, else the env fallback."""
    path = registry_path()
    if path.exists():
        return _read_file(path)
    return _from_env()


def projects() -> list[tuple[str, str]]:
    """(board-repo, project-path) pairs — the shape relay_control's dispatcher already consumes."""
    return [(e["name"], e["path"]) for e in load()]


def save(entries: list[dict]) -> Path:
    """Write the registry, creating the parent dir. Mirrors the input format (JSON, or YAML if the
    path is .yml/.yaml and PyYAML is installed — otherwise falls back to writing JSON)."""
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [n for e in entries if (n := _normalize(e))]
    payload = {"repos": normalized}
    if _is_yaml(path):
        try:
            import yaml  # type: ignore
            path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
            return path
        except Exception:
            pass                            # no PyYAML — persist as JSON so `add` still works
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def seed_from_env() -> list[dict]:
    """If no registry file exists yet, materialize one from RELAY_PROJECTS/GITHUB_REPO so the env
    becomes a real, editable registry. Idempotent: a no-op once the file is present."""
    if registry_path().exists():
        return load()
    seeded = _from_env()
    if seeded:
        save(seeded)
    return seeded


def add(name: str, path: str | None = None, board: str = "github") -> list[dict]:
    """Register (or update) a repo. Seeds from env first so an existing env list isn't clobbered."""
    entries = seed_from_env() if not registry_path().exists() else load()
    entry = _normalize({"name": name, "path": path or ".", "board": board})
    if not entry:
        raise ValueError("repo name is required (owner/name)")
    entries = [e for e in entries if e["name"].lower() != entry["name"].lower()]
    entries.append(entry)
    save(entries)
    return entries


def remove(name: str) -> list[dict]:
    """Deregister a repo by owner/name (case-insensitive). Seeds from env first if needed."""
    entries = seed_from_env() if not registry_path().exists() else load()
    kept = [e for e in entries if e["name"].lower() != name.strip().lower()]
    save(kept)
    return kept
