"""Home Assistant MQTT device discovery payloads.

Discovery is deliberately read-only: no component has a command topic and the
agent never subscribes to an agent command topic.
"""

import hashlib
import re
from dataclasses import dataclass

from ..config import AgentConfig

SUPPORT_URL = "https://github.com/blackgold9/htpc-steam"


@dataclass(frozen=True)
class DiscoveryMessage:
    topic: str
    payload: dict
    qos: int = 1
    retain: bool = True


def _sensor(unique_id, name, template, *, device_class=None, unit=None, state_class=None, diagnostic=False):
    component = {
        "platform": "sensor",
        "unique_id": unique_id,
        "name": name,
        "value_template": template,
    }
    if device_class:
        component["device_class"] = device_class
    if unit:
        component["unit_of_measurement"] = unit
    if state_class:
        component["state_class"] = state_class
    if diagnostic:
        component["entity_category"] = "diagnostic"
        component["enabled_by_default"] = False
    return component


def _binary(unique_id, name, template, *, device_class=None, diagnostic=False):
    component = {
        "platform": "binary_sensor",
        "unique_id": unique_id,
        "name": name,
        "value_template": template,
        "payload_on": "ON",
        "payload_off": "OFF",
    }
    if device_class:
        component["device_class"] = device_class
    if diagnostic:
        component["entity_category"] = "diagnostic"
        component["enabled_by_default"] = False
    return component


def _availability(*topics):
    return {
        "availability": [{"topic": topic} for topic in topics],
        "availability_mode": "all",
        "payload_available": "online",
        "payload_not_available": "offline",
    }


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "fan"


