"""
Configuration dataclass for the SteamOS HTPC Remote integration.

:license: MIT
"""

from dataclasses import dataclass


@dataclass
class SteamOSConfig:
    identifier: str = ""
    name: str = ""
    host: str = ""
    enable_hardware_monitoring: bool = True
    temperature_unit: str = "celsius"
    auth_token: str = ""
    # Wake-on-LAN is opt-in exactly like auth_token: an empty MAC means no
    # wake capability, no Power On button, and no behaviour change at all for
    # users who don't want it.
    mac_address: str = ""
    # Limited broadcast by default. The subnet-directed form (e.g.
    # 192.168.1.255) is the override for networks that drop 255.255.255.255;
    # the box's last-known IP is also always tried, see device.wake_on_lan().
    broadcast_address: str = "255.255.255.255"
    wol_port: int = 9

    def convert_temperature(self, celsius: float) -> float:
        if self.temperature_unit == "fahrenheit":
            return (celsius * 9 / 5) + 32
        return celsius

    def temperature_symbol(self) -> str:
        return "°F" if self.temperature_unit == "fahrenheit" else "°C"
