"""
SteamOS HTPC device implementation using PollingDevice.

Four device states, because Wake-on-LAN introduces a case this integration
never had to model: a box that has an IP and is simply not answering.

    ON           the agent is answering /health and we're polling it
    OFF          nothing answered the TCP probe — asleep, powered off, or
                 unplugged. This is the state a magic packet is for.
    WAKING       a magic packet was sent; we're watching for the box to come
                 back, and fall back to OFF after WAKE_TIMEOUT_S.
    UNAVAILABLE  the *host* answered with a refusal — it is awake, but the
                 agent isn't listening (Decky not loaded, plugin crashed,
                 wrong port). Waking it is the wrong action there, which is
                 exactly why this is not folded into OFF.

Two structural notes, both load-bearing:

1. `establish_connection()` MUST NOT raise. `PollingDevice.connect()` aborts
   (no poll task, no retry, forever) when it does — so a box that happened to
   be off while the Remote (re)connected stayed permanently unrecoverable
   without a Remote restart. It now reports the state it found instead, which
   is the only way a Power On affordance can ever be reachable.

2. "OFF" is inferred from a TCP probe (`probe.py`), not from a failed
   `/health`. A failed HTTP request cannot distinguish "box asleep" from
   "box awake, agent dead"; an unanswered TCP connect can.

:license: MIT
"""

import base64
import logging
import os
import time
from typing import Any

from ucapi_framework import PollingDevice

from uc_intg_steamos import probe, wol
from uc_intg_steamos.client import SteamOSClient, SystemData
from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.const import AGENT_PORT, POLL_INTERVAL

_LOG = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
RECONNECT_INTERVAL = 30

#: While WAKING, probe every poll tick instead of every RECONNECT_INTERVAL: a
#: booting box is back within 20-60s and the user is staring at the Remote.
WAKE_TIMEOUT_S = 120

STATE_ON = "ON"
STATE_OFF = "OFF"
STATE_WAKING = "WAKING"
STATE_UNAVAILABLE = "UNAVAILABLE"


