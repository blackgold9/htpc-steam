"""Device state machine: the four states, and the wake path's decisions.

These are the load-bearing regressions for Wake-on-LAN, in order of how badly
each failure would present to a user:

1. establish_connection() must not raise when the box is off. If it does,
   PollingDevice.connect() swallows it into `return False` without ever creating
   a poll task — so the integration can never notice the box coming back, and
   Power On is unreachable until the Remote restarts. That bug predates WoL and
   is what made the feature impossible to expose at all.
2. OFF vs UNAVAILABLE must be decided by the TCP probe, not by "the HTTP call
   failed" — the two need opposite remedies.
3. A wake must not claim the box is on, and must be refused when the host is
   demonstrably awake.
"""


from uc_intg_steamos import probe
from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import (
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_WAKING,
    SteamOSDevice,
)
from uc_intg_steamos.driver import SteamOSDriver

MAC = "aa:bb:cc:dd:ee:ff"


class FakeClient:
    """Stands in for SteamOSClient; `healthy` flips the whole box on or off."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.closed = False
        self.system_data = "sensors"
        self.games = [{"appid": 1, "name": "Game"}]

    def ensure_session(self):
        """Sync on the real client too — it only builds the aiohttp session."""

    async def test_agent(self) -> bool:
        return self.healthy

    async def update_system_data(self) -> bool:
        return self.healthy

    async def update_games(self) -> bool:
        return self.healthy

    async def close(self) -> None:
        self.closed = True


def _device(monkeypatch, mac: str = MAC, wol_ok: bool = True) -> SteamOSDevice:
    config = SteamOSConfig(identifier="steamos_test", name="Test", host="192.168.6.193", mac_address=mac)
    device = SteamOSDevice(config, driver=SteamOSDriver())
    # push_update() needs a registered entity/API; the state machine only needs
    # it to be callable.
    monkeypatch.setattr(device, "push_update", lambda: None)
    monkeypatch.setattr("uc_intg_steamos.device.wol.wake_on_lan", _fake_wol(wol_ok))
    return device


def _fake_wol(succeeds: bool):
    calls = []

    async def wake(mac, **kwargs):
        calls.append((mac, kwargs))
        return succeeds

    wake.calls = calls
    return wake


def _probe_result(monkeypatch, result: str) -> None:
    async def fake_probe(host, port, timeout=1.5):
        return result

    monkeypatch.setattr(probe, "probe", fake_probe)


async def test_offline_box_still_starts_the_poll_task(monkeypatch):
    """The dead-poller regression, asserted at the level that actually broke.

    `PollingDevice.connect()` only creates the poll task if
    `establish_connection()` returns without raising; on a raise it logs and
    `return False`. The old code raised for any unreachable box, so a box that
    happened to be off while the Remote (re)connected got no poll loop at all:
    nothing ever probed it again, and Power On stayed unreachable until a Remote
    restart. Asserting "state == OFF" alone would pass even with the bug, since
    the state is set before the raise — so this goes through the real connect().
    """
    device = _device(monkeypatch)
    monkeypatch.setattr("uc_intg_steamos.device.SteamOSClient", lambda cfg: FakeClient(healthy=False))
    _probe_result(monkeypatch, probe.NO_ANSWER)

    assert await device.connect() is True
    try:
        assert device._poll_task is not None and not device._poll_task.done()
        assert device.state == STATE_OFF
    finally:
        await device.disconnect()



async def test_host_up_but_agent_dead_is_unavailable_not_off(monkeypatch):
    """Refused port = awake box. Showing OFF here would offer a wake that cannot
    work; the actual fault is Decky/the plugin."""
    device = _device(monkeypatch)
    monkeypatch.setattr("uc_intg_steamos.device.SteamOSClient", lambda cfg: FakeClient(healthy=False))
    _probe_result(monkeypatch, probe.HOST_UP)

    await device.establish_connection()

    assert device.state == STATE_UNAVAILABLE


async def test_healthy_agent_reaches_on_and_loads_data(monkeypatch):
    device = _device(monkeypatch)
    monkeypatch.setattr("uc_intg_steamos.device.SteamOSClient", lambda cfg: FakeClient(healthy=True))

    await device.establish_connection()

    assert device.state == STATE_ON
    assert device.games == [{"appid": 1, "name": "Game"}]


async def test_wake_sets_waking_not_on(monkeypatch):
    """Packet leaving the socket is not evidence of a wake; only the agent
    answering again is, and that's the probe's job."""
    device = _device(monkeypatch)
    device._state = STATE_OFF
    wol = _fake_wol(True)
    monkeypatch.setattr("uc_intg_steamos.device.wol.wake_on_lan", wol)

    assert await device.wake_on_lan() is True

    assert device.state == STATE_WAKING
    assert wol.calls[0][0] == MAC
    assert wol.calls[0][1]["unicast"] == "192.168.6.193"


async def test_failed_wake_leaves_state_alone(monkeypatch):
    device = _device(monkeypatch)
    device._state = STATE_OFF
    monkeypatch.setattr("uc_intg_steamos.device.wol.wake_on_lan", _fake_wol(False))

    assert await device.wake_on_lan() is False
    assert device.state == STATE_OFF


async def test_wake_is_refused_without_a_mac(monkeypatch):
    """No MAC means no wake capability at all: no packet, no state change."""
    device = _device(monkeypatch, mac="")
    device._state = STATE_OFF
    wol = _fake_wol(True)
    monkeypatch.setattr("uc_intg_steamos.device.wol.wake_on_lan", wol)

    assert device.wol_available is False
    assert await device.wake_on_lan() is False
    assert wol.calls == []
    assert device.state == STATE_OFF


async def test_wake_is_refused_while_the_host_is_awake(monkeypatch):
    """UNAVAILABLE means a live host refusing the port. A magic packet there is
    wasted and sends the user hunting the wrong fault."""
    device = _device(monkeypatch)
    device._state = STATE_UNAVAILABLE
    wol = _fake_wol(True)
    monkeypatch.setattr("uc_intg_steamos.device.wol.wake_on_lan", wol)

    assert await device.wake_on_lan() is False
    assert wol.calls == []


async def test_waking_survives_silence_while_the_box_boots(monkeypatch):
    """A magic packet wakes the NIC long before the agent can answer, so silence
    during a wake is the normal case, not a failure. Reading the first silent
    tick (5s later) as OFF would flip the dashboard to "Box is off — press Power
    On" for the ~50s a box takes to boot, and invite a second pointless wake."""
    device = _device(monkeypatch)
    device._state = STATE_WAKING
    device._wake_deadline = 1e12
    _probe_result(monkeypatch, probe.NO_ANSWER)

    await device._poll_offline()

    assert device.state == STATE_WAKING


