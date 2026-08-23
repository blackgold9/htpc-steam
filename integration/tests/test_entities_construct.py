"""Smoke test: construct the driver and every entity type together against
the real installed ucapi/ucapi-framework packages, catching constructor
signature drift that import-only checks would miss. No network I/O.
"""

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import SteamOSDevice
from uc_intg_steamos.driver import SteamOSDriver
from uc_intg_steamos.entities.media_player import SteamOSMediaPlayer
from uc_intg_steamos.entities.remote import SteamOSRemote
from uc_intg_steamos.entities.sensor import create_sensors


async def test_driver_and_all_entities_construct_without_error():
    driver = SteamOSDriver()
    assert driver.api is not None

    config = SteamOSConfig(
        identifier="steamos_test",
        name="Test SteamOS",
        host="192.168.6.193",
        enable_hardware_monitoring=True,
        temperature_unit="celsius",
        mac_address="",
        auth_token="",
    )
    device = SteamOSDevice(config, driver=driver)
    assert device.identifier == "steamos_test"
    assert device.name == "Test SteamOS"

    remote = SteamOSRemote(config, device)
    assert remote.id == "remote.steamos_test"

    media_player = SteamOSMediaPlayer(config, device)
    assert media_player.id == "media_player.steamos_test"

    sensors = create_sensors(config, device)
    assert len(sensors) == 11


async def test_entities_construct_with_wol_enabled():
    driver = SteamOSDriver()
    config = SteamOSConfig(
        identifier="steamos_wol", name="WoL Test", host="10.0.0.5", mac_address="AA:BB:CC:DD:EE:FF"
    )
    device = SteamOSDevice(config, driver=driver)
    remote = SteamOSRemote(config, device)
    assert remote.id == "remote.steamos_wol"
