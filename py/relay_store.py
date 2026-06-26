"""
relay_store.py — v2 session/event persistence with JSON-on-disk + SQLite index.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import relay_schema as schema
import relay_state as state


class Store:
    def __init__(self, data_dir: str | Path | None = None) -> None:
        self.data_dir = Path(data_dir or os.getenv("DATA_DIR", "data"))
        self.sessions_dir = self.data_dir / "sessions"
        self.queue_dir = self.data_dir / "queue"
        self.cache_dir = self.data_dir / "cache"
        self.db_path = self.data_dir / "relay.db"
        self._init_layout()

    def _init_layout(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists sessions (
                  session_id text primary key,
                  task_id text not null,
                  repo text not null,
                  project_path text not null,
                  role text not null,
                  tier text not null,
                  state text not null,
                  lane text not null,
                  provider text not null,
                  model text not null,
                  effort text not null,
                  selection_mode text not null,
                  selection_reason text not null,
                  review_round integer not null,
                  max_review_rounds integer not null,
                  created_at text not null,
                  updated_at text not null
                );
                create table if not exists events (
                  event_id text primary key,
                  session_id text not null,
                  sequence integer not null,
                  type text not null,
                  actor text not null,
                  timestamp text not null,
                  summary text not null,
                  payload_json text not null,
                  foreign key(session_id) references sessions(session_id)
                );
                create index if not exists idx_events_session_seq on events(session_id, sequence);
                """
            )
        self.rebuild_index()

    def session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / session_id

    def session_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "session.json"

    def events_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "events.jsonl"

    def transcript_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "transcript.log"

    def evidence_dir(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "evidence"

    def next_sequence(self, session_id: str) -> int:
        rows = schema.read_jsonl(self.events_path(session_id))
        return (rows[-1]["sequence"] + 1) if rows else 1

    def create_session(self, doc: dict[str, Any]) -> dict[str, Any]:
        errs = schema.validate_session(doc)
        if errs:
            raise ValueError("; ".join(errs))
        sdir = self.session_dir(doc["session_id"])
        sdir.mkdir(parents=True, exist_ok=False)
        self.evidence_dir(doc["session_id"]).mkdir(exist_ok=True)
        self.transcript_path(doc["session_id"]).touch()
        (sdir / doc.get("brief_path", "brief.md")).touch()
        schema.write_json(self.session_path(doc["session_id"]), doc)
        self._upsert_session_row(doc)
        ev = schema.make_event(doc["session_id"], "session_created", "relay", "session created",
                               {"state": doc["state"]}, sequence=1)
        self.append_event(doc["session_id"], ev)
        return doc

    def get_session(self, session_id: str) -> dict[str, Any]:
        return schema.read_json(self.session_path(session_id))

    def list_sessions(self) -> list[dict[str, Any]]:
        out = []
        for p in sorted(self.sessions_dir.glob("*/session.json")):
            out.append(schema.read_json(p))
        return out

    def append_event(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        errs = schema.validate_event(event)
        if errs:
            raise ValueError("; ".join(errs))
        schema.append_jsonl(self.events_path(session_id), event)
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into events
                (event_id, session_id, sequence, type, actor, timestamp, summary, payload_json)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["event_id"], session_id, event["sequence"], event["type"], event["actor"],
                    event["timestamp"], event["summary"], json.dumps(event["payload"], sort_keys=True),
                ),
            )
        return event

    def timeline(self, session_id: str) -> list[dict[str, Any]]:
        return schema.read_jsonl(self.events_path(session_id))

    def update_session(self, session_id: str, mutate) -> dict[str, Any]:
        doc = self.get_session(session_id)
        mutate(doc)
        doc["updated_at"] = schema.now_iso()
        errs = schema.validate_session(doc)
        if errs:
            raise ValueError("; ".join(errs))
        schema.write_json(self.session_path(session_id), doc)
        self._upsert_session_row(doc)
        return doc

    def transition_session(self, session_id: str, to_state: str, actor: str = "relay",
                           reason: str = "") -> dict[str, Any]:
        before = self.get_session(session_id)
        trans = state.transition(before["state"], to_state, reason)

        def mutate(doc: dict[str, Any]) -> None:
            doc["state"] = trans.to
            if trans.to == "running" and not doc.get("started_at"):
                doc["started_at"] = schema.now_iso()
            if trans.to in {"done", "terminated"}:
                doc["ended_at"] = schema.now_iso()

        after = self.update_session(session_id, mutate)
        ev = schema.make_event(
            session_id, "state_changed", actor, f"{trans.frm}->{trans.to}",
            {"from": trans.frm, "to": trans.to, "reason": reason},
            sequence=self.next_sequence(session_id),
        )
        self.append_event(session_id, ev)
        return after

    def add_nudge(self, session_id: str, actor: str, nudge_type: str, message: str,
                  attachments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if nudge_type not in schema.NUDGE_TYPES:
            raise ValueError(f"invalid nudge type {nudge_type}")
        current = self.get_session(session_id)
        if current["state"] == "running":
            self.transition_session(session_id, "paused", actor="relay", reason="operator nudge")
        seq = self.next_sequence(session_id)
        ev = schema.make_event(
            session_id, "operator_nudge", actor, message,
            {"nudge_type": nudge_type, "attachments": attachments or []}, sequence=seq,
        )
        self.append_event(session_id, ev)
        ack = schema.make_event(
            session_id, "worker_acknowledged", "relay", "nudge queued for acknowledgement",
            {"nudge_type": nudge_type}, sequence=seq + 1,
        )
        self.append_event(session_id, ack)
        return self.get_session(session_id)

    def _upsert_session_row(self, doc: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into sessions
                (session_id, task_id, repo, project_path, role, tier, state, lane, provider,
                 model, effort, selection_mode, selection_reason, review_round,
                 max_review_rounds, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["session_id"], doc["task_id"], doc["repo"], doc["project_path"],
                    doc["role"], doc["tier"], doc["state"], doc["lane"], doc["provider"],
                    doc["model"], doc["effort"], doc["selection_mode"], doc["selection_reason"],
                    doc["review_round"], doc["max_review_rounds"], doc["created_at"],
                    doc["updated_at"],
                ),
            )

    def rebuild_index(self) -> None:
        """Rebuild SQLite from canonical disk artifacts.

        This keeps JSON-on-disk as the source of truth and lets the DB be replaced or repaired
        without losing session history.
        """
        with self._connect() as conn:
            conn.execute("delete from events")
            conn.execute("delete from sessions")
        for p in sorted(self.sessions_dir.glob("*/session.json")):
            doc = schema.read_json(p)
            errs = schema.validate_session(doc)
            if errs:
                continue
            self._upsert_session_row(doc)
            for event in schema.read_jsonl(self.events_path(doc["session_id"])):
                errs = schema.validate_event(event)
                if errs:
                    continue
                with self._connect() as conn:
                    conn.execute(
                        """
                        insert or replace into events
                        (event_id, session_id, sequence, type, actor, timestamp, summary, payload_json)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event["event_id"], doc["session_id"], event["sequence"], event["type"],
                            event["actor"], event["timestamp"], event["summary"],
                            json.dumps(event["payload"], sort_keys=True),
                        ),
                    )
