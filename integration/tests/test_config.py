from uc_intg_steamos.config import SteamOSConfig


def test_wol_enabled_reflects_mac_address():
    assert SteamOSConfig(mac_address="").wol_enabled is False
    assert SteamOSConfig(mac_address="AA:BB:CC:DD:EE:FF").wol_enabled is True


def test_convert_temperature_celsius_passthrough():
    config = SteamOSConfig(temperature_unit="celsius")
    assert config.convert_temperature(100.0) == 100.0
    assert config.temperature_symbol() == "°C"


def test_convert_temperature_fahrenheit():
    config = SteamOSConfig(temperature_unit="fahrenheit")
    assert config.convert_temperature(0.0) == 32.0
    assert config.convert_temperature(100.0) == 212.0
    assert config.temperature_symbol() == "°F"


def test_defaults():
    config = SteamOSConfig()
    assert config.auth_token == ""
    assert config.enable_hardware_monitoring is True
    assert config.temperature_unit == "celsius"
