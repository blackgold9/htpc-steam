"""Power/wake behaviour of the two entities the user actually touches.

Construction is already smoke-tested elsewhere; what matters here is the
decisions these entities make, each of which has a way to be wrong that a
constructor check cannot see:

- `remote` TOGGLE has to pick wake or shutdown from the *device* state, and
  picking wrong either shuts down a running box or fires a packet at one that
  is already on.
- OFF on `remote` means `power_shutdown`, ON means a magic packet sent
  locally — never an agent command, since the agent is unreachable in exactly
  the state ON exists for.
- The "Wake-on-LAN" monitoring view has to keep three situations distinct:
  the agent couldn't read the NIC, the NIC can't do WoL, and the NIC can but
  isn't armed. Only the last is fixable with `ethtool`, so collapsing "unknown"
  into "unsupported" tells the user their hardware is incapable.
"""

from ucapi import StatusCodes, media_player, remote

from uc_intg_steamos.client import SystemData
from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_WAKING,
)
from uc_intg_steamos.entities.media_player import SteamOSMediaPlayer
from uc_intg_steamos.entities.remote import SteamOSRemote

MAC = "aa:bb:cc:dd:ee:ff"


class _FakeDevice:
    """Just the surface the entities use, with the calls recorded."""

    def __init__(self, state: str = STATE_OFF, wol_available: bool = True, wake_ok: bool = True) -> None:
        self.state = state
        self.wol_available = wol_available
        self.wake_ok = wake_ok
        self.system_data = SystemData()
        self.current_view = "Wake-on-LAN"
        self.log_id = "[test]"
        self.config = SteamOSConfig(identifier="t", name="T", host="10.0.0.1", mac_address=MAC)
        self.commands: list[str] = []
        self.wakes = 0

    async def send_command(self, command: str) -> bool:
        self.commands.append(command)
        return True

    async def wake_on_lan(self) -> bool:
        self.wakes += 1
        return self.wake_ok

    def push_update(self) -> None:
        """Entities call this after a command that changes device state."""

    def get_icon_base64(self, _name: str) -> str:
        return ""


def _capture(entity) -> dict:
    """Route the entity's updates into a dict we can assert on."""
    seen: dict = {}
    entity.update = lambda attrs, **kwargs: seen.update(attrs)
    return seen


async def _remote(device: _FakeDevice) -> SteamOSRemote:
    entity = SteamOSRemote.__new__(SteamOSRemote)
    entity._device = device
    return entity


async def _media_player(device: _FakeDevice) -> SteamOSMediaPlayer:
    entity = SteamOSMediaPlayer.__new__(SteamOSMediaPlayer)
    entity._device = device
    return entity


# --- remote: ON/OFF/TOGGLE -------------------------------------------------


async def test_remote_on_wakes_locally_rather_than_via_the_agent():
    device = _FakeDevice(state=STATE_OFF)
    entity = await _remote(device)

    code = await entity._handle_command(entity, remote.Commands.ON, None)

    assert code == StatusCodes.OK
    assert device.wakes == 1
    # The whole point: there is no power_on agent command to send.
    assert device.commands == []


async def test_remote_on_reports_failure_when_no_mac_is_configured():
    """Must be a non-OK status: a silent success would leave the Remote showing
    a pressed button and a box that never comes up."""
    device = _FakeDevice(state=STATE_OFF, wol_available=False)
    entity = await _remote(device)

    code = await entity._handle_command(entity, remote.Commands.ON, None)

    assert code == StatusCodes.SERVER_ERROR
    assert device.wakes == 0


async def test_remote_off_shuts_down_through_the_agent():
    device = _FakeDevice(state=STATE_ON)
    entity = await _remote(device)

    code = await entity._handle_command(entity, remote.Commands.OFF, None)

    assert code == StatusCodes.OK
    assert device.commands == ["power_shutdown"]
    assert device.wakes == 0


async def test_remote_toggle_shuts_down_when_awake_and_wakes_when_asleep():
    """The physical POWER button lands here. Inverting the branch would either
    put a running box down or waste a packet, and nothing else exercises it."""
    awake = _FakeDevice(state=STATE_ON)
    await (await _remote(awake))._handle_command(awake, remote.Commands.TOGGLE, None)
    assert awake.commands == ["power_shutdown"]
    assert awake.wakes == 0

    asleep = _FakeDevice(state=STATE_OFF)
    await (await _remote(asleep))._handle_command(asleep, remote.Commands.TOGGLE, None)
    assert asleep.wakes == 1
    assert asleep.commands == []


async def test_remote_waking_still_offers_a_retry():
    """`remote` has no transitional state; mapping WAKING to ON would hide the
    Power On button precisely while the user is waiting."""
    device = _FakeDevice(state=STATE_WAKING)
    entity = await _remote(device)
    seen = _capture(entity)

    await entity.sync_state()

    assert seen[remote.Attributes.STATE] == remote.States.OFF


async def test_remote_reports_unavailable_not_off_when_the_box_is_awake():
    device = _FakeDevice(state=STATE_UNAVAILABLE)
    entity = await _remote(device)
    seen = _capture(entity)

    await entity.sync_state()

    assert seen[remote.Attributes.STATE] == remote.States.UNAVAILABLE


