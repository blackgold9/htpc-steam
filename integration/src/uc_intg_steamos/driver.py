"""
SteamOS HTPC Remote integration driver.

:license: MIT
"""

import logging

from ucapi_framework import BaseIntegrationDriver

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.device import SteamOSDevice
from uc_intg_steamos.entities.media_player import SteamOSMediaPlayer
from uc_intg_steamos.entities.remote import SteamOSRemote
from uc_intg_steamos.entities.sensor import create_sensors

_LOG = logging.getLogger(__name__)


class SteamOSDriver(BaseIntegrationDriver[SteamOSDevice, SteamOSConfig]):
    """SteamOS HTPC Remote integration driver."""

    def __init__(self):
        super().__init__(
            device_class=SteamOSDevice,
            entity_classes=[
                lambda cfg, dev: [SteamOSMediaPlayer(cfg, dev)] if cfg.enable_hardware_monitoring else [],
                SteamOSRemote,
                lambda cfg, dev: create_sensors(cfg, dev) if cfg.enable_hardware_monitoring else [],
            ],
            driver_id="uc_intg_steamos",
        )
