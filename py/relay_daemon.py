"""
relay_daemon.py — initial v2 daemon scaffold with REST endpoints.

This is intentionally small: it proves the runtime contract shape without replacing the
existing CLI/control-plane yet.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import relay_schema as schema
import relay_review as review
import relay_bridge as bridge
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
        code, payload = handle_request("GET", urlparse(self.path).path, {}, self.store)
        return _json(self, code, payload)

    def do_POST(self) -> None:
        try:
            body = self._body()
            code, payload = handle_request("POST", urlparse(self.path).path, body, self.store)
            return _json(self, code, payload)
        except FileNotFoundError:
            return _json(self, HTTPStatus.NOT_FOUND, {"error": "session not found"})
        except KeyError as e:
            return _json(self, HTTPStatus.BAD_REQUEST, {"error": f"missing field {e.args[0]}"})
        except ValueError as e:
            return _json(self, HTTPStatus.BAD_REQUEST, {"error": str(e)})


def handle_request(method: str, path: str, body: dict, store: Store) -> tuple[int, dict]:
    if method == "GET":
        if path == "/api/health":
            return HTTPStatus.OK, {"status": "ok"}
        if path == "/api/sessions":
            return HTTPStatus.OK, {"sessions": store.list_sessions()}
        if path.startswith("/api/sessions/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3:
                session_id = parts[2]
                return HTTPStatus.OK, store.get_session(session_id)
            if len(parts) == 4 and parts[3] == "timeline":
                session_id = parts[2]
                return HTTPStatus.OK, {"events": store.timeline(session_id)}
            if len(parts) == 4 and parts[3] == "transcript":
                session_id = parts[2]
                return HTTPStatus.OK, {"session_id": session_id, "transcript": bridge.transcript_text(session_id, store=store)}
            if len(parts) == 4 and parts[3] == "evidence":
                session_id = parts[2]
                return HTTPStatus.OK, bridge.evidence_summary(session_id, store=store)
            if len(parts) == 4 and parts[3] == "diff":
                session_id = parts[2]
                return HTTPStatus.OK, {"session_id": session_id, "diff": bridge.session_diff_text(session_id, store=store)}
        return HTTPStatus.NOT_FOUND, {"error": "not found"}

    if method == "POST":
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
            created = store.create_session(doc)
            return HTTPStatus.CREATED, created

        if path.startswith("/api/sessions/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 4:
                session_id, action = parts[2], parts[3]
                if action == "pause":
                    session = store.transition_session(
                        session_id, "paused", actor="owner", reason=body.get("reason", "manual pause")
                    )
                    return HTTPStatus.OK, session
                if action == "resume":
                    session = store.transition_session(
                        session_id, "running", actor="owner", reason=body.get("reason", "manual resume")
                    )
                    return HTTPStatus.OK, session
                if action == "nudge":
                    session = store.add_nudge(
                        session_id=session_id,
                        actor=body.get("actor", "owner"),
                        nudge_type=body.get("nudge_type", "goal_correction"),
                        message=body["message"],
                        attachments=body.get("attachments", []),
                    )
                    return HTTPStatus.OK, session
                if action == "request-review":
                    session = review.spawn_reviewer(
                        store,
                        session_id,
                        provider=body.get("provider", ""),
                        model=body.get("model", ""),
                        effort=body.get("effort", "medium"),
                        selection_reason=body.get("selection_reason", "review request"),
                    )
                    return HTTPStatus.CREATED, session
                if action == "submit-review":
                    session = review.submit_review(
                        store,
                        parent_session_id=session_id,
                        review_session_id=body["review_session_id"],
                        comments=body.get("comments", []),
                        approved=bool(body.get("approved", False)),
                        actor=body.get("actor", "reviewer"),
                    )
                    return HTTPStatus.OK, session

    return HTTPStatus.NOT_FOUND, {"error": "not found"}


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    host = os.getenv("RELAYD_HOST", "127.0.0.1")
    port = int(os.getenv("RELAYD_PORT", "8787"))
    server = build_server(host, port)
    log.info("relayd listening on http://%s:%s", host, port)
    server.serve_forever()


def build_server(host: str = "127.0.0.1", port: int = 8787, store: Store | None = None) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), RelayHandler)
    server.store = store or Store()  # type: ignore[attr-defined]
    return server


def start_server_in_thread(host: str = "127.0.0.1", port: int = 0,
                           store: Store | None = None) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = build_server(host, port, store=store)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, t


if __name__ == "__main__":
    serve()
