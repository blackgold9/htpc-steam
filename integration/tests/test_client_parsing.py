"""Protocol contract tests: fixture /sensors JSON -> parse_sensor_data() -> SystemData.

fixtures/agent_sensors_response.json is the actual captured live response
from the Bazzite test box (see docs/hardware-notes.md, Phase 3 section);
fixtures/agent_sensors_response_full.json is a hand-built fixture exercising
fields the real box didn't have populated (fans, battery).
"""

import json
from pathlib import Path

from uc_intg_steamos.client import parse_sensor_data

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    with open(FIXTURES / name) as f:
        return json.load(f)


def test_parses_real_captured_response():
    raw = _load("agent_sensors_response.json")
    sd = parse_sensor_data(raw)

    assert sd.detected_cpu_name == "AMD Ryzen 9 8945HS w/ Radeon 780M Graphics"
    assert sd.cpu_temp == 42.75
    assert sd.cpu_power is None  # confirmed real finding: no CPU power hwmon on this box
    assert sd.gpu_temp == 35.0
    assert sd.gpu_load == 26.0
    assert sd.has_dedicated_gpu is True
    assert round(sd.memory_used, 2) == round(3.1749801635742188, 2)
    assert sd.storage_used_percent == 25.466598568811634
    assert sd.fan_speeds == []  # confirmed: no fans on this box
    assert sd.battery_present is False


def test_network_kbps_converted_to_mbps():
    raw = _load("agent_sensors_response.json")
    sd = parse_sensor_data(raw)
    # wire schema is kbps; SystemData/media_player formatting expects Mbps
    assert sd.network_down == 510.96435889685847 / 1000
    assert sd.network_up == 72.22202650876696 / 1000


def test_parses_full_fixture_with_fans_and_battery():
    raw = _load("agent_sensors_response_full.json")
    sd = parse_sensor_data(raw)

    assert sd.fan_speeds == [1800, 2200]
    assert sd.battery_present is True
    assert sd.battery_percent == 85.0
    assert sd.battery_charging is True
    assert sd.battery_power == 15.0
    assert sd.motherboard_temp_avg == 38.0
    assert sd.motherboard_temp_max == 45.0
    assert sd.cpu_power == 28.5


def test_handles_missing_top_level_sections_gracefully():
    sd = parse_sensor_data({})
    assert sd.cpu_temp is None
    assert sd.detected_cpu_name == "CPU"
    assert sd.detected_gpu_name == "GPU"
    assert sd.fan_speeds == []
    assert sd.battery_present is False
    assert sd.network_up is None
    assert sd.network_down is None
