"""
relay_verify.py — pure helpers for the verifier (review) loop.

The control plane (relay_control) drives the process launches; this module holds the parts
that are pure and testable: the reviewer brief, parsing the reviewer's verdict, the
round/cap decision, appending feedback to the implementer brief, and building the
decision-log PR comment. No subprocesses, no board calls — just data in, data out.

Loop shape (driven by relay_control on each worker DONE):
  implementer DONE + evidence ok  -> spawn reviewer (read-only, Opus) in the same worktree
  reviewer DONE                   -> parse evidence/review.json:
      approved                     -> finalize the PR (+ decision log)
      changes (rounds < cap)       -> append feedback to brief, respawn implementer
      changes (rounds == cap)      -> file PR + needs_decision (your call)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_APPROVE = {"approved", "approve", "approved_with_nits", "lgtm", "pass", "passed", "ok"}
_CHANGES = {"changes_requested", "changes", "request_changes", "reject", "rejected", "fail",
            "failed", "needs_changes"}


def render_review_brief(title: str, item: str, tier: str, evidence: str, base: str = "main",
                        round_no: int = 1) -> str:
    """The reviewer's brief. Read-only: it inspects the implementer's committed diff and the
    evidence bundle and writes a structured verdict to evidence/review.json. It must NOT edit
    code — any stray edits are discarded by the control plane before the next round."""
    return f"""# Review: {title} (#{item}, tier-{tier}) — round {round_no}

You are a **read-only reviewer**. Do NOT edit, create, or delete code. Do NOT commit, push,
or run `gh`. Your only output is a verdict file.

## What to review
The implementer committed work on this branch. Inspect it:
- `git diff {base}...HEAD` — the full committed diff.
- `git log {base}..HEAD --stat` — what changed.
- the evidence bundle in `{evidence}/` — `summary.md`, `pytest.txt`, screenshots, and
  `decisions.md` (what the implementer tried and ruled out), if present.

Review for correctness, missing edge cases, security, and whether the evidence actually
backs the claims. Tier-2 paths deserve line-by-line scrutiny.

## Your only output — write exactly this file
Write **{evidence}/review.json** (and nothing else) as:

```json
{{
  "verdict": "approved" | "changes_requested",
  "summary": "one paragraph: the headline judgement",
  "comments": [
    {{"path": "backend/storage.py", "line": 184, "message": "specific, actionable change"}}
  ]
}}
```

- `approved`: the work is correct and the evidence supports it. `comments` may be empty.
- `changes_requested`: list concrete, line-anchored changes. Be specific — the implementer
  acts on these verbatim next round, with no other context.

When `review.json` is written, you are done. Do not modify anything else.
"""


def parse_review(evidence_dir: Path) -> tuple[str, list[dict], str]:
    """Read evidence/review.json -> (verdict, comments, summary).
    verdict is normalized to 'approved' | 'changes_requested' | 'unknown'."""
    p = Path(evidence_dir) / "review.json"
    if not p.exists():
        return "unknown", [], ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return "unknown", [], ""
    raw = str(data.get("verdict", "")).strip().lower()
    if raw in _APPROVE:
        verdict = "approved"
    elif raw in _CHANGES:
        verdict = "changes_requested"
    else:
        verdict = "unknown"
    comments = data.get("comments") or []
    if not isinstance(comments, list):
        comments = []
    return verdict, comments, str(data.get("summary", "")).strip()


def review_decision(verdict: str, completed_rounds: int, cap: int = 3) -> str:
    """What to do after a reviewer run. completed_rounds counts the run that just finished.
    Returns 'finalize' | 'respawn' | 'needs_decision'."""
    if verdict == "changes_requested":
        return "needs_decision" if completed_rounds >= cap else "respawn"
    # approved, or unknown (reviewer produced no usable verdict — don't block the work).
    return "finalize"


def append_feedback(brief_path: Path, round_no: int, comments: list[dict]) -> None:
    """Append a review-feedback section to the implementer brief so a respawn addresses it."""
    brief_path = Path(brief_path)
    existing = brief_path.read_text(encoding="utf-8") if brief_path.exists() else ""
    lines = [existing.rstrip(), "", f"## Review feedback — round {round_no}", "",
             "The reviewer requested these changes. Address each, update the evidence bundle,",
             "and commit. Then stop — the reviewer re-checks.", ""]
    if not comments:
        lines.append("- (no line-anchored comments; see the reviewer summary)")
    for c in comments:
        loc, line, msg = c.get("path", ""), c.get("line"), str(c.get("message", "")).strip()
        if loc and line is not None:
            lines.append(f"- `{loc}:{line}` {msg}")
        elif loc:
            lines.append(f"- `{loc}` {msg}")
        else:
            lines.append(f"- {msg}")
    brief_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def decision_log(evidence_dir: Path) -> str:
    """Build the decision-log PR comment from the implementer's evidence. Prefer an explicit
    decisions.md; otherwise pull decision-ish lines out of summary.md. '' when there's none."""
    d = Path(evidence_dir)
    dec = d / "decisions.md"
    if dec.exists():
        text = dec.read_text(encoding="utf-8").strip()
        if text:
            return f"## Decision log\n\n{text}\n\n_— captured by the implementer, surfaced by relay._"
    summary = d / "summary.md"
    if summary.exists():
        hits = [ln.strip() for ln in summary.read_text(encoding="utf-8").splitlines()
                if any(k in ln.lower() for k in ("ruled out", "decided", "decision", "trade-off",
                                                 "tradeoff", "alternativ", "rejected"))]
        if hits:
            body = "\n".join(f"- {h.lstrip('-* ')}" for h in hits)
            return f"## Decision log\n\n{body}\n\n_— extracted from summary.md by relay._"
    return ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
