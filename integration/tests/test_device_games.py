"""Device-level tests for the Game Launcher's data plumbing: the appid<->name
lookup and the launch_game -> send_command routing. Entity command-handling
itself isn't unit tested (see test_entities_construct.py's docstring) since
ucapi_framework's update_attributes() no-ops without a full configured-entity
API -- these test the plain-Python device methods it delegates to instead.
"""

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import SteamOSDevice
from uc_intg_steamos.driver import SteamOSDriver


def _device() -> SteamOSDevice:
    driver = SteamOSDriver()
    config = SteamOSConfig(identifier="steamos_test", name="Test SteamOS", host="192.168.6.193")
    return SteamOSDevice(config, driver=driver)


async def test_appid_for_game_found():
    device = _device()
    device._games = [
        {"appid": 1686940, "name": "Bopl Battle", "last_played": 1787507429},
        {"appid": 2338140, "name": "Dokapon Kingdom: Connect", "last_played": 1786754345},
    ]
    assert device.appid_for_game("Bopl Battle") == 1686940


async def test_appid_for_game_not_found():
    device = _device()
    device._games = [{"appid": 100, "name": "Some Game", "last_played": 1}]
    assert device.appid_for_game("Nonexistent Game") is None


async def test_games_property_reflects_internal_state():
    device = _device()
    assert device.games == []
    device._games = [{"appid": 100, "name": "Some Game", "last_played": 1}]
    assert device.games == [{"appid": 100, "name": "Some Game", "last_played": 1}]


async def test_launch_game_sends_launch_game_command():
    device = _device()
    calls = []

    async def fake_send_command(command):
        calls.append(command)
        return True

    device.send_command = fake_send_command
    result = await device.launch_game(1686940)
    assert result is True
    assert calls == ["launch_game:1686940"]
