import asyncio
import importlib
import importlib.util
import sys
import types
from dataclasses import replace
from pathlib import Path

from uc_steamos_agent.config import AgentConfig, MqttConfig


class FakeLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


class FakeLifecycle:
    def __init__(self, *args, **kwargs):
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        self.stopped = True

    def status(self):
        return None

    def snapshot(self):
        return {}


class FakePuck(FakeLifecycle):
    def events_since(self, sequence):
        return []

    def add_event_listener(self, listener):
        self.listener = listener

    def remove_event_listener(self, listener):
        if getattr(self, "listener", None) == listener:
            self.listener = None


class FakeServer:
    def __init__(self):
        self.shutdown_called = False
        self.close_called = False

    def serve_forever(self):
        pass

    def shutdown(self):
        self.shutdown_called = True

    def server_close(self):
        self.close_called = True


class FakeMqtt(FakeLifecycle):
    instances = []

    def __init__(self, config, **kwargs):
        super().__init__()
        self.config = config
        self.kwargs = kwargs
        self.__class__.instances.append(self)

    def status(self):
        return {
            "enabled": self.config.mqtt.enabled,
            "connected": self.started and not self.stopped,
            "broker_online": self.started and not self.stopped,
            "last_error": None,
        }


def test_plugin_wires_read_only_mqtt_publisher_into_lifecycle(monkeypatch, tmp_path):
    FakeMqtt.instances.clear()
    decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path),
        DECKY_PLUGIN_VERSION="0.1.0",
        DECKY_USER="deck",
        logger=FakeLogger(),
    )
    monkeypatch.setitem(sys.modules, "decky", decky)
    module_name = "decky_plugin_main_for_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).resolve().parents[1] / "main.py"
    )
    plugin_main = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = plugin_main
    spec.loader.exec_module(plugin_main)

    config = AgentConfig(
        version="0.1.0",
        mqtt=MqttConfig(enabled=True, host="ha.internal"),
    )
    monkeypatch.setattr(plugin_main, "load_config", lambda *args: config)
    monkeypatch.setattr(plugin_main, "Dispatcher", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "WakeOnLanMonitor", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "SensorCollector", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "PuckMonitor", FakePuck)
    monkeypatch.setattr(plugin_main, "MqttPublisher", FakeMqtt)
    monkeypatch.setattr(plugin_main, "build_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_session_env", lambda self: None)
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_steam_root", lambda self: None)

    plugin = plugin_main.Plugin()
    asyncio.run(plugin._main())

    assert len(FakeMqtt.instances) == 1
    mqtt = FakeMqtt.instances[0]
    assert mqtt.started is True
    assert mqtt.config is config
    assert mqtt.kwargs["sensors_fn"] == plugin.sensors.snapshot
    assert mqtt.kwargs["puck"] is plugin.controller_puck
    assert mqtt.kwargs["games_fn"] is None
    assert mqtt.kwargs["uinput_available_fn"] is plugin_main.uinput_writable

    def late_stop_failure():
        mqtt.stopped = True
        raise RuntimeError("late stop failure")

    mqtt.stop = late_stop_failure
    asyncio.run(plugin._unload())
    assert mqtt.stopped is True
    assert plugin.server.shutdown_called is True
    assert plugin.server.close_called is True
    assert plugin.dispatcher.stopped is True
    assert plugin.sensors.stopped is True
    assert plugin.controller_puck.stopped is True


