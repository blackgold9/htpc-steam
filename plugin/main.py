import asyncio
import sys
import threading
from pathlib import Path

# decky-loader adds py_modules/ to sys.path itself; the explicit insert here is a
# harmless fallback that also lets this file run standalone for a quick smoke test.
sys.path.insert(0, str(Path(__file__).parent / "py_modules"))

import decky

from uc_steamos_agent.commands import media, user_session
from uc_steamos_agent.commands.dispatcher import Dispatcher
from uc_steamos_agent.commands.uinput_probe import uinput_writable
from uc_steamos_agent.config import load_config
from uc_steamos_agent.http.server import build_server


class Plugin:
    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded.
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self.config = load_config(decky.DECKY_PLUGIN_SETTINGS_DIR, decky.DECKY_PLUGIN_VERSION)
        self.dispatcher = Dispatcher(media_execute=self._build_media_execute())
        self.server = build_server(self.config, uinput_writable, self.dispatcher)
        self._server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._server_thread.start()
        decky.logger.info(
            "uc-steamos-agent listening on %s:%s (uinput_available=%s)",
            self.config.host,
            self.config.port,
            uinput_writable(),
        )

    # Called first during unload; the plugin is stopped but not removed.
    async def _unload(self):
        decky.logger.info("uc-steamos-agent shutting down")
        server = getattr(self, "server", None)
        if server is not None:
            server.shutdown()
            server.server_close()
        dispatcher = getattr(self, "dispatcher", None)
        if dispatcher is not None:
            dispatcher.close()

    async def _uninstall(self):
        pass

    def _build_media_execute(self):
        """wpctl needs the desktop user's XDG_RUNTIME_DIR to reach PipeWire,
        since this plugin process itself runs as root. See user_session.py."""
        try:
            uid = user_session.resolve_uid(decky.DECKY_USER)
            env = user_session.session_env(uid)
        except (KeyError, OSError) as err:
            decky.logger.warning("Could not resolve session env for %s: %s", decky.DECKY_USER, err)
            return media.execute

        def media_execute(argv):
            media.execute(argv, env=env)

        return media_execute

    async def get_health(self) -> dict:
        """Callable from the QAM frontend panel for an in-process status check."""
        return {
            "status": "ok",
            "version": self.config.version,
            "host": self.config.host,
            "port": self.config.port,
            "uinput_available": uinput_writable(),
        }