def _agent_components(agent_id: str, sensors: dict) -> dict:
    uid = f"uc_steamos_{agent_id}"
    components = {
        "agent_version": _sensor(uid + "_version", "Version", "{{ value_json.version }}", diagnostic=True),
        "uinput_available": _binary(
            uid + "_uinput",
            "Uinput available",
            "{{ 'ON' if value_json.uinput_available else 'OFF' }}",
            diagnostic=True,
        ),
        "cpu_temperature": _sensor(
            uid + "_cpu_temp",
            "CPU temperature",
            "{{ value_json.sensors.cpu.temp_c }}",
            device_class="temperature",
            unit="°C",
            state_class="measurement",
        ),
        "cpu_utilization": _sensor(
            uid + "_cpu_load",
            "CPU utilization",
            "{{ value_json.sensors.cpu.load_pct }}",
            unit="%",
            state_class="measurement",
        ),
        "cpu_clock": _sensor(
            uid + "_cpu_clock",
            "CPU clock",
            "{{ value_json.sensors.cpu.clock_mhz }}",
            device_class="frequency",
            unit="MHz",
            state_class="measurement",
            diagnostic=True,
        ),
        "cpu_power": _sensor(
            uid + "_cpu_power",
            "CPU power",
            "{{ value_json.sensors.cpu.power_w }}",
            device_class="power",
            unit="W",
            state_class="measurement",
            diagnostic=True,
        ),
        "gpu_temperature": _sensor(
            uid + "_gpu_temp",
            "GPU temperature",
            "{{ value_json.sensors.gpu.temp_c }}",
            device_class="temperature",
            unit="°C",
            state_class="measurement",
        ),
        "gpu_utilization": _sensor(
            uid + "_gpu_load",
            "GPU utilization",
            "{{ value_json.sensors.gpu.load_pct }}",
            unit="%",
            state_class="measurement",
        ),
        "memory_used": _sensor(
            uid + "_memory_used",
            "Memory used",
            "{{ value_json.sensors.memory.used_gb }}",
            device_class="data_size",
            unit="GB",
            state_class="measurement",
        ),
        "memory_total": _sensor(
            uid + "_memory_total",
            "Memory total",
            "{{ value_json.sensors.memory.total_gb }}",
            device_class="data_size",
            unit="GB",
            state_class="measurement",
            diagnostic=True,
        ),
        "storage_used": _sensor(
            uid + "_storage_used",
            "Storage used",
            "{{ value_json.sensors.storage.used_gb }}",
            device_class="data_size",
            unit="GB",
            state_class="measurement",
            diagnostic=True,
        ),
        "storage_total": _sensor(
            uid + "_storage_total",
            "Storage total",
            "{{ value_json.sensors.storage.total_gb }}",
            device_class="data_size",
            unit="GB",
            state_class="measurement",
            diagnostic=True,
        ),
        "storage_used_percent": _sensor(
            uid + "_storage_pct",
            "Storage used",
            "{{ value_json.sensors.storage.used_pct }}",
            unit="%",
            state_class="measurement",
        ),
        "storage_temperature": _sensor(
            uid + "_storage_temp",
            "Storage temperature",
            "{{ value_json.sensors.storage.temp_c }}",
            device_class="temperature",
            unit="°C",
            state_class="measurement",
            diagnostic=True,
        ),
        "network_download": _sensor(
            uid + "_network_down",
            "Network download",
            "{{ value_json.sensors.network.down_kbps }}",
            device_class="data_rate",
            unit="kbit/s",
            state_class="measurement",
        ),
        "network_upload": _sensor(
            uid + "_network_up",
            "Network upload",
            "{{ value_json.sensors.network.up_kbps }}",
            device_class="data_rate",
            unit="kbit/s",
            state_class="measurement",
        ),
        "wol_supported": _binary(
            uid + "_wol_supported",
            "Wake-on-LAN supported",
            "{% set wol = value_json.sensors.get('wol') %}"
            "{% if wol is none or wol.get('supported') is none %}None"
            "{% elif wol.get('supported') %}ON{% else %}OFF{% endif %}",
            diagnostic=True,
        ),
        "wol_enabled": _binary(
            uid + "_wol_enabled",
            "Wake-on-LAN enabled",
            "{% set wol = value_json.sensors.get('wol') %}"
            "{% if wol is none or wol.get('enabled') is none %}None"
            "{% elif wol.get('enabled') %}ON{% else %}OFF{% endif %}",
        ),
        "wol_may_wakeup": _binary(
            uid + "_wol_may_wakeup",
            "Wake-on-LAN kernel wake",
            "{% set wol = value_json.sensors.get('wol') %}"
            "{% if wol is none or wol.get('may_wakeup') is none %}None"
            "{% elif wol.get('may_wakeup') %}ON{% else %}OFF{% endif %}",
            diagnostic=True,
        ),
        "recent_games_count": _sensor(
            uid + "_games_count", "Recent games", "{{ value_json.recent_games_count }}", diagnostic=True
        ),
    }
    battery = sensors.get("battery", {})
    if battery.get("present"):
        components["system_battery"] = _sensor(
            uid + "_battery",
            "System battery",
            "{{ value_json.sensors.battery.percent }}",
            device_class="battery",
            unit="%",
            state_class="measurement",
        )
        components["system_charging"] = _binary(
            uid + "_charging",
            "System charging",
            "{% set charging = value_json.sensors.battery.charging %}"
            "{% if charging is none %}None{% elif charging %}ON{% else %}OFF{% endif %}",
            device_class="battery_charging",
        )
        components["system_battery_power"] = _sensor(
            uid + "_battery_power",
            "System battery power",
            "{{ value_json.sensors.battery.power_w }}",
            device_class="power",
            unit="W",
            state_class="measurement",
            diagnostic=True,
        )
    used_keys = set(components)
    for index, fan in enumerate(sensors.get("fans", [])):
        label = str(fan.get("label") or f"Fan {index + 1}")
        digest = hashlib.sha256(label.encode("utf-8")).hexdigest()[:8]
        base_key = f"fan_{_slug(label)}_{digest}"
        key = base_key
        duplicate = 2
        while key in used_keys:
            key = f"{base_key}_{duplicate}"
            duplicate += 1
        used_keys.add(key)
        components[key] = _sensor(
            uid + f"_{key}",
            label,
            f"{{{{ value_json.sensors.fans[{index}].rpm }}}}",
            unit="rpm",
            state_class="measurement",
            diagnostic=True,
        )
    return components


