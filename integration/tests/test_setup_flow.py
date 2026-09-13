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
    async def fake_agent_status(self):
        return None

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)

    with pytest.raises(ValueError, match="connection failed or refused"):
        await flow.query_device({"host": "203.0.113.10"})


async def test_rejected_auth_token_raises_a_distinct_error(flow, monkeypatch):
    """A 401 must not read as "unreachable" -- that sends users debugging
    the network instead of their token. See client.agent_status()."""
    async def fake_agent_status(self):
        return 401

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)

    with pytest.raises(ValueError, match="rejected the auth token"):
        await flow.query_device({"host": "203.0.113.10", "auth_token": "wrong"})


async def test_sensor_test_failure_raises_when_monitoring_enabled(flow, monkeypatch):
    async def fake_agent_status(self):
        return 200

    async def fake_test_sensors(self):
        return {"success": False, "error": "boom"}

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fake_test_sensors)

    with pytest.raises(ValueError, match="sensor data unavailable"):
        await flow.query_device({"host": "203.0.113.10", "enable_hardware_monitoring": "enabled"})


async def test_successful_setup_returns_populated_config(flow, monkeypatch):
    async def fake_agent_status(self):
        return 200

    async def fake_test_sensors(self):
        return {"success": True, "sensor_count": 9}

    async def fake_fetch_wol_mac(self):
        return ""

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fake_test_sensors)
    monkeypatch.setattr(SteamOSClient, "fetch_wol_mac", fake_fetch_wol_mac)

    config = await flow.query_device({
        "host": "203.0.113.10",
        "name": "My Deck",
        "enable_hardware_monitoring": "enabled",
        "temperature_unit": "fahrenheit",
        "auth_token": "secret",
    })

    assert config.identifier == "steamos_203_0_113_10"
    assert config.name == "My Deck"
    assert config.host == "203.0.113.10"
    assert config.enable_hardware_monitoring is True
    assert config.temperature_unit == "fahrenheit"
    assert config.auth_token == "secret"


async def test_monitoring_disabled_skips_sensor_test(flow, monkeypatch):
    async def fake_agent_status(self):
        return 200

    def fail_if_called(self):
        raise AssertionError("test_sensors should not be called when monitoring is disabled")

    async def fake_fetch_wol_mac(self):
        return ""

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fail_if_called)
    monkeypatch.setattr(SteamOSClient, "fetch_wol_mac", fake_fetch_wol_mac)

    config = await flow.query_device({"host": "203.0.113.10", "enable_hardware_monitoring": "disabled"})
    assert config.enable_hardware_monitoring is False


async def test_mac_is_discovered_from_the_agent_not_typed_in(flow, monkeypatch):
    """The MAC comes from the agent's own /health, not a setup field: a
    motherboard/NIC swap must not require the user to remember to update it."""

    async def fake_agent_status(self):
        return 200

    async def fake_test_sensors(self):
        return {"success": True, "sensor_count": 9}

    async def fake_fetch_wol_mac(self):
        return "AA:BB:CC:DD:EE:FF"

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)
    monkeypatch.setattr(SteamOSClient, "test_sensors", fake_test_sensors)
    monkeypatch.setattr(SteamOSClient, "fetch_wol_mac", fake_fetch_wol_mac)

    config = await flow.query_device({"host": "203.0.113.10"})
    assert config.mac_address == "aabbccddeeff"


async def test_agent_without_a_readable_mac_leaves_wake_disabled(flow, monkeypatch):
    """Old agent, or a NIC ethtool can't read: no MAC, no wake capability --
    same as today, just discovered instead of typed."""

    async def fake_agent_status(self):
        return 200

    async def fake_fetch_wol_mac(self):
        return ""

    monkeypatch.setattr(SteamOSClient, "agent_status", fake_agent_status)
    monkeypatch.setattr(SteamOSClient, "fetch_wol_mac", fake_fetch_wol_mac)

    config = await flow.query_device({
        "host": "203.0.113.10",
        "enable_hardware_monitoring": "disabled",
    })

    assert config.mac_address == ""
    assert config.broadcast_address == "255.255.255.255"
