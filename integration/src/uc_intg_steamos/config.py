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

    def convert_temperature(self, celsius: float) -> float:
        if self.temperature_unit == "fahrenheit":
            return (celsius * 9 / 5) + 32
        return celsius

    def temperature_symbol(self) -> str:
        return "°F" if self.temperature_unit == "fahrenheit" else "°C"
