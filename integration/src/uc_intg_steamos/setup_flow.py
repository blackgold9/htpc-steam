"""
SteamOS HTPC setup flow for device configuration.

:license: MIT
"""

import logging
from typing import Any

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow

from uc_intg_steamos.client import SteamOSClient
from uc_intg_steamos.config import SteamOSConfig

_LOG = logging.getLogger(__name__)


class SteamOSSetupFlow(BaseSetupFlow[SteamOSConfig]):
    """Setup flow for the SteamOS HTPC Remote integration."""

    def get_manual_entry_form(self) -> RequestUserInput:
        return RequestUserInput(
            {"en": "SteamOS HTPC Setup"},
            [
                {
                    "id": "name",
                    "label": {"en": "Device Name"},
                    "field": {"text": {"value": "SteamOS HTPC"}},
                },
                {
                    "id": "host",
                    "label": {"en": "HTPC IP Address"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "enable_hardware_monitoring",
                    "label": {"en": "Hardware Monitoring"},
                    "field": {
                        "dropdown": {
                            "value": "enabled",
                            "items": [
                                {"id": "enabled", "label": {"en": "Enabled"}},
                                {"id": "disabled", "label": {"en": "Disabled (Remote Control Only)"}},
                            ],
                        }
                    },
                },
                {
                    "id": "temperature_unit",
                    "label": {"en": "Temperature Unit"},
                    "field": {
                        "dropdown": {
                            "value": "celsius",
                            "items": [
                                {"id": "celsius", "label": {"en": "Celsius"}},
                                {"id": "fahrenheit", "label": {"en": "Fahrenheit"}},
                            ],
                        }
                    },
                },
                {
                    "id": "mac_address",
                    "label": {"en": "MAC Address (Optional - for Wake-on-LAN)"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "auth_token",
                    "label": {"en": "Agent Auth Token (Optional)"},
                    "field": {"text": {"value": ""}},
                },
            ],
        )

    async def query_device(self, input_values: dict[str, Any]) -> SteamOSConfig | RequestUserInput:
        host = input_values.get("host", "").strip()
        if not host:
            raise ValueError("HTPC IP address is required")

        name = input_values.get("name", "SteamOS HTPC").strip()
        enable_hw = input_values.get("enable_hardware_monitoring", "enabled") == "enabled"
        temp_unit = input_values.get("temperature_unit", "celsius")
        mac = input_values.get("mac_address", "").strip()
        auth_token = input_values.get("auth_token", "").strip()

        config = SteamOSConfig(
            identifier=f"steamos_{host.replace('.', '_')}",
            name=name,
            host=host,
            enable_hardware_monitoring=enable_hw,
            temperature_unit=temp_unit,
            mac_address=mac,
            auth_token=auth_token,
        )

        client = SteamOSClient(config)
        try:
            status = await client.agent_status()
            if status == 401:
                raise ValueError(
                    f"The SteamOS agent at {host} rejected the auth token. Check the token in the "
                    "agent's config.json on the HTPC, or clear both to disable authentication."
                )
            if status != 200:
                raise ValueError(
                    f"Cannot connect to the SteamOS agent at {host}: "
                    + (f"agent returned HTTP {status}" if status else "connection failed or refused")
                )
            _LOG.info("SteamOS agent is reachable")

            if enable_hw:
                result = await client.test_sensors()
                if not result["success"]:
                    raise ValueError(
                        f"Agent reachable but sensor data unavailable: {result.get('error', 'Unknown error')}"
                    )
                _LOG.info("Sensor connection test passed with %d values", result.get("sensor_count", 0))
        finally:
            await client.close()

        _LOG.info("Setup complete: %s at %s (hw_monitoring=%s)", name, host, enable_hw)
        return config
