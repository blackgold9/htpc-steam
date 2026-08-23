"""Agent configuration: defaults plus a persisted override file.

Deliberately has no dependency on the `decky` module so it stays importable
and unit-testable outside a Decky Loader runtime; `main.py` is what wires in
Decky-provided paths and the plugin version.
"""

import json
import os
from dataclasses import dataclass

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8086


@dataclass
class AgentConfig:
    version: str = "0.0.0"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    auth_token: str = ""


def load_config(settings_dir: str, version: str) -> AgentConfig:
    """Load config.json from settings_dir, writing it with defaults if absent."""
    config_path = os.path.join(settings_dir, "config.json")
    config = AgentConfig(version=version)

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            config.host = data.get("host", config.host)
            config.port = data.get("port", config.port)
            config.auth_token = data.get("auth_token", config.auth_token)
        except (json.JSONDecodeError, OSError):
            pass
    else:
        save_config(settings_dir, config)

    return config


def save_config(settings_dir: str, config: AgentConfig) -> None:
    config_path = os.path.join(settings_dir, "config.json")
    payload = {"host": config.host, "port": config.port, "auth_token": config.auth_token}
    os.makedirs(settings_dir, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
