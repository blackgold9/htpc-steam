"""Agent configuration: defaults plus a persisted override file.

Deliberately has no dependency on the `decky` module so it stays importable
and unit-testable outside a Decky Loader runtime; `main.py` is what wires in
Decky-provided paths and the plugin version.
"""

import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8086


@dataclass
class MqttConfig:
    enabled: bool = False
    host: str = ""
    port: int = 1883
    username: str = ""
    password: str = ""
    tls: bool = False
    topic_prefix: str = "uc-steamos"
    discovery_prefix: str = "homeassistant"
    publish_interval_s: float = 5.0


@dataclass
class AgentConfig:
    version: str = "0.0.0"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    auth_token: str = ""
    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
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
            stored_agent_id = data.get("agent_id")
            if _valid_agent_id(stored_agent_id):
                config.agent_id = stored_agent_id
            mqtt_data = data.get("mqtt", {})
            if isinstance(mqtt_data, dict):
                config.mqtt = _load_mqtt_config(mqtt_data)
            if stored_agent_id != config.agent_id:
                save_config(settings_dir, config)
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            pass
    else:
        save_config(settings_dir, config)

    return config


def parse_mqtt_config(data: dict) -> MqttConfig:
    """Validate an explicit MQTT settings payload.

    Unlike config-file loading, interactive callers need an error instead of a
    silent fallback so the UI cannot claim that invalid settings were saved.
    """
    if not isinstance(data, dict):
        raise ValueError("Invalid MQTT configuration")
    defaults = MqttConfig()
    values = {name: data.get(name, getattr(defaults, name)) for name in MqttConfig.__dataclass_fields__}
    strings = ("host", "username", "password", "topic_prefix", "discovery_prefix")
    valid = all(isinstance(values[name], str) for name in strings)
    limits = {"host": 255, "username": 256, "password": 1024, "topic_prefix": 256, "discovery_prefix": 256}
    if valid:
        encoded = {}
        try:
            for name in strings:
                encoded[name] = values[name].encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            valid = False
        valid = valid and all(
            len(encoded[name]) <= limits[name]
            and "\x00" not in values[name]
            and not any(
                ord(character) < 32
                or 0x7F <= ord(character) <= 0x9F
                or 0xFDD0 <= ord(character) <= 0xFDEF
                or ord(character) & 0xFFFF in (0xFFFE, 0xFFFF)
                for character in values[name]
            )
            for name in strings
        )
        valid = valid and (not values["host"] or values["host"] == values["host"].strip())
    valid = valid and isinstance(values["enabled"], bool) and isinstance(values["tls"], bool)
    valid = valid and isinstance(values["port"], int) and not isinstance(values["port"], bool)
    valid = valid and 1 <= values["port"] <= 65535
    interval = values["publish_interval_s"]
    valid = valid and isinstance(interval, (int, float)) and not isinstance(interval, bool)
    valid = valid and 1.0 <= interval <= 86400.0
    valid = valid and (not values["enabled"] or bool(values["host"].strip()))
    valid = valid and all(
        values[name].rstrip("/") and "+" not in values[name] and "#" not in values[name]
        for name in ("topic_prefix", "discovery_prefix")
    )
    if not valid:
        raise ValueError("Invalid MQTT configuration")
    values["publish_interval_s"] = float(interval)
    return MqttConfig(**values)


def _load_mqtt_config(data: dict) -> MqttConfig:
    try:
        return parse_mqtt_config(data)
    except ValueError:
        return MqttConfig()


def save_config(settings_dir: str, config: AgentConfig) -> None:
    config_path = os.path.join(settings_dir, "config.json")
    payload = {
        "host": config.host,
        "port": config.port,
        "auth_token": config.auth_token,
        "wol_arm": config.wol_arm,
        "agent_id": config.agent_id,
        "mqtt": asdict(config.mqtt),
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


def _valid_agent_id(value) -> bool:
    if not isinstance(value, str) or len(value) != 32:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
