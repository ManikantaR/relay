"""
relay_daemon.py — initial v2 daemon scaffold with REST endpoints.

This is intentionally small: it proves the runtime contract shape without replacing the
existing CLI/control-plane yet.
"""
from __future__ import annotations

import json
import logging
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import relay_schema as schema
from relay_store import Store

log = logging.getLogger("relayd")


def _json(handler: BaseHTTPRequestHandler, code: int, payload) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class RelayHandler(BaseHTTPRequestHandler):
    server_version = "Relayd/0.1"

    @property
    def store(self) -> Store:
        return self.server.store  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def _body(self):
        n = int(self.headers.get("Content-Length", "0") or "0")
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            return _json(self, HTTPStatus.OK, {"status": "ok"})
        if path == "/api/sessions":
            return _json(self, HTTPStatus.OK, {"sessions": self.store.list_sessions()})
        if path.startswith("/api/sessions/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3:
                session_id = parts[2]
                try:
                    return _json(self, HTTPStatus.OK, self.store.get_session(session_id))
                except FileNotFoundError:
                    return _json(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
            if len(parts) == 4 and parts[3] == "timeline":
                session_id = parts[2]
                try:
                    return _json(self, HTTPStatus.OK, {"events": self.store.timeline(session_id)})
                except FileNotFoundError:
                    return _json(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
        return _json(self, HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/dispatch":
                doc = schema.default_session(
                    task_id=body["task_id"],
                    repo=body.get("repo", ""),
                    project_path=body.get("project_path", "."),
                    role=body.get("role", "implementer"),
                    tier=str(body.get("tier", "1")),
                    lane=body.get("lane", ""),
                    provider=body.get("provider", ""),
                    model=body.get("model", ""),
                    effort=body.get("effort", "medium"),
                    selection_mode=body.get("selection_mode", "auto"),
                    selection_reason=body.get("selection_reason", "manual dispatch"),
                    alternatives=body.get("alternatives", []),
                    max_review_rounds=int(body.get("max_review_rounds", 3)),
                )
                created = self.store.create_session(doc)
                return _json(self, HTTPStatus.CREATED, created)

            if path.startswith("/api/sessions/"):
                parts = [p for p in path.split("/") if p]
                if len(parts) == 4:
                    session_id, action = parts[2], parts[3]
                    if action == "pause":
                        session = self.store.transition_session(
                            session_id, "paused", actor="owner", reason=body.get("reason", "manual pause")
                        )
                        return _json(self, HTTPStatus.OK, session)
                    if action == "resume":
                        session = self.store.transition_session(
                            session_id, "running", actor="owner", reason=body.get("reason", "manual resume")
                        )
                        return _json(self, HTTPStatus.OK, session)
                    if action == "nudge":
                        session = self.store.add_nudge(
                            session_id=session_id,
                            actor=body.get("actor", "owner"),
                            nudge_type=body.get("nudge_type", "goal_correction"),
                            message=body["message"],
                            attachments=body.get("attachments", []),
                        )
                        return _json(self, HTTPStatus.OK, session)
            return _json(self, HTTPStatus.NOT_FOUND, {"error": "not found"})
        except FileNotFoundError:
            return _json(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
        except KeyError as e:
            return _json(self, HTTPStatus.BAD_REQUEST, {"error": f"missing field {e.args[0]}"})
        except ValueError as e:
            return _json(self, HTTPStatus.BAD_REQUEST, {"error": str(e)})


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    host = os.getenv("RELAYD_HOST", "127.0.0.1")
    port = int(os.getenv("RELAYD_PORT", "8787"))
    store = Store()
    server = ThreadingHTTPServer((host, port), RelayHandler)
    server.store = store  # type: ignore[attr-defined]
    log.info("relayd listening on http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    serve()