def test_qam_mqtt_settings_never_return_the_saved_password(monkeypatch, tmp_path):
    FakeMqtt.instances.clear()
    decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path),
        DECKY_PLUGIN_VERSION="0.1.0",
        DECKY_USER="deck",
        logger=FakeLogger(),
    )
    monkeypatch.setitem(sys.modules, "decky", decky)
    module_name = "decky_plugin_main_for_mqtt_settings_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).resolve().parents[1] / "main.py"
    )
    plugin_main = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = plugin_main
    spec.loader.exec_module(plugin_main)

    config = AgentConfig(
        version="0.1.0",
        mqtt=MqttConfig(enabled=True, host="ha.internal", username="agent", password="broker-secret"),
    )
    monkeypatch.setattr(plugin_main, "load_config", lambda *args: config)
    monkeypatch.setattr(plugin_main, "Dispatcher", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "WakeOnLanMonitor", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "SensorCollector", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "PuckMonitor", FakePuck)
    monkeypatch.setattr(plugin_main, "MqttPublisher", FakeMqtt)
    monkeypatch.setattr(plugin_main, "build_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_session_env", lambda self: None)
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_steam_root", lambda self: None)

    plugin = plugin_main.Plugin()
    asyncio.run(plugin._main())
    try:
        settings = asyncio.run(plugin.get_mqtt_settings())
        assert settings["password_set"] is True
        assert "password" not in settings
        assert "broker-secret" not in repr(settings)
        assert settings["status"]["connected"] is True
    finally:
        asyncio.run(plugin._unload())