class SteamOSDevice(PollingDevice):
    """SteamOS HTPC device using polling for data refresh."""

    def __init__(self, device_config: SteamOSConfig, **kwargs: Any) -> None:
        super().__init__(device_config, poll_interval=POLL_INTERVAL, **kwargs)
        self._config = device_config
        self._client: SteamOSClient | None = None
        self._state: str = STATE_UNAVAILABLE
        self._system_data = SystemData()
        self._current_view: str = "System Overview"
        self._consecutive_failures: int = 0
        self._reconnect_poll_count: int = 0
        self._icon_cache: dict[str, str] = {}
        self._games: list[dict[str, Any]] = []
        self._wake_deadline: float = 0.0

    @property
    def identifier(self) -> str:
        return self._config.identifier

    @property
    def name(self) -> str:
        return self._config.name

    @property
    def address(self) -> str:
        return self._config.host

    @property
    def log_id(self) -> str:
        return f"[{self.name}]"

    @property
    def state(self) -> str:
        return self._state

    @property
    def config(self) -> SteamOSConfig:
        return self._config

    @property
    def system_data(self) -> SystemData:
        return self._system_data

    @property
    def current_view(self) -> str:
        return self._current_view

    def set_current_view(self, view: str) -> None:
        self._current_view = view

    @property
    def games(self) -> list[dict[str, Any]]:
        return self._games

    @property
    def wol_available(self) -> bool:
        """WoL is opt-in: no MAC configured means no wake capability at all."""
        return bool(self._config.mac_address and wol.validate_mac(self._config.mac_address))

    @property
    def can_wake(self) -> bool:
        """Wake only makes sense when the host itself isn't answering.

        In UNAVAILABLE the box is demonstrably awake and refusing the port, so
        a magic packet is wasted and misleading — the fix there is Decky, not WoL.
        """
        return self.wol_available and self._state in (STATE_OFF, STATE_WAKING)

    def appid_for_game(self, name: str) -> int | None:
        for game in self._games:
            if game["name"] == name:
                return game["appid"]
        return None

    async def launch_game(self, appid: int) -> bool:
        return await self.send_command(f"launch_game:{appid}")

    async def wake_on_lan(self) -> bool:
        """Fire a magic packet and start watching for the box to come back.

        Success means "the packet left the socket", not "the box woke" — only
        the agent answering again is evidence of that. So we deliberately do
        NOT claim ON; we go to WAKING and let the probe decide.
        """
        if not self.can_wake:
            _LOG.info("%s Wake refused: WoL unavailable (state=%s)", self.log_id, self._state)
            return False

        sent = await wol.wake_on_lan(
            self._config.mac_address,
            broadcast=self._config.broadcast_address,
            port=self._config.wol_port,
            unicast=self._config.host,
        )
        if not sent:
            self.push_update()
            return False

        self._state = STATE_WAKING
        self._wake_deadline = time.monotonic() + WAKE_TIMEOUT_S
        self._reconnect_poll_count = 0
        self.push_update()
        return True

    def get_icon_base64(self, icon_filename: str) -> str:
        if icon_filename in self._icon_cache:
            return self._icon_cache[icon_filename]

        script_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(script_dir, "icons", icon_filename)

        if not os.path.exists(icon_path):
            fallback = os.path.join(script_dir, "icons", "system_overview.png")
            if os.path.exists(fallback):
                icon_path = fallback
            else:
                return ""

        try:
            with open(icon_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
                result = f"data:image/png;base64,{data}"
                self._icon_cache[icon_filename] = result
                return result
        except Exception:
            return ""

    async def establish_connection(self) -> None:
        """Connect if the agent answers; otherwise record why not.

        Never raises. Raising here is what used to strand a powered-off box:
        `PollingDevice.connect()` reads a raised exception as "no connection,
        no poll task", leaving the integration with no mechanism to notice the
        box coming back.
        """
        if await self._attempt_connect():
            self.push_update()
            return

        await self._drop_connection()
        if await self._classify_offline_state(startup=True) == probe.AGENT_UP:
            # /health said no but the agent's port accepted a connection a
            # moment later — the agent was mid-startup. Try for real rather
            # than settling for a state we can't back up with data.
            await self._attempt_connect()
        self.push_update()

    async def _attempt_connect(self) -> bool:
        """Build a client and bring the device to ON if the agent answers.

        Leaves no client behind on failure: a half-built one would keep an
        aiohttp session open per retry and make `send_command` report results
        from a box we just decided is unreachable.
        """
        await self._drop_connection()
        self._client = SteamOSClient(self._config)
        # update_games()/update_system_data() return False with no session,
        # which would read as "agent is down" on a perfectly live box.
        self._client.ensure_session()

        if not await self._client.test_agent():
            await self._drop_connection()
            return False

        if self._config.enable_hardware_monitoring and await self._client.update_system_data():
            self._system_data = self._client.system_data
        if await self._client.update_games():
            self._games = self._client.games
        self._state = STATE_ON
        self._consecutive_failures = 0
        _LOG.info("%s Connected to SteamOS agent", self.log_id)
        return True

    async def _classify_offline_state(self, startup: bool = False) -> str:
        """Probe the host and settle into OFF or UNAVAILABLE; returns the probe.

        Deliberately does not claim ON when the probe reaches the agent port:
        ON means "we have a client and fresh data", and a state that promises
        that with no client is a lie the entities would render as stale sensor
        numbers. The caller gets AGENT_UP back and reconnects for real.
        """
        result = await probe.probe(self._config.host, AGENT_PORT)
        if result == probe.AGENT_UP:
            return result

        previous = self._state
        self._state = STATE_UNAVAILABLE if result == probe.HOST_UP else STATE_OFF
        if previous != self._state:
            _LOG.info(
                "%s %s: %s",
                self.log_id,
                self._state,
                "host answered but refused the agent port" if result == probe.HOST_UP else f"no answer from {self._config.host}",
            )
        if startup:
            _LOG.warning("%s SteamOS agent unreachable at %s", self.log_id, self._config.host)
        return result

    async def poll_device(self) -> None:
        if self._state == STATE_ON:
            await self._poll_awake()
        else:
            await self._poll_offline()

    async def _poll_awake(self) -> None:
        if not self._client:
            self._state = STATE_UNAVAILABLE
            self.push_update()
            return

        games_ok = await self._client.update_games()
        if games_ok:
            self._games = self._client.games

        # The failure ladder has to run off a fetch that exists whatever the
        # `enable_hardware_monitoring` toggle says. It used to be driven purely
        # by the sensor fetch, so with monitoring off a dead agent was never
        # noticed: the device sat at ON forever, and since OFF is the only
        # wakeable state, a user who switched sensors off could never reach
        # Power On again without re-pairing. /games is polled unconditionally
        # (the Game Launcher entity needs it), so it serves as liveness.
        if self._config.enable_hardware_monitoring:
            alive = await self._client.update_system_data()
            if alive:
                self._system_data = self._client.system_data
        else:
            alive = games_ok

        if alive:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            _LOG.warning(
                "%s Data fetch failure %d/%d",
                self.log_id,
                self._consecutive_failures,
                MAX_CONSECUTIVE_FAILURES,
            )
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                _LOG.error("%s Max failures reached; probing the host", self.log_id)
                await self._drop_connection()
                if await self._classify_offline_state() == probe.AGENT_UP:
                    await self._attempt_connect()
                self.push_update()
                return

        self.push_update()

    async def _poll_offline(self) -> None:
        """Box off/asleep/agent-dead: probe on a schedule, connect on evidence."""
        self._reconnect_poll_count += 1

        waking = self._state == STATE_WAKING
        if waking and time.monotonic() > self._wake_deadline:
            _LOG.info("%s No sign of life %ds after the magic packet; back to OFF", self.log_id, WAKE_TIMEOUT_S)
            self._state = STATE_OFF
            self._wake_deadline = 0.0
            self._reconnect_poll_count = 0
            self.push_update()
            return

        # While WAKING, probe every tick — the user is waiting. Otherwise fall
        # back to the slow 30s ladder so an off box isn't hammered.
        interval = POLL_INTERVAL if waking else RECONNECT_INTERVAL
        polls_needed = max(1, interval // max(POLL_INTERVAL, 1))
        if self._reconnect_poll_count < polls_needed:
            return
        self._reconnect_poll_count = 0

        result = await probe.probe(self._config.host, AGENT_PORT)

        if result == probe.AGENT_UP:
            _LOG.info("%s Agent is answering again", self.log_id)
            if not await self._attempt_connect():
                # Reached the port but /health didn't answer — the agent is
                # mid-startup or wedged. Stay offline and let the ladder retry.
                await self._drop_connection()
                self._state = STATE_UNAVAILABLE
            self.push_update()
            return

        if result == probe.HOST_UP:
            # Something is awake and refusing the port. If we just woke it, the
            # wake worked and only the agent is missing — and Decky can take
            # 30s+ to load a plugin after a cold boot, so this keeps probing.
            if self._state != STATE_UNAVAILABLE:
                _LOG.info("%s Host is awake, agent still not answering", self.log_id)
                self._state = STATE_UNAVAILABLE
                self.push_update()
            return

        # Silence. While a wake is in flight that is simply the box still
        # booting — the NIC answers long before the agent does — so it must not
        # be read as failure yet; only the deadline may give up on the wake.
        if waking:
            return
        if self._state != STATE_OFF:
            self._state = STATE_OFF
            self.push_update()

    async def _drop_connection(self) -> None:
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

    async def send_command(self, command: str) -> bool:
        if not self._client:
            return False
        return await self._client.send_command(command)

    async def disconnect(self) -> None:
        await self._drop_connection()
        self._state = STATE_UNAVAILABLE
        await super().disconnect()
