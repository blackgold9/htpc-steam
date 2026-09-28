import json
import stat

import pytest
from uc_steamos_agent.config import AgentConfig, MqttConfig, load_config, parse_mqtt_config, save_config


def test_load_config_creates_defaults(tmp_path):
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.version == "0.1.0"
    assert config.port == 8086
    assert config.host == "0.0.0.0"
    assert config.auth_token == ""
    assert len(config.agent_id) == 32
    assert int(config.agent_id, 16) >= 0
    assert config.mqtt == MqttConfig()
    assert (tmp_path / "config.json").exists()

    reloaded = load_config(str(tmp_path), version="0.1.0")
    assert reloaded.agent_id == config.agent_id


def test_load_config_reads_persisted_overrides(tmp_path):
    mqtt = MqttConfig(
        enabled=True,
        host="ha.internal",
        port=8883,
        username="agent",
        password="broker-secret",
        tls=True,
        topic_prefix="house/steam",
        discovery_prefix="ha",
        publish_interval_s=7.5,
    )
    save_config(
        str(tmp_path),
        AgentConfig(version="0.1.0", port=9001, auth_token="secret", mqtt=mqtt),
    )
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.port == 9001
    assert config.auth_token == "secret"
    assert config.mqtt == mqtt
    assert stat.S_IMODE((tmp_path / "config.json").stat().st_mode) == 0o600


def test_parse_mqtt_config_rejects_invalid_ui_values_instead_of_silently_defaulting():
    valid = {
        "enabled": True,
        "host": "ha.internal",
        "port": 1883,
        "username": "agent",
        "password": "secret",
        "tls": False,
        "topic_prefix": "uc-steamos",
        "discovery_prefix": "homeassistant",
        "publish_interval_s": 5,
    }

    assert parse_mqtt_config(valid) == MqttConfig(**valid)
    with pytest.raises(ValueError, match="Invalid MQTT configuration"):
        parse_mqtt_config({**valid, "port": 0})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host", "   "),
        ("host", "ha.internal\x00evil"),
        ("username", "agent\x00evil"),
        ("password", "secret\x00evil"),
        ("topic_prefix", "uc\x00steamos"),
        ("discovery_prefix", "homeassistant\x00evil"),
        ("host", "ha.internal\u0085evil"),
        ("username", "agent\u009fevil"),
        ("topic_prefix", "uc\ufdd0steamos"),
        ("username", "é" * 129),
        ("host", "h" * 256),
        ("username", "u" * 257),
        ("password", "p" * 1025),
        ("topic_prefix", "t" * 257),
    ],
)
def test_parse_mqtt_config_rejects_blank_control_and_oversized_strings(field, value):
    values = {"enabled": True, "host": "ha.internal", field: value}
    with pytest.raises(ValueError, match="Invalid MQTT configuration"):
        parse_mqtt_config(values)


def test_load_config_survives_corrupt_file(tmp_path):
    (tmp_path / "config.json").write_text("not json")
    config = load_config(str(tmp_path), version="0.1.0")
    assert config.port == 8086


def test_load_config_survives_non_utf8_file(tmp_path):
    (tmp_path / "config.json").write_bytes(b'{"mqtt":"\xff"}')

    config = load_config(str(tmp_path), version="0.1.0")

    assert config.version == "0.1.0"
    assert config.host == "0.0.0.0"
    assert config.port == 8086
    assert config.mqtt == MqttConfig()


@pytest.mark.parametrize(
    "override",
    [
        {"enabled": "yes"},
        {"host": None},
        {"host": ""},
        {"port": "1883"},
        {"port": True},
        {"port": 0},
        {"port": 65536},
        {"username": None},
        {"password": []},
        {"tls": "false"},
        {"topic_prefix": None},
        {"topic_prefix": "uc-steamos/+"},
        {"topic_prefix": "uc-steamos/#"},
        {"discovery_prefix": None},
        {"discovery_prefix": "homeassistant/+"},
        {"publish_interval_s": True},
        {"publish_interval_s": 0},
        {"publish_interval_s": float("inf")},
        {"publish_interval_s": 10**400},
    ],
)
def test_malformed_optional_mqtt_config_fails_closed_without_losing_http_config(tmp_path, override):
    mqtt = {
        "enabled": True,
        "host": "ha.internal",
        "port": 1883,
        "username": "agent",
        "password": "secret",
        "tls": True,
        "topic_prefix": "uc-steamos",
        "discovery_prefix": "homeassistant",
        "publish_interval_s": 5,
        **override,
    }
    (tmp_path / "config.json").write_text(
        json.dumps({"host": "127.0.0.1", "port": 9001, "auth_token": "http-secret", "mqtt": mqtt})
    )

    config = load_config(str(tmp_path), version="0.1.0")

    assert (config.host, config.port, config.auth_token) == ("127.0.0.1", 9001, "http-secret")
    assert config.mqtt == MqttConfig()