def test_qam_save_mqtt_settings_preserves_blank_password_and_restarts_publisher(monkeypatch, tmp_path):
    FakeMqtt.instances.clear()
    decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(tmp_path),
        DECKY_PLUGIN_VERSION="0.1.0",
        DECKY_USER="deck",
        logger=FakeLogger(),
    )
    monkeypatch.setitem(sys.modules, "decky", decky)
    module_name = "decky_plugin_main_for_mqtt_save_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, Path(__file__).resolve().parents[1] / "main.py"
    )
    plugin_main = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = plugin_main
    spec.loader.exec_module(plugin_main)

    config = AgentConfig(
        version="0.1.0",
        mqtt=MqttConfig(enabled=True, host="old-broker", username="agent", password="saved-secret"),
    )
    saved = []
    monkeypatch.setattr(plugin_main, "load_config", lambda *args: config)
    monkeypatch.setattr(
        plugin_main, "save_config", lambda settings_dir, value: saved.append((settings_dir, value))
    )
    monkeypatch.setattr(plugin_main, "Dispatcher", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "WakeOnLanMonitor", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "SensorCollector", FakeLifecycle)
    monkeypatch.setattr(plugin_main, "PuckMonitor", FakePuck)
    monkeypatch.setattr(plugin_main, "MqttPublisher", FakeMqtt)
    monkeypatch.setattr(plugin_main, "build_server", lambda *args, **kwargs: FakeServer())
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_session_env", lambda self: None)
    monkeypatch.setattr(plugin_main.Plugin, "_resolve_steam_root", lambda self: None)

    plugin = plugin_main.Plugin()
    asyncio.run(plugin._main())
    old_publisher = plugin.mqtt
    try:
        result = asyncio.run(
            plugin.set_mqtt_settings(
                {
                    "enabled": True,
                    "host": "new-broker",
                    "port": 8883,
                    "username": "agent",
                    "password": "",
                    "clear_password": False,
                    "tls": True,
                    "topic_prefix": "uc-steamos",
                    "discovery_prefix": "homeassistant",
                    "publish_interval_s": 10,
                }
            )
        )

        assert result["ok"] is True
        assert "password" not in result["settings"]
        assert plugin.config.mqtt.host == "new-broker"
        assert plugin.config.mqtt.password == "saved-secret"
        assert old_publisher.stopped is True
        assert plugin.mqtt is not old_publisher
        assert plugin.mqtt.started is True
        assert saved == [(str(tmp_path), plugin.config)]

        active_publisher = plugin.mqtt
        rejected = asyncio.run(plugin.set_mqtt_settings({"enabled": True, "host": "new-broker", "port": 0}))
        assert rejected == {"ok": False, "error": "Invalid MQTT configuration"}
        assert plugin.mqtt is active_publisher
        assert len(saved) == 1

        original_factory = plugin._new_mqtt_publisher

        def fail_constructor(value):
            raise RuntimeError("constructor failed")

        monkeypatch.setattr(plugin, "_new_mqtt_publisher", fail_constructor)
        constructor_failure = asyncio.run(
            plugin.set_mqtt_settings({"enabled": True, "host": "constructor-failure"})
        )
        assert constructor_failure == {"ok": False, "error": "Could not prepare MQTT publisher"}
        assert plugin.mqtt is active_publisher
        assert len(saved) == 1

        monkeypatch.setattr(plugin, "_new_mqtt_publisher", original_factory)
        original_stop = active_publisher.stop

        def fail_stop():
            raise RuntimeError("stop failed")

        active_publisher.stop = fail_stop
        stop_failure = asyncio.run(plugin.set_mqtt_settings({"enabled": True, "host": "stop-failure"}))
        assert stop_failure == {"ok": False, "error": "Could not stop the current MQTT publisher"}
        assert plugin.mqtt is not active_publisher
        assert plugin.mqtt.started is True
        assert FakeMqtt.instances[-2].stopped is True
        assert len(saved) == 1
        active_publisher.stop = original_stop

        cleared = asyncio.run(
            plugin.set_mqtt_settings(
                {
                    "enabled": True,
                    "host": "new-broker",
                    "port": 8883,
                    "username": "agent",
                    "password": "",
                    "clear_password": True,
                    "tls": True,
                    "topic_prefix": "uc-steamos",
                    "discovery_prefix": "homeassistant",
                    "publish_interval_s": 10,
                }
            )
        )
        assert cleared["ok"] is True
        assert plugin.config.mqtt.password == ""
        assert cleared["settings"]["password_set"] is False

        before_failure = plugin.config

        class FailingMqtt(FakeMqtt):
            def status(self):
                status = super().status()
                status["last_error"] = "client start failed"
                return status

        factories = [FailingMqtt, FakeMqtt]

        def replacement_factory(value):
            return factories.pop(0)(value)

        monkeypatch.setattr(plugin, "_new_mqtt_publisher", replacement_factory)
        failed = asyncio.run(
            plugin.set_mqtt_settings(
                {
                    "enabled": True,
                    "host": "broken-broker",
                    "port": 1883,
                    "username": "agent",
                    "password": "",
                    "clear_password": False,
                    "tls": False,
                    "topic_prefix": "uc-steamos",
                    "discovery_prefix": "homeassistant",
                    "publish_interval_s": 5,
                }
            )
        )
        assert failed == {"ok": False, "error": "MQTT failed to start"}
        assert plugin.config == before_failure
        assert plugin.mqtt.started is True
        assert [entry[1] for entry in saved[-2:]] == [
            replace(
                before_failure,
                mqtt=replace(
                    before_failure.mqtt, host="broken-broker", port=1883, tls=False, publish_interval_s=5.0
                ),
            ),
            before_failure,
        ]

        factories = [FailingMqtt, FakeMqtt]
        monkeypatch.setattr(plugin, "_new_mqtt_publisher", replacement_factory)
        rollback_writes = 0

        def fail_rollback_save(settings_dir, value):
            nonlocal rollback_writes
            rollback_writes += 1
            if rollback_writes == 2:
                raise OSError("rollback failed")
            saved.append((settings_dir, value))

        monkeypatch.setattr(plugin_main, "save_config", fail_rollback_save)
        rollback_failed = asyncio.run(
            plugin.set_mqtt_settings(
                {
                    "enabled": True,
                    "host": "rollback-failure-broker",
                    "port": 1883,
                    "username": "agent",
                    "password": "",
                    "clear_password": False,
                    "tls": False,
                    "topic_prefix": "uc-steamos",
                    "discovery_prefix": "homeassistant",
                    "publish_interval_s": 5,
                }
            )
        )
        assert rollback_failed == {
            "ok": False,
            "error": "MQTT failed to start and the saved configuration could not be restored",
        }
        assert plugin.config == before_failure
        assert plugin.mqtt.started is True
        assert plugin.mqtt.stopped is False

        plugin._unloading = True
        rejected_shutdown = asyncio.run(plugin.set_mqtt_settings({}))
        assert rejected_shutdown == {"ok": False, "error": "Plugin is shutting down"}
        plugin._unloading = False
    finally:
        asyncio.run(plugin._unload())
