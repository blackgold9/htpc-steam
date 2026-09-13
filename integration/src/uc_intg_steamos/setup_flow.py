"""
SteamOS HTPC setup flow for device configuration.

:license: MIT
"""

import logging
from typing import Any

from ucapi import RequestUserInput
from ucapi_framework import BaseSetupFlow

from uc_intg_steamos import wol
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
                    "id": "auth_token",
                    "label": {"en": "Agent Auth Token (Optional)"},
                    "field": {"text": {"value": ""}},
                },
                {
                    "id": "broadcast_address",
                    "label": {"en": "WoL Broadcast Address (Optional)"},
                    "field": {"text": {"value": "255.255.255.255", "hint": {"en": "use the subnet broadcast if 255.255.255.255 is dropped"}}},
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
        auth_token = input_values.get("auth_token", "").strip()
        broadcast_address = input_values.get("broadcast_address", "").strip() or "255.255.255.255"

        config = SteamOSConfig(
            identifier=f"steamos_{host.replace('.', '_')}",
            name=name,
            host=host,
            enable_hardware_monitoring=enable_hw,
            temperature_unit=temp_unit,
            auth_token=auth_token,
            broadcast_address=broadcast_address,
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

            # Read the MAC from the agent itself rather than asking the user to
            # type it in: a value they'd have to remember to update by hand
            # after every motherboard/NIC swap is exactly the kind of thing
            # that goes stale silently. Empty (old agent, unreadable NIC) just
            # means no WoL capability, same as an unset MAC always has.
            mac_address = await client.fetch_wol_mac()
            if mac_address:
                config.mac_address = wol.normalize_mac(mac_address)
                _LOG.info("Wake-on-LAN MAC discovered from agent: %s", config.mac_address)
        finally:
            await client.close()

        _LOG.info(
            "Setup complete: %s at %s (hw_monitoring=%s, wol=%s)",
            name,
            host,
            enable_hw,
            config.mac_address or "disabled",
        )
        return config
