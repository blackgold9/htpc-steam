"""ThreadingHTTPServer wiring for the agent's HTTP API.

Threaded (not asyncio) so a slow handler can't block a concurrent request;
`Dispatcher` (see ../commands/dispatcher.py) holds its own lock around
uinput writes for the same reason.
"""

import hmac
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ..commands.dispatcher import Dispatcher
from ..config import AgentConfig
from . import handlers


def build_server(
    config: AgentConfig,
    uinput_available_fn: Callable[[], bool],
    dispatcher: Dispatcher,
    sensors_fn: Callable[[], dict] | None = None,
    games_fn: Callable[[], list[dict]] | None = None,
) -> ThreadingHTTPServer:
    start_time = time.monotonic()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A002 - stdlib signature
            pass  # caller wires real logging via `decky.logger`, not stderr

        def _write(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            """Opt-in shared-secret check (docs/protocol.md's "Auth posture").

            Applies to every endpoint, not just /command: /games leaks the
            user's library and /sensors their hardware, and the integration's
            client sets X-UC-Token on the whole session anyway, so there's no
            compatibility reason to carve exceptions. compare_digest because
            this is a shared secret compared against attacker-supplied input.
            """
            if not config.auth_token:
                return True
            return hmac.compare_digest(self.headers.get("X-UC-Token", ""), config.auth_token)

        def do_GET(self) -> None:
            if not self._authorized():
                self._write(*handlers.handle_unauthorized())
                return
            if self.path == "/health":
                status, ctype, body = handlers.handle_health(config, start_time, uinput_available_fn())
            elif self.path == "/status":
                status, ctype, body = handlers.handle_status(config, start_time)
            elif self.path == "/sensors" and sensors_fn is not None:
                status, ctype, body = handlers.handle_sensors(sensors_fn())
            elif self.path == "/games" and games_fn is not None:
                status, ctype, body = handlers.handle_games(games_fn())
            else:
                status, ctype, body = 404, "text/plain", b"not found"
            self._write(status, ctype, body)

        def do_POST(self) -> None:
            if not self._authorized():
                self._write(*handlers.handle_unauthorized())
                return
            if self.path != "/command":
                self._write(404, "text/plain", b"not found")
                return

            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            try:
                data = json.loads(raw) if raw else {}
                command = data["command"]
            except (json.JSONDecodeError, KeyError, TypeError):
                payload = {"status": "error", "message": "expected JSON body: {\"command\": \"...\"}"}
                self._write(400, "application/json", json.dumps(payload).encode("utf-8"))
                return

            status, ctype, body = handlers.handle_command(dispatcher, command)
            self._write(status, ctype, body)

    return ThreadingHTTPServer((config.host, config.port), Handler)
