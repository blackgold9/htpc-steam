"""
SteamOS media player entity for system monitoring display.

Uses the media_player entity type purely as a UI vehicle for a compact
multi-line stats dashboard (title/artist/album -> three lines of system
stats) — this box is for gaming, not media playback, so there's no actual
transport control here (no play/pause/etc.); only ON_OFF/SELECT_SOURCE/
VOLUME/MUTE_TOGGLE are real.

:license: MIT
"""

import logging
from typing import Any

from ucapi import StatusCodes, media_player
from ucapi_framework import MediaPlayerEntity

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.const import MONITORING_VIEWS
from uc_intg_steamos.device import STATE_OFF, STATE_UNAVAILABLE, STATE_WAKING, SteamOSDevice

_LOG = logging.getLogger(__name__)

SOURCE_ICONS = {
    "System Overview": "system_overview.png",
    "CPU Performance": "cpu_monitor.png",
    "GPU Performance": "gpu_monitor.png",
    "Memory Usage": "memory_usage.png",
    "Storage Activity": "storage_monitor.png",
    "Network Activity": "network_activity.png",
    "Temperature Overview": "temperatures.png",
    "Fan Monitoring": "fan_monitoring.png",
    "Power Consumption": "power_consumption.png",
    "Battery": "battery.png",
    # Reuses the power icon; there's no dedicated WoL glyph in the icon set.
    "Wake-on-LAN": "power_consumption.png",
}

FEATURES = [
    media_player.Features.ON_OFF,
    media_player.Features.SELECT_SOURCE,
    media_player.Features.VOLUME,
    media_player.Features.MUTE_TOGGLE,
    media_player.Features.MEDIA_IMAGE_URL,
    media_player.Features.MEDIA_TITLE,
    media_player.Features.MEDIA_ARTIST,
    media_player.Features.MEDIA_ALBUM,
]