def _puck_components(agent_id: str, base: str) -> dict:
    uid = f"uc_steamos_{agent_id}_puck"
    agent_availability = f"{base}/availability"
    puck_availability = f"{base}/puck/availability"
    state_topic = f"{base}/puck/state"
    event_topic = f"{base}/puck/event"
    agent_only = _availability(agent_availability)
    both = _availability(agent_availability, puck_availability)
    components = {
        "puck_connected": {
            **_binary(
                uid + "_connected",
                "Connected",
                "{{ 'ON' if value_json.available else 'OFF' }}",
                device_class="connectivity",
            ),
            "state_topic": state_topic,
            **agent_only,
        },
        "puck_docked": {
            **_binary(
                uid + "_docked",
                "Docked",
                "{% if value_json.docked is none %}None"
                "{% elif value_json.docked %}ON{% else %}OFF{% endif %}",
                device_class="plug",
            ),
            "state_topic": state_topic,
            **both,
        },
        "puck_battery": {
            **_sensor(
                uid + "_battery",
                "Battery",
                "{{ value_json.battery_percent }}",
                device_class="battery",
                unit="%",
                state_class="measurement",
            ),
            "state_topic": state_topic,
            **both,
        },
        "puck_charge_state": {
            **_sensor(uid + "_charge_state", "Charge state", "{{ value_json.charge_state }}"),
            "device_class": "enum",
            "options": ["reset", "discharging", "charging", "source_validation", "charged", "unknown"],
            "state_topic": state_topic,
            **both,
        },
        "puck_event": {
            "platform": "event",
            "unique_id": uid + "_event",
            "name": "Pickup",
            "state_topic": event_topic,
            "event_types": ["pickup_candidate", "picked_up", "candidate_expired"],
            **both,
        },
        "pickup_candidate_trigger": {
            "platform": "device_automation",
            "automation_type": "trigger",
            "topic": event_topic,
            "value_template": "{{ value_json.event_type }}",
            "payload": "pickup_candidate",
            "type": "pickup_candidate",
            "subtype": "controller",
        },
        "picked_up_trigger": {
            "platform": "device_automation",
            "automation_type": "trigger",
            "topic": event_topic,
            "value_template": "{{ value_json.event_type }}",
            "payload": "picked_up",
            "type": "picked_up",
            "subtype": "controller",
        },
        "puck_candidate_pending": {
            **_binary(
                uid + "_candidate",
                "Pickup candidate pending",
                "{{ 'ON' if value_json.pickup_candidate else 'OFF' }}",
                diagnostic=True,
            ),
            "state_topic": state_topic,
            **both,
        },
        "puck_confirmed_count": {
            **_sensor(
                uid + "_confirmed_count",
                "Confirmed pickups",
                "{{ value_json.diagnostics.confirmed_pickup_count }}",
                state_class="total_increasing",
                diagnostic=True,
            ),
            "state_topic": state_topic,
            **agent_only,
        },
        "puck_rejected_count": {
            **_sensor(
                uid + "_rejected_count",
                "Rejected pickup candidates",
                "{{ value_json.diagnostics.unconfirmed_disconnect_count }}",
                state_class="total_increasing",
                diagnostic=True,
            ),
            "state_topic": state_topic,
            **agent_only,
        },
    }
    return components


def discovery_messages(config: AgentConfig, sensors: dict) -> list[DiscoveryMessage]:
    """Build retained Home Assistant device discovery messages."""
    mqtt = config.mqtt
    base = f"{mqtt.topic_prefix.rstrip('/')}/{config.agent_id}"
    discovery_base = mqtt.discovery_prefix.rstrip("/")
    agent_identifier = f"uc-steamos:{config.agent_id}"
    origin = {"name": "uc-steamos-agent", "sw_version": config.version, "support_url": SUPPORT_URL}
    agent_payload = {
        "device": {
            "identifiers": [agent_identifier],
            "name": "SteamOS Agent",
            "manufacturer": "UC Project",
            "model": "SteamOS Agent",
            "sw_version": config.version,
        },
        "origin": origin,
        "availability_topic": f"{base}/availability",
        "state_topic": f"{base}/system/state",
        "qos": 1,
        "components": _agent_components(config.agent_id, sensors),
    }
    puck_payload = {
        "device": {
            "identifiers": [agent_identifier + ":puck"],
            "name": "Steam Controller Puck",
            "manufacturer": "Valve",
            "model": "Steam Controller Puck",
            "via_device": agent_identifier,
        },
        "origin": origin,
        "components": _puck_components(config.agent_id, base),
    }
    return [
        DiscoveryMessage(f"{discovery_base}/device/uc_steamos_{config.agent_id}/config", agent_payload),
        DiscoveryMessage(f"{discovery_base}/device/uc_steamos_{config.agent_id}_puck/config", puck_payload),
    ]
