"""
HTTP client for the UC SteamOS Agent (health/command/sensors on one port).

Replaces upstream's split LibreHardwareMonitor-tree-walker + separate Windows
agent client with a single flat-JSON consumer, since our agent (plugin/) owns
both commands and sensors on one port. See docs/protocol.md for the schema
this parses.

:license: MIT
"""

import asyncio
import logging
from typing import Any

import aiohttp
from wakeonlan import send_magic_packet

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.const import AGENT_PORT

_LOG = logging.getLogger(__name__)


class SystemData:
    """Parsed hardware sensor data from the agent's /sensors endpoint."""

    def __init__(self) -> None:
        self.cpu_temp: float | None = None
        self.cpu_load: float | None = None
        self.cpu_clock: float | None = None
        self.cpu_power: float | None = None
        self.gpu_temp: float | None = None
        self.gpu_load: float | None = None
        self.memory_used: float | None = None
        self.memory_total: float | None = None
        self.storage_used: float | None = None
        self.storage_total: float | None = None
        self.storage_used_percent: float | None = None
        self.storage_temp: float | None = None
        self.network_up: float | None = None  # Mbps
        self.network_down: float | None = None  # Mbps
        self.motherboard_temp_avg: float | None = None
        self.motherboard_temp_max: float | None = None
        self.fan_speeds: list[float] = []
        self.has_dedicated_gpu: bool = False
        self.detected_cpu_name: str = "CPU"
        self.detected_gpu_name: str = "GPU"
        self.battery_present: bool = False
        self.battery_percent: float | None = None
        self.battery_charging: bool | None = None
        self.battery_power: float | None = None
        self.last_updated: float = 0.0


def parse_sensor_data(raw: dict[str, Any]) -> SystemData:
    """Parse the agent's flat /sensors JSON (docs/protocol.md) into SystemData."""
    sd = SystemData()

    cpu = raw.get("cpu") or {}
    sd.detected_cpu_name = cpu.get("name") or "CPU"
    sd.cpu_temp = cpu.get("temp_c")
    sd.cpu_load = cpu.get("load_pct")
    sd.cpu_clock = cpu.get("clock_mhz")
    sd.cpu_power = cpu.get("power_w")

    gpu = raw.get("gpu") or {}
    sd.detected_gpu_name = gpu.get("name") or "GPU"
    sd.gpu_temp = gpu.get("temp_c")
    sd.gpu_load = gpu.get("load_pct")
    sd.has_dedicated_gpu = bool(gpu.get("has_dedicated_gpu"))

    memory = raw.get("memory") or {}
    sd.memory_used = memory.get("used_gb")
    sd.memory_total = memory.get("total_gb")

    storage = raw.get("storage") or {}
    sd.storage_used = storage.get("used_gb")
    sd.storage_total = storage.get("total_gb")
    sd.storage_used_percent = storage.get("used_pct")
    sd.storage_temp = storage.get("temp_c")

    network = raw.get("network") or {}
    up_kbps = network.get("up_kbps")
    down_kbps = network.get("down_kbps")
    sd.network_up = up_kbps / 1000 if up_kbps is not None else None
    sd.network_down = down_kbps / 1000 if down_kbps is not None else None

    motherboard = raw.get("motherboard") or {}
    sd.motherboard_temp_avg = motherboard.get("temp_avg_c")
    sd.motherboard_temp_max = motherboard.get("temp_max_c")

    sd.fan_speeds = [f["rpm"] for f in raw.get("fans", []) if f.get("rpm") is not None]

    battery = raw.get("battery") or {}
    sd.battery_present = bool(battery.get("present"))
    sd.battery_percent = battery.get("percent")
    sd.battery_charging = battery.get("charging")
    sd.battery_power = battery.get("power_w")

    return sd


