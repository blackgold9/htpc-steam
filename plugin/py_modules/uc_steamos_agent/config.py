"""Agent configuration: defaults plus a persisted override file.

Deliberately has no dependency on the `decky` module so it stays importable
and unit-testable outside a Decky Loader runtime; `main.py` is what wires in
Decky-provided paths and the plugin version.
"""

import json
import os
import tempfile
from dataclasses import dataclass

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8086


@dataclass
class AgentConfig:
    version: str = "0.0.0"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    auth_token: str = ""
    # Opt-in: re-apply `ethtool -s <iface> wol g` whenever the plugin starts.
    # Off by default because it changes a NIC-wide power setting; see
    # commands/wol.py for why re-applying at start is the only thing that
    # survives a driver reload.
    wol_arm: bool = False


def load_config(settings_dir: str, version: str) -> AgentConfig:
    """Load config.json from settings_dir, writing it with defaults if absent."""
    config_path = os.path.join(settings_dir, "config.json")
    config = AgentConfig(version=version)

    if os.path.exists(config_path):
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            config.host = data.get("host", config.host)
            config.port = data.get("port", config.port)
            config.auth_token = data.get("auth_token", config.auth_token)
            config.wol_arm = bool(data.get("wol_arm", config.wol_arm))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
    else:
        save_config(settings_dir, config)

    return config


def save_config(settings_dir: str, config: AgentConfig) -> None:
    config_path = os.path.join(settings_dir, "config.json")
    payload = {
        "host": config.host,
        "port": config.port,
        "auth_token": config.auth_token,
        "wol_arm": config.wol_arm,
    }
    os.makedirs(settings_dir, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=settings_dir, prefix=".config.json.", delete=False
        ) as f:
            temporary_path = f.name
            os.chmod(temporary_path, 0o600)
            json.dump(payload, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary_path, config_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
