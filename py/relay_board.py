"""
relay_board.py — the board interface and its two adapters.

Control-plane-native: ONLY this module (running in the trusted Python orchestrator) holds
board credentials and mutates the board. The agent never imports this with write access.

- GitHubBoard: implemented via the `gh` CLI (personal/home) — no PAT needed.
- TFSBoard: SKELETON. You fill the TODOs at work by calling your EXISTING PowerShell
  scripts (the ones that already pull TFS tickets, file PRs, post comments). You are NOT
  reimplementing TFS — you are translating between Relay's interface and your scripts.

Pickup contract (both adapters): only return tickets tagged `agent-ready`, not yet
`agent-wip`, within the area fence (work) or the repo (home). Never auto-dispatch.
"""
from __future__ import annotations
import json, os, subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Ticket:
    id: str
    title: str
    body: str
    tier: str            # "1" | "2"
    labels: list[str]


class Board(ABC):
    @abstractmethod
    def pull_ready(self) -> list[Ticket]: ...
    @abstractmethod
    def apply_label(self, ticket_id: str, label: str) -> None: ...
    @abstractmethod
    def remove_label(self, ticket_id: str, label: str) -> None: ...
    @abstractmethod
    def file_pr(self, branch: str, title: str, body: str, tier: str) -> str: ...
    @abstractmethod
    def comment_pr(self, pr_id: str, text: str) -> None: ...


# ----------------------------- GitHub (home) — implemented -----------------------------

class GitHubBoard(Board):
    """Wraps the GitHub CLI (`gh`). Uses your existing `gh auth login` — no PAT to manage.
    Requires `gh` installed and authenticated (run `gh auth status` to check)."""
    def __init__(self, repo: str | None = None) -> None:
        self.repo = repo or os.environ["GITHUB_REPO"]      # e.g. "ManikantaR/MoneyPulse"

    def _gh(self, *args: str) -> str:
        cmd = ["gh", *args, "--repo", self.repo]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    def pull_ready(self) -> list[Ticket]:
        raw = self._gh("issue", "list", "--label", "agent-ready", "--state", "open",
                       "--json", "number,title,body,labels")
        out: list[Ticket] = []
        for it in json.loads(raw or "[]"):
            labels = [l["name"] for l in it.get("labels", [])]
            if "agent-wip" in labels:
                continue
            tier = "2" if "tier-2" in labels else "1"
            out.append(Ticket(str(it["number"]), it["title"], it.get("body") or "", tier, labels))
        return out

    def apply_label(self, ticket_id: str, label: str) -> None:
        self._gh("issue", "edit", ticket_id, "--add-label", label)

    def remove_label(self, ticket_id: str, label: str) -> None:
        self._gh("issue", "edit", ticket_id, "--remove-label", label)

    def file_pr(self, branch: str, title: str, body: str, tier: str) -> str:
        out = self._gh("pr", "create", "--head", branch, "--base", "main",
                       "--title", title, "--body", body)
        return out.strip().rsplit("/", 1)[-1]              # gh prints the PR URL; take the number

    def comment_pr(self, pr_id: str, text: str) -> None:
        self._gh("pr", "comment", pr_id, "--body", text)

    def pull_review(self) -> list[dict]:
        """Open PRs awaiting the owner (the kanban Review column). Matches relay-opened PRs by
        their `relay/` branch (robust) or the agent-review label. Not on the ABC — optional."""
        raw = self._gh("pr", "list", "--state", "open",
                       "--json", "number,title,labels,url,headRefName")
        out = []
        for it in json.loads(raw or "[]"):
            labels = [l["name"] for l in it.get("labels", [])]
            if not (it.get("headRefName", "").startswith("relay/") or "agent-review" in labels):
                continue
            out.append({"repo": self.repo, "id": str(it["number"]), "title": it["title"],
                        "tier": "2" if "tier-2" in labels else "1", "url": it.get("url", "")})
        return out


# --------------------- Azure DevOps / TFS (work) — SKELETON: FILL AT WORK ---------------------

class TFSBoard(Board):
    """
    Wrap your EXISTING PowerShell scripts. Relay does NOT speak the TFS API and does NOT
    handle the PAT — your scripts already read it from their own configured env file.
    Relay just calls the scripts and translates the results.

    Env (set in data/captain.work.md, gitignored):
        TFS_URL        your TFS/Azure DevOps Server collection URL
        RELAY_AREA     area path that fences pickup
        RELAY_TFS_SCRIPTS   path to your scripts (default ./tfs-scripts)
    Note: no PAT here on purpose — your scripts own auth.
    """
    def __init__(self) -> None:
        self.url = os.environ.get("TFS_URL", "")
        self.area = os.getenv("RELAY_AREA", "")
        self.scripts = os.getenv("RELAY_TFS_SCRIPTS", "./tfs-scripts")

    def _ps(self, script: str, *args: str) -> str:
        """Run a PowerShell script and return stdout. The script handles its own auth/PAT."""
        cmd = ["pwsh", "-NoProfile", "-File", f"{self.scripts}/{script}", *args]
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout

    def pull_ready(self) -> list[Ticket]:
        # TODO(work): call your ticket-pull script, fenced to agent-ready + RELAY_AREA.
        #   Recommended: have the script emit JSON so parsing is trivial:
        #   raw = self._ps("Get-Tickets.ps1", "-Area", self.area, "-Tag", "agent-ready")
        #   return [Ticket(t["id"], t["title"], t["body"], "2" if "tier-2" in t["tags"] else "1", t["tags"])
        #           for t in json.loads(raw) if "agent-wip" not in t["tags"]]
        raise NotImplementedError("fill pull_ready() with your Get-Tickets.ps1 call")

    def apply_label(self, ticket_id: str, label: str) -> None:
        # TODO(work): self._ps("Set-TicketTag.ps1", "-Id", ticket_id, "-Tag", label)
        raise NotImplementedError("fill apply_label() with your tag script")

    def remove_label(self, ticket_id: str, label: str) -> None:
        # TODO(work): self._ps("Remove-TicketTag.ps1", "-Id", ticket_id, "-Tag", label)
        raise NotImplementedError("fill remove_label() with your tag script")

    def file_pr(self, branch: str, title: str, body: str, tier: str) -> str:
        # TODO(work): raw = self._ps("New-PR.ps1", "-Branch", branch, "-Title", title, "-Body", body)
        #   return json.loads(raw)["prId"]
        raise NotImplementedError("fill file_pr() with your New-PR.ps1 call")

    def comment_pr(self, pr_id: str, text: str) -> None:
        # TODO(work): self._ps("Add-PRComment.ps1", "-PrId", pr_id, "-Text", text)
        raise NotImplementedError("fill comment_pr() with your Add-PRComment.ps1 call")


def get_board(repo: str | None = None) -> Board:
    # work = one TFS board; personal = a GitHub board per repo (multi-repo registry).
    return TFSBoard() if os.getenv("RELAY_PROFILE") == "work" else GitHubBoard(repo)
