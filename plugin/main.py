import asyncio
import pwd
import sys
import threading
from dataclasses import replace
from pathlib import Path

# decky-loader adds py_modules/ to sys.path itself; the explicit insert here is a
# harmless fallback that also lets this file run standalone for a quick smoke test.
sys.path.insert(0, str(Path(__file__).parent / "py_modules"))

import decky
from uc_steamos_agent.commands import launch, media, user_session
from uc_steamos_agent.commands.dispatcher import Dispatcher
from uc_steamos_agent.commands.uinput_probe import uinput_writable
from uc_steamos_agent.commands.wol import WakeOnLanMonitor
from uc_steamos_agent.config import load_config, parse_mqtt_config, save_config
from uc_steamos_agent.controller_puck import PuckMonitor
from uc_steamos_agent.games import library
from uc_steamos_agent.http.server import build_server
from uc_steamos_agent.mqtt.publisher import MqttPublisher
from uc_steamos_agent.sensors.collector import SensorCollector


class Plugin:
    # Asyncio-compatible long-running code, executed in a task when the plugin is loaded.
    async def _main(self):
        self.loop = asyncio.get_event_loop()
        self._mqtt_settings_lock = asyncio.Lock()
        self._unloading = False
        self.config = load_config(decky.DECKY_PLUGIN_SETTINGS_DIR, decky.DECKY_PLUGIN_VERSION)
        session_env = self._resolve_session_env()

        self.dispatcher = Dispatcher(
            media_execute=self._bind_env(media.execute, session_env),
            launch_steam_uri_execute=self._bind_env(launch.launch_steam_uri, session_env),
        )
        self.wol = WakeOnLanMonitor(arm=self.config.wol_arm)
        # Arming spawns ethtool, and the flag has to be back before the box can
        # be slept, so it happens off the plugin's startup task: Decky's start
        # path must not block on a subprocess.
        threading.Thread(target=self.wol.start, daemon=True).start()
        self.sensors = SensorCollector(wol_fn=self.wol.status)
        self.sensors.start()
        self.controller_puck = PuckMonitor()
        self.controller_puck.start()
        steam_root = self._resolve_steam_root()
        self._games_fn = library.RecentGamesCache(steam_root).games if steam_root else None
        self.server = build_server(
            self.config,
            uinput_writable,
            self.dispatcher,
            self.sensors.snapshot,
            games_fn=self._games_fn,
            wol_fn=self.wol.status,
            puck_snapshot_fn=self.controller_puck.snapshot,
            puck_events_fn=self.controller_puck.events_since,
        )
        self._server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._server_thread.start()
        self.mqtt = self._new_mqtt_publisher(self.config)
        self.mqtt.start()
        decky.logger.info(
            "uc-steamos-agent listening on %s:%s (uinput_available=%s, wol_arm=%s)",
            self.config.host,
            self.config.port,
            uinput_writable(),
            self.config.wol_arm,
        )

    # Called first during unload; the plugin is stopped but not removed.
    async def _unload(self):
        decky.logger.info("uc-steamos-agent shutting down")
        mqtt_settings_lock = getattr(self, "_mqtt_settings_lock", None)
        if mqtt_settings_lock is not None:
            async with mqtt_settings_lock:
                self._unloading = True
                await self._stop_mqtt_for_unload()
        else:
            await self._stop_mqtt_for_unload()
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
        controller_puck = getattr(self, "controller_puck", None)
        if controller_puck is not None:
            controller_puck.stop()

    async def _stop_mqtt_for_unload(self):
        mqtt = getattr(self, "mqtt", None)
        if mqtt is not None:
            try:
                await asyncio.to_thread(mqtt.stop)
            except Exception:
                decky.logger.warning("MQTT publisher failed during shutdown")

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

    def _new_mqtt_publisher(self, config):
        return MqttPublisher(
            config,
            sensors_fn=self.sensors.snapshot,
            puck=self.controller_puck,
            games_fn=self._games_fn,
            uinput_available_fn=uinput_writable,
        )

    def _install_fresh_mqtt(self, config) -> bool:
        """Install a fresh publisher without allowing lifecycle errors to escape."""
        self.config = config
        publisher = None
        try:
            publisher = self._new_mqtt_publisher(config)
            self.mqtt = publisher
            publisher.start()
            if publisher.status()["last_error"]:
                publisher.stop()
                return False
            return True
        except Exception:
            if publisher is not None:
                try:
                    publisher.stop()
                except Exception:
                    pass
            return False

    async def get_health(self) -> dict:
        """Callable from the QAM frontend panel for an in-process status check."""
        return {
            "status": "ok",
            "version": self.config.version,
            "host": self.config.host,
            "port": self.config.port,
            "uinput_available": uinput_writable(),
            "wol_arm": self.config.wol_arm,
            "wol": self.wol.status(),
        }

    async def get_mqtt_settings(self) -> dict:
        """Return QAM-safe MQTT settings without exposing the broker password."""
        mqtt = self.config.mqtt
        return {
            "enabled": mqtt.enabled,
            "host": mqtt.host,
            "port": mqtt.port,
            "username": mqtt.username,
            "password_set": bool(mqtt.password),
            "tls": mqtt.tls,
            "topic_prefix": mqtt.topic_prefix,
            "discovery_prefix": mqtt.discovery_prefix,
            "publish_interval_s": mqtt.publish_interval_s,
            "status": self.mqtt.status(),
        }

    async def set_mqtt_settings(self, values: dict) -> dict:
        """Validate, persist, and live-apply MQTT settings from the QAM panel."""
        async with self._mqtt_settings_lock:
            if self._unloading:
                return {"ok": False, "error": "Plugin is shutting down"}
            if not isinstance(values, dict):
                return {"ok": False, "error": "Invalid MQTT configuration"}
            password = values.get("password", "")
            clear_password = values.get("clear_password", False)
            if not isinstance(password, str) or not isinstance(clear_password, bool):
                return {"ok": False, "error": "Invalid MQTT configuration"}
            mqtt_values = {
                name: values.get(name, getattr(self.config.mqtt, name))
                for name in self.config.mqtt.__dataclass_fields__
            }
            if clear_password:
                mqtt_values["password"] = ""
            elif not password:
                mqtt_values["password"] = self.config.mqtt.password
            try:
                mqtt = parse_mqtt_config(mqtt_values)
            except ValueError as err:
                return {"ok": False, "error": str(err)}

            new_config = replace(self.config, mqtt=mqtt)
            try:
                replacement = self._new_mqtt_publisher(new_config)
            except Exception:
                return {"ok": False, "error": "Could not prepare MQTT publisher"}

            old_config = self.config
            old_mqtt = self.mqtt
            try:
                await asyncio.to_thread(old_mqtt.stop)
            except Exception:
                try:
                    await asyncio.to_thread(replacement.stop)
                except Exception:
                    pass
                restored = self._install_fresh_mqtt(old_config)
                error = "Could not stop the current MQTT publisher"
                if not restored:
                    error += "; the previous MQTT publisher could not be restarted"
                return {"ok": False, "error": error}

            try:
                save_config(decky.DECKY_PLUGIN_SETTINGS_DIR, new_config)
            except OSError:
                try:
                    await asyncio.to_thread(replacement.stop)
                except Exception:
                    pass
                restored = self._install_fresh_mqtt(old_config)
                error = "Could not save MQTT configuration"
                if not restored:
                    error += "; the previous MQTT publisher could not be restarted"
                return {"ok": False, "error": error}

            self.config = new_config
            self.mqtt = replacement
            start_error = None
            try:
                self.mqtt.start()
            except Exception as err:
                start_error = str(err)
            try:
                status = self.mqtt.status()
            except Exception as err:
                status = {"last_error": str(err)}
            failure = start_error or status["last_error"]
            if failure:
                try:
                    await asyncio.to_thread(self.mqtt.stop)
                except Exception:
                    pass
                try:
                    save_config(decky.DECKY_PLUGIN_SETTINGS_DIR, old_config)
                except OSError:
                    restored = self._install_fresh_mqtt(old_config)
                    error = "MQTT failed to start and the saved configuration could not be restored"
                    if not restored:
                        error += "; the previous MQTT publisher could not be restarted"
                    return {"ok": False, "error": error}
                restored = self._install_fresh_mqtt(old_config)
                error = "MQTT failed to start"
                if not restored:
                    error += "; the previous MQTT publisher could not be restarted"
                return {"ok": False, "error": error}
            return {"ok": True, "settings": await self.get_mqtt_settings()}
