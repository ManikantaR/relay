"""
relay_finish.py — classify a worker's exit and write its terminal status line.

Invoked by the spawn wrapper after the harness process exits (any lane, any backend).
Keeping exit classification HERE — one small, testable place — means completion and
rate-limit detection never depend on the agent cooperatively writing DONE itself.

    DONE          rc == 0
    RATE_LIMITED  the log tail shows a usage-limit signature (-> watchdog probes & resumes)
    ERROR exit=N  rc != 0 and not a rate limit (-> watchdog escalates to the owner)
"""
from __future__ import annotations
import os, re, sys
from datetime import datetime, timezone
from pathlib import Path

DATA = Path(os.getenv("DATA_DIR", "data"))
RATE = re.compile(r"rate.?limit|usage limit|session limit|limit reached|quota|\b429\b|"
                  r"too many requests|overloaded|resets \d", re.IGNORECASE)


def classify(task: str, rc: str) -> str:
    log = DATA / task / "worker.log"
    tail = log.read_text(errors="ignore")[-4000:] if log.exists() else ""
    if rc != "0" and RATE.search(tail):
        return "RATE_LIMITED"
    return "DONE" if rc == "0" else f"ERROR exit={rc}"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: relay_finish.py <task> <rc>", file=sys.stderr)
        return 2
    task, rc = argv[0], str(argv[1])
    line = classify(task, rc)
    status = DATA / task / "status.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    with status.open("a", encoding="utf-8") as f:
        f.write(f"{line} {datetime.now(timezone.utc).isoformat()}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
