"""Route handlers for the agent's HTTP API.

Each handler returns (status_code, content_type, body_bytes) rather than
touching a socket directly, so `server.py` and tests can exercise them
without a real HTTP connection. See docs/protocol.md for the wire contract.
"""

import json
import time

from ..commands.dispatcher import Dispatcher, UnknownCommandError
from ..config import AgentConfig


def handle_command(dispatcher: Dispatcher, command: str) -> tuple[int, str, bytes]:
    try:
        dispatcher.dispatch(command)
    except UnknownCommandError:
        payload = {"status": "error", "message": f"unknown command: {command}"}
        return 400, "application/json", json.dumps(payload).encode("utf-8")
    except OSError as err:
        payload = {"status": "error", "message": str(err)}
        return 500, "application/json", json.dumps(payload).encode("utf-8")
    return 200, "application/json", json.dumps({"status": "ok"}).encode("utf-8")


def handle_health(config: AgentConfig, start_time: float, uinput_available: bool) -> tuple[int, str, bytes]:
    payload = {
        "status": "ok",
        "version": config.version,
        "uptime_s": round(time.monotonic() - start_time, 1),
        "uinput_available": uinput_available,
    }
    return 200, "application/json", json.dumps(payload).encode("utf-8")


def handle_status(config: AgentConfig, start_time: float) -> tuple[int, str, bytes]:
    body = (
        f"UC SteamOS Agent {config.version}\n"
        f"Uptime: {round(time.monotonic() - start_time, 1)}s\n"
        f"Listening on {config.host}:{config.port}\n"
    )
    return 200, "text/plain", body.encode("utf-8")
