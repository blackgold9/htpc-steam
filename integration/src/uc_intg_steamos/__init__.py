"""
uc-intg-steamos: SteamOS/Bazzite Gamescope HTPC integration for the
Unfolded Circle Remote Two/3.

:license: MIT
"""

import asyncio
import logging
import os

from ucapi_framework import BaseConfigManager, get_config_path

from uc_intg_steamos.config import SteamOSConfig
from uc_intg_steamos.driver import SteamOSDriver
from uc_intg_steamos.setup_flow import SteamOSSetupFlow

__version__ = "0.1.0"

_LOG = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=os.getenv("UC_LOG_LEVEL", "INFO"))

    driver = SteamOSDriver()
    config_path = get_config_path(driver.api.config_dir_path)
    driver.config_manager = BaseConfigManager(
        config_path,
        driver.on_device_added,
        driver.on_device_removed,
        config_class=SteamOSConfig,
    )

    setup_handler = SteamOSSetupFlow.create_handler(driver)
    await driver.api.init("driver.json", setup_handler=setup_handler)
    await driver.register_all_device_instances(connect=False)

    _LOG.info("uc-intg-steamos %s running", __version__)
    await asyncio.Event().wait()
