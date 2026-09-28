from uc_steamos_agent.config import AgentConfig
from uc_steamos_agent.mqtt.discovery import discovery_messages

AGENT_ID = "0123456789abcdef0123456789abcdef"


def _sensor_snapshot():
    return {
        "cpu": {"name": "CPU", "temp_c": 61.5, "load_pct": 42.0, "clock_mhz": 3200, "power_w": 18.0},
        "gpu": {"name": "GPU", "temp_c": 58.0, "load_pct": 20.0, "has_dedicated_gpu": True},
        "memory": {"used_gb": 7.0, "total_gb": 16.0},
        "storage": {"used_gb": 100.0, "total_gb": 500.0, "used_pct": 20.0, "temp_c": 44.0},
        "network": {"up_kbps": 12.0, "down_kbps": 34.0},
        "motherboard": {"temp_avg_c": None, "temp_max_c": None},
        "fans": [{"label": "CPU Fan", "rpm": 1200}],
        "battery": {"present": False, "percent": None, "charging": None, "power_w": None},
        "wol": {"supported": True, "enabled": True, "may_wakeup": True},
    }


def _contains_key(value, forbidden):
    if isinstance(value, dict):
        return forbidden in value or any(_contains_key(item, forbidden) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def test_device_discovery_exposes_read_only_agent_and_puck_entities():
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID)

    messages = discovery_messages(config, _sensor_snapshot())

    assert [message.topic for message in messages] == [
        f"homeassistant/device/uc_steamos_{AGENT_ID}/config",
        f"homeassistant/device/uc_steamos_{AGENT_ID}_puck/config",
    ]
    assert all(message.retain is True and message.qos == 1 for message in messages)
    assert all(not _contains_key(message.payload, "command_topic") for message in messages)

    agent = messages[0].payload
    assert agent["device"]["identifiers"] == [f"uc-steamos:{AGENT_ID}"]
    assert "configuration_url" not in agent["device"]
    assert agent["origin"]["name"] == "uc-steamos-agent"
    assert set(agent["components"]) >= {
        "agent_version",
        "uinput_available",
        "cpu_temperature",
        "cpu_utilization",
        "gpu_temperature",
        "gpu_utilization",
        "memory_used",
        "storage_used_percent",
        "network_download",
        "network_upload",
        "wol_enabled",
    }
    assert any(component.get("name") == "CPU Fan" for component in agent["components"].values())
    assert ".get('wol')" in agent["components"]["wol_enabled"]["value_template"]

    puck = messages[1].payload
    assert puck["device"]["via_device"] == f"uc-steamos:{AGENT_ID}"
    assert set(puck["components"]) >= {
        "puck_connected",
        "puck_docked",
        "puck_battery",
        "puck_charge_state",
        "puck_event",
        "pickup_candidate_trigger",
        "picked_up_trigger",
    }
    assert puck["components"]["puck_event"]["event_types"] == [
        "pickup_candidate",
        "picked_up",
        "candidate_expired",
    ]
    assert "docked is none" in puck["components"]["puck_docked"]["value_template"]


def test_fan_unique_id_survives_reordering_and_removal():
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID)
    sensors = _sensor_snapshot()
    sensors["fans"] = [
        {"label": "CPU Fan", "rpm": 1200},
        {"label": "Case Fan", "rpm": 900},
    ]
    before = discovery_messages(config, sensors)[0].payload["components"]

    sensors["fans"] = [{"label": "Case Fan", "rpm": 900}]
    after = discovery_messages(config, sensors)[0].payload["components"]

    before_id = next(
        component["unique_id"] for component in before.values() if component.get("name") == "Case Fan"
    )
    after_id = next(
        component["unique_id"] for component in after.values() if component.get("name") == "Case Fan"
    )
    assert before_id == after_id


def test_fan_identity_survives_reorder_removal_and_slug_collisions():
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID)
    sensors = _sensor_snapshot()
    sensors["fans"] = [
        {"label": "CPU Fan", "rpm": 1200},
        {"label": "Case Fan", "rpm": 900},
    ]

    before = discovery_messages(config, sensors)[0].payload["components"]
    surviving_id = next(
        component["unique_id"] for component in before.values() if component.get("name") == "Case Fan"
    )
    sensors["fans"] = [{"label": "Case Fan", "rpm": 910}]
    after = discovery_messages(config, sensors)[0].payload["components"]

    assert (
        next(component["unique_id"] for component in after.values() if component.get("name") == "Case Fan")
        == surviving_id
    )

    sensors["fans"] = [
        {"label": "Case Fan", "rpm": 910},
        {"label": "case-fan", "rpm": 920},
    ]
    collided = discovery_messages(config, sensors)[0].payload["components"]
    assert {component.get("name") for component in collided.values()} >= {"Case Fan", "case-fan"}

    sensors["fans"].reverse()
    reordered = discovery_messages(config, sensors)[0].payload["components"]
    before_ids = {component["name"]: component["unique_id"] for component in collided.values()}
    after_ids = {component["name"]: component["unique_id"] for component in reordered.values()}
    assert before_ids == after_ids


def test_unknown_system_charging_state_stays_unknown():
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID)
    sensors = _sensor_snapshot()
    sensors["battery"].update({"present": True, "charging": None})

    components = discovery_messages(config, sensors)[0].payload["components"]

    assert "charging is none" in components["system_charging"]["value_template"]
