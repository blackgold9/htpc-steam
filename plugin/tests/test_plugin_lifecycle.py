"""Exercise Decky's startup/unload hooks against a real local HTTP server."""

import asyncio
import importlib.util
import json
import logging
import socket
import sys
import threading
import types
import urllib.request
from pathlib import Path

import pytest

from uc_steamos_agent.commands.dispatcher import Dispatcher
from uc_steamos_agent.config import AgentConfig, save_config


class _Keyboard:
    def __init__(self, keycodes):
        self.presses = []
        self.closed = False

    def press(self, keycode):
        self.presses.append(keycode)

    def close(self):
        self.closed = True


class _Sensors:
    def __init__(self, wol_fn):
        self.wol_fn = wol_fn
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def snapshot(self):
        return {"schema_version": 1, "cpu": {"temp_c": 45}, "wol": self.wol_fn()}


def test_plugin_startup_serves_http_and_unload_releases_resources(monkeypatch, tmp_path):
    save_config(str(tmp_path), AgentConfig(host="127.0.0.1", port=0, auth_token="test-token"))
    decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path),
        DECKY_PLUGIN_VERSION="0.1.0",
        logger=logging.getLogger(__name__),
    )
    monkeypatch.setitem(sys.modules, "decky", decky)
    # main.py prepends its import root; restore the original path after this test.
    monkeypatch.setattr(sys, "path", sys.path.copy())
    spec = importlib.util.spec_from_file_location(
        "plugin_lifecycle_test", Path(__file__).resolve().parents[1] / "main.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    dispatcher = Dispatcher(keyboard_factory=_Keyboard)
    wol_started = threading.Event()
    wol = types.SimpleNamespace(start=wol_started.set, status=lambda: {"enabled": True})
    monkeypatch.setattr(module, "Dispatcher", lambda **kwargs: dispatcher)
    monkeypatch.setattr(module, "WakeOnLanMonitor", lambda **kwargs: wol)
    monkeypatch.setattr(module, "SensorCollector", _Sensors)
    monkeypatch.setattr(module, "uinput_writable", lambda: True)
    monkeypatch.setattr(module.Plugin, "_resolve_session_env", lambda self: None)
    monkeypatch.setattr(module.Plugin, "_resolve_steam_root", lambda self: tmp_path)
    games = [{"appid": 123, "name": "Test game", "last_played": 1}]
    monkeypatch.setattr(
        module.library, "RecentGamesCache", lambda root: types.SimpleNamespace(games=lambda: games),
    )

    plugin = module.Plugin()

    async def exercise():
        def request(path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://{address[0]}:{address[1]}{path}", data=data,
                headers={"X-UC-Token": "test-token", "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=2) as response:
                return json.load(response)

        try:
            await plugin._main()
            address = plugin.server.server_address
            assert wol_started.wait(timeout=2)
            assert plugin.sensors.started
            assert request("/health")["uinput_available"] is True
            assert request("/sensors")["cpu"]["temp_c"] == 45
            assert request("/sensors")["wol"] == {"enabled": True}
            assert request("/games") == {"games": games}
            assert request("/command", {"command": "arrow_up"}) == {"status": "ok"}
            keyboard = dispatcher._keyboard
            assert keyboard.presses == [103]
        finally:
            server = getattr(plugin, "server", None)
            thread = getattr(plugin, "_server_thread", None)
            if server is not None and (thread is None or not thread.is_alive()):
                # shutdown() waits for serve_forever(); it must not be called
                # if startup failed before that thread was started.
                server.server_close()
                del plugin.server
            try:
                await plugin._unload()
            finally:
                if thread is not None and thread.ident is not None:
                    thread.join(timeout=2)

        assert not plugin._server_thread.is_alive()
        assert keyboard.closed
        assert plugin.sensors.stopped
        with pytest.raises(OSError):
            socket.create_connection(address, timeout=0.2)

    asyncio.run(exercise())