# --- media player: offline presentation + WoL view ------------------------
async def test_dashboard_while_waking_shows_no_stale_sensor_numbers():
    """If WAKING fell through to the normal data path it would repaint the last
    pre-sleep temperatures as though they were live, and the user could not tell
    the box had not actually come back."""
    device = _FakeDevice(state=STATE_WAKING)
    device.system_data = SystemData()
    device.system_data.cpu_temp = 42.0
    device.current_view = "System Overview"
    entity = await _media_player(device)
    seen = _capture(entity)

    await entity.sync_state()

    assert seen[media_player.Attributes.STATE] == media_player.States.STANDBY
    assert "Waking" in seen[media_player.Attributes.MEDIA_ARTIST]
    assert "42" not in str(seen.get(media_player.Attributes.MEDIA_TITLE, ""))


async def test_dashboard_off_points_at_the_wake_path_when_a_mac_exists():
    device = _FakeDevice(state=STATE_OFF, wol_available=True)
    entity = await _media_player(device)
    seen = _capture(entity)

    await entity.sync_state()

    assert seen[media_player.Attributes.STATE] == media_player.States.STANDBY
    assert "Power On" in seen[media_player.Attributes.MEDIA_ARTIST]


async def test_dashboard_off_tells_the_user_to_use_the_button_when_not():
    device = _FakeDevice(state=STATE_OFF, wol_available=False)
    entity = await _media_player(device)
    seen = _capture(entity)

    await entity.sync_state()

    assert "MAC" in seen[media_player.Attributes.MEDIA_ARTIST]


async def test_dashboard_on_wakes_the_box():
    device = _FakeDevice(state=STATE_OFF)
    entity = await _media_player(device)

    await entity._handle_command(entity, media_player.Commands.ON, None)

    assert device.wakes == 1


def _wol_data(**overrides) -> SystemData:
    data = SystemData()
    data.wol_present = True
    data.wol_interface = "enp9s0"
    data.wol_driver = "r8169"
    data.wol_supported = True
    for key, value in overrides.items():
        setattr(data, f"wol_{key}", value)
    return data


async def test_wol_view_says_unknown_rather_than_unsupported_when_unreadable():
    """The live box lands here: an unprivileged ethtool reports nothing about
    wake, and claiming the NIC is incapable would send the user chasing
    firmware for no reason."""
    device = _FakeDevice(state=STATE_ON)
    entity = await _media_player(device)

    attrs = entity._format_view_data("Wake-on-LAN", SystemData())

    assert "Could not read NIC state" in attrs[media_player.Attributes.MEDIA_ARTIST]
    assert "NOT armed" not in attrs[media_player.Attributes.MEDIA_TITLE]
    assert "does not advertise" not in attrs[media_player.Attributes.MEDIA_TITLE]


async def test_wol_view_names_the_fix_when_armed_is_all_that_is_missing():
    device = _FakeDevice(state=STATE_ON)
    entity = await _media_player(device)

    attrs = entity._format_view_data("Wake-on-LAN", _wol_data(supported=True, enabled=False))

    title = attrs[media_player.Attributes.MEDIA_TITLE]
    assert "NOT armed" in title
    assert "sudo ethtool -s enp9s0 wol g" in title


async def test_wol_view_flags_a_filter_armed_nic_the_kernel_wont_wake():
    """Both gates have to be open; reporting only the ethtool flag would call
    this armed and then never wake."""
    device = _FakeDevice(state=STATE_ON)
    entity = await _media_player(device)

    attrs = entity._format_view_data("Wake-on-LAN", _wol_data(enabled=True, may_wakeup=False))

    assert "no wakeup source" in attrs[media_player.Attributes.MEDIA_TITLE]

    armed = entity._format_view_data("Wake-on-LAN", _wol_data(enabled=True, may_wakeup=True))
    assert armed[media_player.Attributes.MEDIA_TITLE].endswith("armed")


async def test_wol_view_only_says_unsupported_when_the_nic_said_so():
    device = _FakeDevice(state=STATE_ON)
    entity = await _media_player(device)

    attrs = entity._format_view_data("Wake-on-LAN", _wol_data(supported=False, enabled=False))

    assert "does not advertise Wake-on-LAN" in attrs[media_player.Attributes.MEDIA_TITLE]


def test_every_monitoring_view_is_constructible_and_iconed():
    """A view added to MONITORING_VIEWS without an icon or a formatter case
    shows up as a blank page on the Remote; the fallbacks make that silent."""
    from uc_intg_steamos.const import MONITORING_VIEWS
    from uc_intg_steamos.entities.media_player import SOURCE_ICONS

    device = _FakeDevice(state=STATE_ON)
    entity = SteamOSMediaPlayer.__new__(SteamOSMediaPlayer)
    entity._device = device

    for view in MONITORING_VIEWS:
        assert view in SOURCE_ICONS, view
        attrs = entity._format_view_data(view, _wol_data())
        assert media_player.Attributes.MEDIA_TITLE in attrs, view
