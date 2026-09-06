"""
SteamOS HTPC device implementation using PollingDevice.

:license: MIT
"""

import base64
import logging
import os
from typing import Any

from ucapi_framework import PollingDevice

from uc_intg_steamos.client import SteamOSClient, SystemData
from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.const import POLL_INTERVAL

_LOG = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 5
RECONNECT_INTERVAL = 30


class SteamOSDevice(PollingDevice):
    """SteamOS HTPC device using polling for data refresh."""

    def __init__(self, device_config: SteamOSConfig, **kwargs: Any) -> None:
        super().__init__(device_config, poll_interval=POLL_INTERVAL, **kwargs)
        self._config = device_config
        self._client: SteamOSClient | None = None
        self._state: str = "UNAVAILABLE"
        self._system_data = SystemData()
        self._current_view: str = "System Overview"
        self._consecutive_failures: int = 0
        self._reconnect_poll_count: int = 0
        self._icon_cache: dict[str, str] = {}
        self._games: list[dict[str, Any]] = []

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

    def appid_for_game(self, name: str) -> int | None:
        for game in self._games:
            if game["name"] == name:
                return game["appid"]
        return None

    async def launch_game(self, appid: int) -> bool:
        return await self.send_command(f"launch_game:{appid}")

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

    async def establish_connection(self) -> SteamOSClient:
        self._client = SteamOSClient(self._config)
        if not await self._client.connect():
            await self._client.close()
            self._client = None
            raise ConnectionError(f"Cannot connect to SteamOS agent at {self._config.host}")

        _LOG.info("%s Connected to SteamOS agent", self.log_id)
        self._state = "ON"
        self._consecutive_failures = 0

        if self._config.enable_hardware_monitoring:
            self._system_data = self._client.system_data

        if await self._client.update_games():
            self._games = self._client.games

        self.push_update()
        return self._client

    async def poll_device(self) -> None:
        if self._state == "UNAVAILABLE":
            self._reconnect_poll_count += 1
            polls_needed = RECONNECT_INTERVAL // max(POLL_INTERVAL, 1)
            if self._reconnect_poll_count >= max(polls_needed, 3):
                self._reconnect_poll_count = 0
                await self._try_reconnect()
            return

        if not self._client:
            return

        if await self._client.update_games():
            self._games = self._client.games

        if self._config.enable_hardware_monitoring:
            if await self._client.update_system_data():
                self._system_data = self._client.system_data
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
                    _LOG.error("%s Max failures reached, will attempt reconnection", self.log_id)
                    self._state = "UNAVAILABLE"
                    self._reconnect_poll_count = 0
                    self.push_update()
                    return

        self.push_update()

    async def _try_reconnect(self) -> bool:
        _LOG.info("%s Attempting reconnection", self.log_id)
        if self._client:
            try:
                await self._client.close()
            except Exception:
                pass
            self._client = None

        try:
            await self.establish_connection()
            _LOG.info("%s Reconnected successfully", self.log_id)
            return True
        except Exception as err:
            _LOG.warning("%s Reconnection failed: %s", self.log_id, err)
            return False

    async def send_command(self, command: str) -> bool:
        if not self._client:
            return False
        return await self._client.send_command(command)

    async def power_on_wol(self) -> bool:
        if self._client:
            return await self._client.power_on_wol()
        temp_client = SteamOSClient(self._config)
        return await temp_client.power_on_wol()

    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None
        self._state = "UNAVAILABLE"
        await super().disconnect()
