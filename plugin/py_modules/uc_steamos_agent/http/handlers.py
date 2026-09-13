"""Route handlers for the agent's HTTP API.

Each handler returns (status_code, content_type, body_bytes) rather than
touching a socket directly, so `server.py` and tests can exercise them
without a real HTTP connection. See docs/protocol.md for the wire contract.
"""

import json
import subprocess
import time

from ..commands.dispatcher import CommandExecutionError, Dispatcher, UnknownCommandError
from ..config import AgentConfig


def handle_command(dispatcher: Dispatcher, command: str) -> tuple[int, str, bytes]:
    try:
        dispatcher.dispatch(command)
    except UnknownCommandError:
        payload = {"status": "error", "message": f"unknown command: {command}"}
        return 400, "application/json", json.dumps(payload).encode("utf-8")
    except CommandExecutionError as err:
        payload = {"status": "error", "message": str(err)}
        return 409, "application/json", json.dumps(payload).encode("utf-8")
    except (OSError, subprocess.SubprocessError) as err:
        # OSError covers uinput/device failures and a missing binary
        # (FileNotFoundError); SubprocessError covers a helper exiting non-zero
        # under check=True (e.g. wpctl with no default sink) -- both must
        # return a clean 500 rather than escape and reset the connection.
        payload = {"status": "error", "message": str(err)}
        return 500, "application/json", json.dumps(payload).encode("utf-8")
    return 200, "application/json", json.dumps({"status": "ok"}).encode("utf-8")


def handle_health(
    config: AgentConfig,
    start_time: float,
    uinput_available: bool,
    wol_status: dict | None = None,
) -> tuple[int, str, bytes]:
    payload = {
        "status": "ok",
        "version": config.version,
        "uptime_s": round(time.monotonic() - start_time, 1),
        "uinput_available": uinput_available,
        # The arming preference is reported unconditionally so the integration
        # can tell "user never asked for WoL" from "asked and it failed".
        "wol_arm": config.wol_arm,
    }
    if wol_status:
        # Reported on /health too, not only /sensors, so a caller that hasn't
        # enabled sensor polling (the integration's enable_hardware_monitoring
        # off switch, or the QAM panel) can still see whether WoL is armed.
        # Omitted when unreadable — absent means "unknown", not "unsupported".
        payload["wol"] = wol_status
    return 200, "application/json", json.dumps(payload).encode("utf-8")


def handle_status(config: AgentConfig, start_time: float) -> tuple[int, str, bytes]:
    body = (
        f"UC SteamOS Agent {config.version}\n"
        f"Uptime: {round(time.monotonic() - start_time, 1)}s\n"
        f"Listening on {config.host}:{config.port}\n"
    )
    return 200, "text/plain", body.encode("utf-8")


def handle_sensors(snapshot: dict) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps(snapshot).encode("utf-8")


def handle_games(games: list[dict]) -> tuple[int, str, bytes]:
    return 200, "application/json", json.dumps({"games": games}).encode("utf-8")


def handle_unauthorized() -> tuple[int, str, bytes]:
    """401 for a missing/wrong X-UC-Token when the agent has a token configured.

    Deliberately doesn't say whether the header was absent or merely wrong --
    that distinction only helps someone guessing at it.
    """
    payload = {"status": "error", "message": "unauthorized"}
    return 401, "application/json", json.dumps(payload).encode("utf-8")
