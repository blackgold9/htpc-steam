import pytest

from uc_intg_steamos.client import SteamOSClient
from uc_intg_steamos.setup_flow import SteamOSSetupFlow


async def fake_close(self):
    pass


@pytest.fixture
def flow():
    return SteamOSSetupFlow(None, driver=None)


@pytest.fixture(autouse=True)
def patch_close(monkeypatch):
    monkeypatch.setattr(SteamOSClient, "close", fake_close)


async def test_missing_host_raises(flow):
    with pytest.raises(ValueError, match="IP address is required"):
        await flow.query_device({"host": ""})


async def test_agent_unreachable_raises(flow, monkeypatch):
    async def fake_test_agent(self):
        return False

    monkeypatch.setattr(SteamOSClient, "test_agent", fake_test_agent)

    with pytest.raises(ValueError, match="Cannot connect to the SteamOS agent"):
        await flow.query_device({"host": "192.168.1.50"})


async def test_sensor_test_failure_raises_when_monitoring_enabled(flow, monkeypatch):
    async def fake_test_agent(self):
        return True

    async def fake_test_sensors(self):
        return {"success": False, "error": "boom"}

    monkeypatch.setattr(SteamOSClient, "test_agent", fake_test_agent)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fake_test_sensors)

    with pytest.raises(ValueError, match="sensor data unavailable"):
        await flow.query_device({"host": "192.168.1.50", "enable_hardware_monitoring": "enabled"})


async def test_successful_setup_returns_populated_config(flow, monkeypatch):
    async def fake_test_agent(self):
        return True

    async def fake_test_sensors(self):
        return {"success": True, "sensor_count": 9}

    monkeypatch.setattr(SteamOSClient, "test_agent", fake_test_agent)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fake_test_sensors)

    config = await flow.query_device({
        "host": "192.168.6.193",
        "name": "My Deck",
        "enable_hardware_monitoring": "enabled",
        "temperature_unit": "fahrenheit",
        "auth_token": "secret",
    })

    assert config.identifier == "steamos_192_168_6_193"
    assert config.name == "My Deck"
    assert config.host == "192.168.6.193"
    assert config.enable_hardware_monitoring is True
    assert config.temperature_unit == "fahrenheit"
    assert config.auth_token == "secret"


async def test_monitoring_disabled_skips_sensor_test(flow, monkeypatch):
    async def fake_test_agent(self):
        return True

    def fail_if_called(self):
        raise AssertionError("test_sensors should not be called when monitoring is disabled")

    monkeypatch.setattr(SteamOSClient, "test_agent", fake_test_agent)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fail_if_called)

    config = await flow.query_device({"host": "192.168.6.193", "enable_hardware_monitoring": "disabled"})
    assert config.enable_hardware_monitoring is False
