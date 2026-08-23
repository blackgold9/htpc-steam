"""ThreadingHTTPServer wiring for the agent's HTTP API.

Threaded (not asyncio) so a slow handler can't block a concurrent request;
`/command`, once it exists in Phase 1, will need a lock around uinput writes
for the same reason.
"""

import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from ..config import AgentConfig
from . import handlers


def build_server(config: AgentConfig, uinput_available_fn: Callable[[], bool]) -> ThreadingHTTPServer:
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

        def do_GET(self) -> None:
            if self.path == "/health":
                status, ctype, body = handlers.handle_health(config, start_time, uinput_available_fn())
            elif self.path == "/status":
                status, ctype, body = handlers.handle_status(config, start_time)
            else:
                status, ctype, body = 404, "text/plain", b"not found"
            self._write(status, ctype, body)

    return ThreadingHTTPServer((config.host, config.port), Handler)