def parse_games_data(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the agent's /games JSON (docs/protocol.md) into a list of
    {"appid": int, "name": str, "last_played": int} dicts, most recent
    first (the agent already sorts them; this just guards against a
    malformed entry breaking the whole list)."""
    games = raw.get("games") or []
    return [g for g in games if isinstance(g, dict) and g.get("appid") is not None and g.get("name")]


def _count_sensor_fields(data: Any) -> int:
    """Rough count of non-null leaf sensor values, for setup-time feedback."""
    count = 0
    if isinstance(data, dict):
        for value in data.values():
            count += _count_sensor_fields(value)
    elif isinstance(data, list):
        count += len(data)
    elif data is not None:
        count += 1
    return count


class SteamOSClient:
    """Client for the SteamOS agent's unified command/sensor HTTP API."""

    FIRE_AND_FORGET_COMMANDS = {"power_sleep", "power_hibernate", "power_shutdown", "power_restart"}

    def __init__(self, config: SteamOSConfig) -> None:
        self._config = config
        self._session: aiohttp.ClientSession | None = None
        self._system_data = SystemData()
        self._games: list[dict[str, Any]] = []

    @property
    def system_data(self) -> SystemData:
        return self._system_data

    @property
    def games(self) -> list[dict[str, Any]]:
        return self._games

    def _headers(self) -> dict[str, str]:
        if self._config.auth_token:
            return {"X-UC-Token": self._config.auth_token}
        return {}

    async def connect(self) -> bool:
        if not self._session:
            connector = aiohttp.TCPConnector(limit=3)
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10, connect=5),
                connector=connector,
                headers=self._headers(),
            )
        if self._config.enable_hardware_monitoring:
            return await self.update_system_data()
        return await self.test_agent()

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def agent_status(self) -> int | None:
        """HTTP status from /health, or None if the host wasn't reachable at all.

        Setup uses the distinction to tell "wrong IP / agent not running" apart
        from "agent is there but rejected the auth token" (401) -- otherwise a
        mistyped token reads as an unreachable host, which sends people
        debugging the wrong thing entirely.
        """
        session = self._session
        close_after = False
        if not session:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5), headers=self._headers())
            close_after = True
        try:
            url = f"http://{self._config.host}:{AGENT_PORT}/health"
            async with session.get(url) as resp:
                return resp.status
        except Exception:
            return None
        finally:
            if close_after:
                await session.close()

    async def test_agent(self) -> bool:
        return await self.agent_status() == 200

    async def test_sensors(self) -> dict[str, Any]:
        """Test-connect to /sensors during setup; returns success + a rough value count."""
        session = self._session
        close_after = False
        if not session:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10), headers=self._headers())
            close_after = True
        try:
            url = f"http://{self._config.host}:{AGENT_PORT}/sensors"
            async with session.get(url) as resp:
                if resp.status != 200:
                    return {"success": False, "error": f"HTTP {resp.status}"}
                data = await resp.json()
                return {"success": True, "sensor_count": _count_sensor_fields(data)}
        except aiohttp.ClientConnectorError:
            return {"success": False, "error": f"Connection refused at {self._config.host}:{AGENT_PORT}"}
        except Exception as err:
            return {"success": False, "error": str(err)}
        finally:
            if close_after:
                await session.close()

    async def update_system_data(self) -> bool:
        if not self._session:
            return False
        try:
            url = f"http://{self._config.host}:{AGENT_PORT}/sensors"
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                raw = await resp.json()
        except Exception as err:
            _LOG.debug("Sensor fetch failed: %s", err)
            return False

        self._system_data = parse_sensor_data(raw)
        return True

    async def update_games(self) -> bool:
        """Independent of hardware monitoring -- the Game Launcher entity
        needs this regardless of whether sensor polling is enabled."""
        if not self._session:
            return False
        try:
            url = f"http://{self._config.host}:{AGENT_PORT}/games"
            async with self._session.get(url) as resp:
                resp.raise_for_status()
                raw = await resp.json()
        except Exception as err:
            _LOG.debug("Games fetch failed: %s", err)
            return False

        self._games = parse_games_data(raw)
        return True

    async def send_command(self, command: str) -> bool:
        if not self._session:
            return False
        url = f"http://{self._config.host}:{AGENT_PORT}/command"
        if command in self.FIRE_AND_FORGET_COMMANDS:
            return await self._send_fire_and_forget(url, command)
        try:
            async with self._session.post(url, json={"command": command}) as resp:
                return resp.status == 200
        except Exception as err:
            _LOG.debug("Command '%s' failed: %s", command, err)
            return False

    async def _send_fire_and_forget(self, url: str, command: str) -> bool:
        try:
            timeout = aiohttp.ClientTimeout(total=3, connect=2)
            async with self._session.post(url, json={"command": command}, timeout=timeout) as resp:
                return resp.status == 200
        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOG.info("Power command '%s' sent (host going offline as expected)", command)
            return True

    async def power_on_wol(self) -> bool:
        if not self._config.wol_enabled:
            return False
        try:
            send_magic_packet(self._config.mac_address)
            _LOG.info("WoL packet sent to %s", self._config.mac_address)
            return True
        except Exception as err:
            _LOG.error("WoL failed: %s", err)
            return False
