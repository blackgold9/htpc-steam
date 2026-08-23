import asyncio
import pwd
import sys
import threading
from pathlib import Path

# decky-loader adds py_modules/ to sys.path itself; the explicit insert here is a
# harmless fallback that also lets this file run standalone for a quick smoke test.
sys.path.insert(0, str(Path(__file__).parent / "py_modules"))

import decky

from uc_steamos_agent.commands import launch, media, user_session
from uc_steamos_agent.commands.dispatcher import Dispatcher
from uc_steamos_agent.commands.uinput_probe import uinput_writable
from uc_steamos_agent.config import load_config
from uc_steamos_agent.games import library
from uc_steamos_agent.http.server import build_server
from uc_steamos_agent.sensors.collector import SensorCollector


class Plugin:
    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded.
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self.config = load_config(decky.DECKY_PLUGIN_SETTINGS_DIR, decky.DECKY_PLUGIN_VERSION)
        session_env = self._resolve_session_env()

        self.dispatcher = Dispatcher(
            media_execute=self._bind_env(media.execute, session_env),
            launch_steam_uri_execute=self._bind_env(launch.launch_steam_uri, session_env),
        )
        self.sensors = SensorCollector()
        self.sensors.start()
        steam_root = self._resolve_steam_root()
        games_fn = (lambda: library.list_recent_games(steam_root=steam_root)) if steam_root else None
        self.server = build_server(
            self.config, uinput_writable, self.dispatcher, self.sensors.snapshot, games_fn=games_fn
        )
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
        sensors = getattr(self, "sensors", None)
        if sensors is not None:
            sensors.stop()

    async def _uninstall(self):
        pass

    def _resolve_session_env(self):
        """wpctl/launch commands need the desktop user's XDG_RUNTIME_DIR to
        reach PipeWire/the desktop session, since this plugin runs as root.
        See user_session.py. Returns None if resolution fails, in which case
        callers fall back to the plugin's own (rootless-session) environment."""
        try:
            uid = user_session.resolve_uid(decky.DECKY_USER)
            return user_session.session_env(uid)
        except (KeyError, OSError) as err:
            decky.logger.warning("Could not resolve session env for %s: %s", decky.DECKY_USER, err)
            return None

    def _resolve_steam_root(self):
        """/games needs the desktop user's Steam data dir; this plugin runs
        as root so `~` (DEFAULT_STEAM_ROOT) would resolve to /root instead.
        Returns None if resolution fails, in which case /games is disabled."""
        try:
            home_dir = pwd.getpwnam(decky.DECKY_USER).pw_dir
            return library.steam_root_for_home(home_dir)
        except KeyError as err:
            decky.logger.warning("Could not resolve home dir for %s: %s", decky.DECKY_USER, err)
            return None

    @staticmethod
    def _bind_env(fn, env):
        if env is None:
            return fn

        def bound(arg):
            return fn(arg, env=env)

        return bound

    async def get_health(self) -> dict:
        """Callable from the QAM frontend panel for an in-process status check."""
        return {
            "status": "ok",
            "version": self.config.version,
            "host": self.config.host,
            "port": self.config.port,
            "uinput_available": uinput_writable(),
        }
