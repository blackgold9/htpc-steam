"""
SteamOS sensor entities for system monitoring.

:license: MIT
"""

import logging
from typing import Any, Callable

from ucapi import sensor
from ucapi_framework import SensorEntity

from uc_intg_steamos.config import SteamOSConfig

_LOG = logging.getLogger(__name__)


class SteamOSSensor(SensorEntity):
    """Generic sensor entity for SteamOS HTPC monitoring values."""

    def __init__(
        self,
        entity_id: str,
        name: str,
        unit: str,
        device_class: str,
        device: Any,
        value_getter: Callable,
    ) -> None:
        self._device = device
        self._value_getter = value_getter
        super().__init__(
            entity_id,
            name,
            [],
            {
                sensor.Attributes.STATE: sensor.States.UNKNOWN,
                sensor.Attributes.VALUE: "N/A",
                sensor.Attributes.UNIT: unit,
            },
            device_class=device_class,
        )
        self.subscribe_to_device(device)

    async def sync_state(self) -> None:
        if self._device.state == "UNAVAILABLE":
            self.update({sensor.Attributes.STATE: sensor.States.UNAVAILABLE})
            return
        value = self._value_getter(self._device)
        self.update({
            sensor.Attributes.STATE: sensor.States.ON,
            sensor.Attributes.VALUE: value if value is not None else "N/A",
        })


def _temp(attr: str, config: SteamOSConfig) -> Callable:
    def getter(dev: Any) -> str | None:
        val = getattr(dev.system_data, attr, None)
        if val is not None:
            return f"{config.convert_temperature(val):.1f}"
        return None

    return getter


def _val(attr: str, fmt: str = "{:.1f}") -> Callable:
    def getter(dev: Any) -> str | None:
        val = getattr(dev.system_data, attr, None)
        if val is not None:
            return fmt.format(val)
        return None

    return getter


def _mem_pct(dev: Any) -> str | None:
    d = dev.system_data
    if d.memory_used is not None and d.memory_total and d.memory_total > 0:
        return f"{(d.memory_used / d.memory_total) * 100:.1f}"
    return None


def _fan_avg(dev: Any) -> str | None:
    d = dev.system_data
    if d.fan_speeds:
        return f"{sum(d.fan_speeds) / len(d.fan_speeds):.0f}"
    return None


def create_sensors(config: SteamOSConfig, device: Any) -> list[SensorEntity]:
    """Create sensor entities based on configuration."""
    ident = config.identifier

    sensors: list[SensorEntity] = [
        SteamOSSensor(
            f"sensor.{ident}.cpu_temp",
            f"{config.name} CPU Temperature",
            config.temperature_symbol(),
            sensor.DeviceClasses.TEMPERATURE,
            device,
            _temp("cpu_temp", config),
        ),
        SteamOSSensor(
            f"sensor.{ident}.cpu_load",
            f"{config.name} CPU Load",
            "%",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("cpu_load"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.cpu_power",
            f"{config.name} CPU Power",
            "W",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("cpu_power"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.gpu_temp",
            f"{config.name} GPU Temperature",
            config.temperature_symbol(),
            sensor.DeviceClasses.TEMPERATURE,
            device,
            _temp("gpu_temp", config),
        ),
        SteamOSSensor(
            f"sensor.{ident}.gpu_load",
            f"{config.name} GPU Load",
            "%",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("gpu_load"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.memory_usage",
            f"{config.name} Memory Usage",
            "%",
            sensor.DeviceClasses.CUSTOM,
            device,
            _mem_pct,
        ),
        SteamOSSensor(
            f"sensor.{ident}.storage_usage",
            f"{config.name} Storage Usage",
            "%",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("storage_used_percent"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.network_down",
            f"{config.name} Network Download",
            "Mbps",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("network_down"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.network_up",
            f"{config.name} Network Upload",
            "Mbps",
            sensor.DeviceClasses.CUSTOM,
            device,
            _val("network_up"),
        ),
        SteamOSSensor(
            f"sensor.{ident}.fan_speed",
            f"{config.name} Fan Speed",
            "RPM",
            sensor.DeviceClasses.CUSTOM,
            device,
            _fan_avg,
        ),
        SteamOSSensor(
            f"sensor.{ident}.battery_percent",
            f"{config.name} Battery",
            "%",
            sensor.DeviceClasses.BATTERY,
            device,
            _val("battery_percent", "{:.0f}"),
        ),
    ]

    return sensors