class SteamOSMediaPlayer(MediaPlayerEntity):
    """Media player entity displaying SteamOS HTPC monitoring views."""

    def __init__(self, device_config: SteamOSConfig, device: SteamOSDevice) -> None:
        self._device = device
        entity_id = f"media_player.{device_config.identifier}"
        super().__init__(
            entity_id,
            device_config.name,
            FEATURES,
            {
                media_player.Attributes.STATE: media_player.States.STANDBY,
                media_player.Attributes.SOURCE_LIST: MONITORING_VIEWS,
                media_player.Attributes.SOURCE: "",
                media_player.Attributes.MEDIA_IMAGE_URL: "",
                media_player.Attributes.MEDIA_TITLE: "",
                media_player.Attributes.MEDIA_ARTIST: "",
                media_player.Attributes.MEDIA_ALBUM: "",
                media_player.Attributes.VOLUME: 50,
                media_player.Attributes.MUTED: False,
            },
            cmd_handler=self._handle_command,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        state = self._device.state
        if state in (STATE_OFF, STATE_WAKING):
            # Sensors are meaningless when the box isn't answering, so the
            # dashboard's job here is to say so and point at the wake path.
            wake_hint = (
                "Wake with the Power On button"
                if self._device.wol_available
                else "No MAC configured — power it on manually"
            )
            self.update({
                media_player.Attributes.STATE: media_player.States.STANDBY,
                media_player.Attributes.MEDIA_TITLE: "Box is off",
                media_player.Attributes.MEDIA_ARTIST: (
                    "Waking — waiting for it to come back" if state == STATE_WAKING else wake_hint
                ),
                media_player.Attributes.MEDIA_ALBUM: "",
            })
            return

        if state == STATE_UNAVAILABLE:
            # Awake but refusing the agent port: Decky/plugin problem, not power.
            self.update({
                media_player.Attributes.STATE: media_player.States.UNAVAILABLE,
                media_player.Attributes.MEDIA_TITLE: "Box is on, agent is not answering",
                media_player.Attributes.MEDIA_ARTIST: "Check Decky and the SteamOS Agent plugin",
                media_player.Attributes.MEDIA_ALBUM: "",
            })
            return

        data = self._device.system_data
        view = self._device.current_view
        icon_file = SOURCE_ICONS.get(view, "system_overview.png")

        attrs: dict[str, Any] = {
            media_player.Attributes.STATE: media_player.States.ON,
            media_player.Attributes.SOURCE_LIST: MONITORING_VIEWS,
            media_player.Attributes.SOURCE: view,
            media_player.Attributes.MEDIA_IMAGE_URL: self._device.get_icon_base64(icon_file),
        }
        attrs.update(self._format_view_data(view, data))
        self.update(attrs)

    def _format_view_data(self, view: str, data: Any) -> dict[str, Any]:
        cfg = self._device.config

        def fmt_temp(val: float | None) -> str:
            if val is None:
                return "N/A"
            return f"{cfg.convert_temperature(val):.1f}{cfg.temperature_symbol()}"

        def fmt_pct(val: float | None) -> str:
            return f"{val:.1f}%" if val is not None else "N/A"

        def fmt_speed(val: float | None) -> str:
            if val is None:
                return "N/A"
            if val > 1000:
                return f"{val / 1000:.2f} Gbps"
            return f"{val:.1f} Mbps"

        match view:
            case "System Overview":
                power = f"Power: {data.cpu_power:.1f}W" if data.cpu_power else "Power: N/A"
                mem = "N/A"
                if data.memory_used is not None and data.memory_total:
                    pct = (data.memory_used / data.memory_total) * 100
                    mem = f"{data.memory_used:.1f}/{data.memory_total:.1f} GB ({pct:.1f}%)"
                return {
                    media_player.Attributes.MEDIA_TITLE: f"CPU: {fmt_temp(data.cpu_temp)} ({fmt_pct(data.cpu_load)})",
                    media_player.Attributes.MEDIA_ARTIST: power,
                    media_player.Attributes.MEDIA_ALBUM: mem,
                }
            case "CPU Performance":
                return {
                    media_player.Attributes.MEDIA_TITLE: f"Temperature: {fmt_temp(data.cpu_temp)}",
                    media_player.Attributes.MEDIA_ARTIST: f"Load: {fmt_pct(data.cpu_load)}",
                    media_player.Attributes.MEDIA_ALBUM: f"Clock: {data.cpu_clock or 0:.0f} MHz",
                }
            case "GPU Performance":
                if data.gpu_temp is not None or data.gpu_load is not None:
                    return {
                        media_player.Attributes.MEDIA_TITLE: f"Temperature: {fmt_temp(data.gpu_temp)}",
                        media_player.Attributes.MEDIA_ARTIST: f"Load: {fmt_pct(data.gpu_load)}",
                        media_player.Attributes.MEDIA_ALBUM: data.detected_gpu_name,
                    }
                return {
                    media_player.Attributes.MEDIA_TITLE: "No GPU Data",
                    media_player.Attributes.MEDIA_ARTIST: "",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }
            case "Memory Usage":
                pct = ((data.memory_used or 0) / (data.memory_total or 1)) * 100
                return {
                    media_player.Attributes.MEDIA_TITLE: f"Used: {data.memory_used or 0:.1f} GB",
                    media_player.Attributes.MEDIA_ARTIST: f"Total: {data.memory_total or 0:.1f} GB",
                    media_player.Attributes.MEDIA_ALBUM: f"Usage: {pct:.1f}%",
                }
            case "Storage Activity":
                if data.storage_total and data.storage_used:
                    return {
                        media_player.Attributes.MEDIA_TITLE: f"Used: {data.storage_used:.1f} GB",
                        media_player.Attributes.MEDIA_ARTIST: f"Total: {data.storage_total:.1f} GB",
                        media_player.Attributes.MEDIA_ALBUM: f"Usage: {data.storage_used_percent or 0:.1f}%",
                    }
                return {
                    media_player.Attributes.MEDIA_TITLE: f"Usage: {data.storage_used_percent or 0:.1f}%",
                    media_player.Attributes.MEDIA_ARTIST: "Primary Drive",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }
            case "Network Activity":
                return {
                    media_player.Attributes.MEDIA_TITLE: f"Download: {fmt_speed(data.network_down)}",
                    media_player.Attributes.MEDIA_ARTIST: f"Upload: {fmt_speed(data.network_up)}",
                    media_player.Attributes.MEDIA_ALBUM: "Active Interface",
                }
            case "Temperature Overview":
                return {
                    media_player.Attributes.MEDIA_TITLE: f"CPU: {fmt_temp(data.cpu_temp)}",
                    media_player.Attributes.MEDIA_ARTIST: f"Storage: {fmt_temp(data.storage_temp)}",
                    media_player.Attributes.MEDIA_ALBUM: f"Motherboard: {fmt_temp(data.motherboard_temp_avg)}",
                }
            case "Fan Monitoring":
                if data.fan_speeds:
                    avg = sum(data.fan_speeds) / len(data.fan_speeds)
                    return {
                        media_player.Attributes.MEDIA_TITLE: f"Active Fans: {len(data.fan_speeds)}",
                        media_player.Attributes.MEDIA_ARTIST: f"Average: {avg:.0f} RPM",
                        media_player.Attributes.MEDIA_ALBUM: f"Maximum: {max(data.fan_speeds):.0f} RPM",
                    }
                return {
                    media_player.Attributes.MEDIA_TITLE: "No Fan Data",
                    media_player.Attributes.MEDIA_ARTIST: "Fans not detected",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }
            case "Power Consumption":
                if data.cpu_power:
                    return {
                        media_player.Attributes.MEDIA_TITLE: f"CPU Package: {data.cpu_power:.1f}W",
                        media_player.Attributes.MEDIA_ARTIST: "Real-time Power Draw",
                        media_player.Attributes.MEDIA_ALBUM: "",
                    }
                return {
                    media_player.Attributes.MEDIA_TITLE: "Power Monitoring",
                    media_player.Attributes.MEDIA_ARTIST: "No power sensors detected",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }
            case "Battery":
                if data.battery_present:
                    status = "Charging" if data.battery_charging else "Discharging"
                    power = f"{data.battery_power:.1f}W" if data.battery_power is not None else "N/A"
                    return {
                        media_player.Attributes.MEDIA_TITLE: f"Battery: {data.battery_percent or 0:.0f}%",
                        media_player.Attributes.MEDIA_ARTIST: status,
                        media_player.Attributes.MEDIA_ALBUM: f"Power: {power}",
                    }
                return {
                    media_player.Attributes.MEDIA_TITLE: "No Battery",
                    media_player.Attributes.MEDIA_ARTIST: "Desktop/no battery detected",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }
            case "Wake-on-LAN":
                # Three answers, and they must not collapse into each other:
                # the agent couldn't read it (the live box, where unprivileged
                # ethtool reports nothing about wake), the NIC can't do it, or
                # it can and isn't armed. Only the last one is a `sudo` away.
                if not data.wol_present:
                    return {
                        media_player.Attributes.MEDIA_TITLE: "Wake-on-LAN",
                        media_player.Attributes.MEDIA_ARTIST: "Could not read NIC state",
                        media_player.Attributes.MEDIA_ALBUM: "Old agent version, or ethtool reported no Wake-on info",
                    }
                if data.wol_enabled:
                    armed = "armed" if data.wol_may_wakeup else "filter armed, device is no wakeup source"
                elif data.wol_supported:
                    armed = f"NOT armed — sudo ethtool -s {data.wol_interface} wol g"
                else:
                    armed = "NIC does not advertise Wake-on-LAN"
                return {
                    media_player.Attributes.MEDIA_TITLE: f"{data.wol_interface}: {armed}",
                    media_player.Attributes.MEDIA_ARTIST: f"driver: {data.wol_driver or 'unknown'}",
                    media_player.Attributes.MEDIA_ALBUM: f"wake via port {cfg.wol_port} to {cfg.broadcast_address}",
                }
            case _:
                return {
                    media_player.Attributes.MEDIA_TITLE: view,
                    media_player.Attributes.MEDIA_ARTIST: "",
                    media_player.Attributes.MEDIA_ALBUM: "",
                }

    async def _handle_command(self, entity: Any, cmd_id: str, params: dict[str, Any] | None) -> StatusCodes:
        match cmd_id:
            case media_player.Commands.ON:
                # Wake, not an agent command: the agent can't be reached from
                # the very state this button exists for.
                await self._device.wake_on_lan()
            case media_player.Commands.OFF:
                await self._device.send_command("power_sleep")
            case media_player.Commands.SELECT_SOURCE:
                source = params.get("source", "") if params else ""
                if source in MONITORING_VIEWS:
                    self._device.set_current_view(source)
            case media_player.Commands.VOLUME:
                volume = params.get("volume", 50) if params else 50
                await self._device.send_command(f"set_volume:{volume}")
            case media_player.Commands.VOLUME_UP:
                await self._device.send_command("volume_up")
            case media_player.Commands.VOLUME_DOWN:
                await self._device.send_command("volume_down")
            case media_player.Commands.MUTE_TOGGLE:
                await self._device.send_command("mute")
            case _:
                return StatusCodes.NOT_IMPLEMENTED

        self._device.push_update()
        return StatusCodes.OK