async def test_waking_falls_back_to_off_after_the_timeout(monkeypatch):
    """Otherwise a wake that didn't take leaves the UI claiming the box is on
    its way up, forever."""
    device = _device(monkeypatch)
    device._state = STATE_WAKING
    device._wake_deadline = -1.0  # already expired
    _probe_result(monkeypatch, probe.NO_ANSWER)

    await device._poll_offline()

    assert device.state == STATE_OFF


async def test_waking_promotes_to_unavailable_once_the_host_answers(monkeypatch):
    """Host answering mid-wake means the wake worked and only the agent is
    missing (Decky loads slowly after a cold boot) — that is a different fault
    than "still off", and it must not keep offering a wake."""
    device = _device(monkeypatch)
    device._state = STATE_WAKING
    device._wake_deadline = 1e12
    _probe_result(monkeypatch, probe.HOST_UP)

    await device._poll_offline()

    assert device.state == STATE_UNAVAILABLE


async def test_agent_answering_while_waking_reconnects(monkeypatch):
    device = _device(monkeypatch)
    device._state = STATE_WAKING
    device._wake_deadline = 1e12
    _probe_result(monkeypatch, probe.AGENT_UP)
    client = FakeClient(healthy=True)
    monkeypatch.setattr("uc_intg_steamos.device.SteamOSClient", lambda cfg: client)

    await device._poll_offline()

    assert device.state == STATE_ON


async def test_offline_poll_probes_on_the_slow_ladder(monkeypatch):
    """A box that is off must not be probed every 5s tick: only after enough
    ticks to cover RECONNECT_INTERVAL."""
    device = _device(monkeypatch)
    device._state = STATE_OFF
    probed = []

    async def fake_probe(host, port, timeout=1.5):
        probed.append(host)
        return probe.NO_ANSWER

    monkeypatch.setattr(probe, "probe", fake_probe)

    await device._poll_offline()

    assert probed == []


async def test_send_command_requires_a_client(monkeypatch):
    """OFF means no client; commands must report failure instead of raising."""
    device = _device(monkeypatch)
    assert await device.send_command("power_shutdown") is False


async def test_client_is_closed_when_the_box_drops(monkeypatch):
    """A leaked aiohttp session per reconnect is a leak per power cycle."""
    device = _device(monkeypatch)
    client = FakeClient(healthy=True)
    device._client = client

    await device._drop_connection()

    assert client.closed is True


async def test_dead_agent_is_detected_even_with_monitoring_disabled(monkeypatch):
    """The ladder that demotes a silent box used to be driven only by the sensor
    fetch. With `enable_hardware_monitoring` off there was no fetch to fail, so
    the device sat at ON forever — and since only OFF can be woken, a user who
    turned sensors off could never reach Power On again."""
    device = _device(monkeypatch)
    device._config.enable_hardware_monitoring = False
    device._state = STATE_ON
    client = FakeClient(healthy=False)
    device._client = client
    _probe_result(monkeypatch, probe.NO_ANSWER)
    monkeypatch.setattr("uc_intg_steamos.device.MAX_CONSECUTIVE_FAILURES", 2)

    await device._poll_awake()
    assert device.state == STATE_ON, "one failed tick must not demote the box"
    await device._poll_awake()

    assert device.state == STATE_OFF
    assert client.closed is True


async def test_never_claims_on_without_a_live_client(monkeypatch):
    """The probe reaching the agent's port is not the same as /health answering.

    ON is what every entity reads as "the numbers I'm showing are fresh", so a
    state of ON with no client — which is what a probe-only promotion produces —
    repaints the last pre-crash temperatures as live and offers a game to launch
    that cannot start. Whatever the probe concluded, ON has to be earned by an
    actual connection.
    """
    device = _device(monkeypatch)
    monkeypatch.setattr("uc_intg_steamos.device.SteamOSClient", lambda cfg: FakeClient(healthy=False))
    _probe_result(monkeypatch, probe.AGENT_UP)

    await device.establish_connection()

    assert device.state != STATE_ON
    assert device._client is None
