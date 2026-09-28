import json
import threading
from collections.abc import Callable

from uc_steamos_agent.config import AgentConfig, MqttConfig
from uc_steamos_agent.mqtt.publisher import MqttPublisher

AGENT_ID = "0123456789abcdef0123456789abcdef"


class FakePublishResult:
    def __init__(self, rc=0, published=True):
        self.rc = rc
        self._published = published

    def wait_for_publish(self, timeout=None):
        return True

    def is_published(self):
        return self._published


class FakeClient:
    def __init__(self, client_id):
        self.client_id = client_id
        self.on_connect = None
        self.on_disconnect = None
        self.on_message = None
        self.calls = []
        self.event_published = threading.Event()
        self.publish_hook: Callable[[str, str], None] | None = None
        self.publish_rc = 0
        self.publish_succeeds = True
        self.disconnect_error: Exception | None = None
        self.loop_stop_error: Exception | None = None

    def username_pw_set(self, username, password):
        self.calls.append(("credentials", username, password))

    def tls_set(self):
        self.calls.append(("tls",))

    def will_set(self, topic, payload, qos, retain):
        self.calls.append(("will", topic, payload, qos, retain))

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect_async", host, port, keepalive))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))
        if self.loop_stop_error:
            raise self.loop_stop_error

    def disconnect(self):
        self.calls.append(("disconnect",))
        if self.disconnect_error:
            raise self.disconnect_error

    def _sock_close(self):
        self.calls.append(("sock_close",))

    def subscribe(self, topic, qos):
        self.calls.append(("subscribe", topic, qos))

    def publish(self, topic, payload, qos, retain):
        self.calls.append(("publish", topic, payload, qos, retain))
        if self.publish_hook is not None:
            self.publish_hook(topic, payload)
        if topic.endswith("/puck/event"):
            self.event_published.set()
        return FakePublishResult(self.publish_rc, self.publish_succeeds)

    def fire_connect(self):
        self.on_connect(self, None, {}, 0, None)


class FakePuck:
    def __init__(self):
        self.listeners = []

    def add_event_listener(self, listener):
        self.listeners.append(listener)

    def remove_event_listener(self, listener):
        try:
            self.listeners.remove(listener)
        except ValueError:
            pass

    def snapshot(self):
        return {
            "schema_version": 1,
            "available": True,
            "docked": True,
            "charge_state": "charging",
            "battery_percent": 54,
            "pickup_candidate": False,
            "last_pickup_event": None,
            "diagnostics": {
                "wireless_disconnect_count": 0,
                "wireless_connect_count": 0,
                "confirmed_pickup_count": 0,
                "unconfirmed_disconnect_count": 0,
            },
        }

    def emit(self, event):
        for listener in self.listeners:
            listener(event)


def _sensors():
    return {
        "cpu": {"name": "CPU", "temp_c": 50.0, "load_pct": 5.0, "clock_mhz": 3000, "power_w": 10.0},
        "gpu": {"name": "GPU", "temp_c": 45.0, "load_pct": 3.0, "has_dedicated_gpu": True},
        "memory": {"used_gb": 4.0, "total_gb": 16.0},
        "storage": {"used_gb": 20.0, "total_gb": 100.0, "used_pct": 20.0, "temp_c": 40.0},
        "network": {"up_kbps": 1.0, "down_kbps": 2.0},
        "motherboard": {"temp_avg_c": None, "temp_max_c": None},
        "fans": [],
        "battery": {"present": False, "percent": None, "charging": None, "power_w": None},
    }


def test_publisher_announces_discovery_state_and_immediate_events_without_commands():
    mqtt = MqttConfig(
        enabled=True,
        host="ha.internal",
        username="agent",
        password="secret",
        publish_interval_s=60,
    )
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID, mqtt=mqtt)
    client = FakeClient(client_id="unused")
    puck = FakePuck()
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=lambda: [{"appid": 10, "name": "Game", "last_played": 20}],
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
        boot_id="boot-test",
    )

    publisher.start()
    client.fire_connect()

    assert ("credentials", "agent", "secret") in client.calls
    assert ("will", f"uc-steamos/{AGENT_ID}/availability", "offline", 1, True) in client.calls
    assert ("connect_async", "ha.internal", 1883, 30) in client.calls
    assert ("subscribe", "homeassistant/status", 0) in client.calls
    assert not any(call[0] == "subscribe" and "command" in call[1] for call in client.calls)

    publishes = [call for call in client.calls if call[0] == "publish"]
    online = next(call for call in publishes if call[1].endswith("/availability") and call[2] == "online")
    assert online[3:] == (1, True)
    discovery = [call for call in publishes if call[1].startswith("homeassistant/device/")]
    assert len(discovery) == 2
    assert all(call[3:] == (1, True) for call in discovery)
    assert all("command_topic" not in call[2] for call in discovery)

    system = next(call for call in publishes if call[1].endswith("/system/state"))
    assert json.loads(system[2])["recent_games_count"] == 1
    assert system[3:] == (1, True)
    assert any(call[1].endswith("/puck/state") and call[3:] == (1, True) for call in publishes)
    assert any(call[1].endswith("/games/state") and call[3:] == (1, True) for call in publishes)

    puck.emit({"event_type": "pickup_candidate", "timestamp": 123.0, "battery_percent": 54})
    assert client.event_published.wait(1.0)
    event = [call for call in client.calls if call[0] == "publish" and call[1].endswith("/puck/event")][-1]
    event_payload = json.loads(event[2])
    assert event_payload["event_type"] == "pickup_candidate"
    assert event_payload["event_id"] == "boot-test:1"
    assert event_payload["boot_id"] == "boot-test"
    assert event_payload["sequence"] == 1
    assert event[3:] == (0, False)

    publisher.stop()
    assert ("publish", f"uc-steamos/{AGENT_ID}/availability", "offline", 1, True) in client.calls
    assert ("disconnect",) in client.calls
    assert ("loop_stop",) in client.calls


def test_dynamic_discovery_is_reconciled_without_republishing_unchanged_payloads():
    mqtt = MqttConfig(enabled=True, host="ha.internal", publish_interval_s=60)
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID, mqtt=mqtt)
    client = FakeClient(client_id="unused")
    puck = FakePuck()
    sensors = _sensors()
    publisher = MqttPublisher(
        config,
        sensors_fn=lambda: sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    agent_topic = f"homeassistant/device/uc_steamos_{AGENT_ID}/config"

    publisher.start()
    try:
        client.fire_connect()
        client.calls.clear()

        publisher._publish_states()
        assert not any(
            call[0] == "publish" and call[1].startswith("homeassistant/device/") for call in client.calls
        )

        sensors["battery"] = {"present": True, "percent": 80, "charging": True, "power_w": 12.0}
        sensors["fans"] = [{"label": "CPU Fan", "rpm": 1200}]
        publisher._publish_states()
        additions = [call for call in client.calls if call[0] == "publish" and call[1] == agent_topic]
        assert len(additions) == 1
        assert additions[0][3:] == (1, True)
        added_components = json.loads(additions[0][2])["components"]
        cpu_fan_key = next(key for key, value in added_components.items() if value.get("name") == "CPU Fan")
        assert {"system_battery", "system_charging", "system_battery_power", cpu_fan_key} <= set(
            added_components
        )

        client.calls.clear()
        sensors["fans"] = [{"label": "Case Fan", "rpm": 900}]
        publisher._publish_states()
        label_change = [call for call in client.calls if call[0] == "publish" and call[1] == agent_topic]
        assert len(label_change) == 2
        marker_components = json.loads(label_change[0][2])["components"]
        clean_components = json.loads(label_change[1][2])["components"]
        case_fan_key = next(key for key, value in clean_components.items() if value.get("name") == "Case Fan")
        assert marker_components[cpu_fan_key] == {"platform": "sensor"}
        assert case_fan_key in marker_components
        assert cpu_fan_key not in clean_components
        assert case_fan_key in clean_components
        assert all(call[3:] == (1, True) for call in label_change)

        client.calls.clear()
        sensors["battery"] = {"present": False, "percent": None, "charging": None, "power_w": None}
        sensors["fans"] = []
        publisher._publish_states()
        removals = [call for call in client.calls if call[0] == "publish" and call[1] == agent_topic]
        assert len(removals) == 2
        marker_components = json.loads(removals[0][2])["components"]
        assert marker_components[case_fan_key] == {"platform": "sensor"}
        assert marker_components["system_battery"] == {"platform": "sensor"}
        assert marker_components["system_charging"] == {"platform": "binary_sensor"}
        assert marker_components["system_battery_power"] == {"platform": "sensor"}
        clean_components = json.loads(removals[1][2])["components"]
        assert not {
            case_fan_key,
            "system_battery",
            "system_charging",
            "system_battery_power",
        } & set(clean_components)
    finally:
        publisher.stop()


def test_optional_mqtt_start_failure_does_not_break_the_agent():
    config = AgentConfig(
        agent_id=AGENT_ID,
        mqtt=MqttConfig(enabled=True, host="ha.internal"),
    )
    puck = FakePuck()
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: (_ for _ in ()).throw(ImportError("paho missing")),
    )

    publisher.start()

    assert publisher.last_error == "MQTT client initialization failed"


def test_status_exposes_connection_health_without_credentials():
    config = AgentConfig(
        agent_id=AGENT_ID,
        mqtt=MqttConfig(enabled=True, host="ha.internal", username="agent", password="secret"),
    )
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    try:
        client.fire_connect()
        status = publisher.status()
        assert status == {
            "enabled": True,
            "connected": True,
            "broker_online": True,
            "last_error": None,
        }
        assert "secret" not in repr(status)
    finally:
        publisher.stop()


def test_stop_unregisters_puck_event_listener():
    puck = FakePuck()
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig())
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
    )
    publisher.start()
    assert len(puck.listeners) == 1

    publisher.stop()

    assert puck.listeners == []


def test_stop_is_exception_safe_after_transport_teardown_failure():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    client.disconnect_error = RuntimeError("disconnect failed")
    client.loop_stop_error = RuntimeError("loop stop failed")
    puck = FakePuck()
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()

    publisher.stop()
    publisher.stop()

    assert publisher._client is None
    assert puck.listeners == []


def test_connection_reason_codes_are_exposed_as_sanitized_status():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()

    publisher._on_connect(client, None, {}, 5, None)
    assert publisher.status()["last_error"] == "Broker connection failed (reason code 5)"

    publisher._on_connect(client, None, {}, 0, None)
    assert publisher.status()["last_error"] is None
    publisher._on_disconnect(client, None, None, 7, None)
    assert publisher.status()["last_error"] == "Broker disconnected (reason code 7)"
    publisher.stop()


def test_puck_listener_never_runs_slow_state_collection_on_hid_thread():
    mqtt = MqttConfig(enabled=True, host="ha.internal", publish_interval_s=60)
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID, mqtt=mqtt)
    client = FakeClient(client_id="unused")
    puck = FakePuck()
    block_sensors = threading.Event()
    sensors_entered = threading.Event()
    release_sensors = threading.Event()
    listener_returned = threading.Event()

    def sensors_fn():
        if block_sensors.is_set():
            sensors_entered.set()
            release_sensors.wait(2.0)
        return _sensors()

    publisher = MqttPublisher(
        config,
        sensors_fn=sensors_fn,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
        boot_id="boot-test",
    )
    publisher.start()
    client.fire_connect()
    block_sensors.set()

    emit_thread = threading.Thread(
        target=lambda: (
            puck.emit({"event_type": "pickup_candidate", "timestamp": 123.0}),
            listener_returned.set(),
        )
    )
    emit_thread.start()
    try:
        assert listener_returned.wait(0.2)
        assert sensors_entered.wait(1.0)
    finally:
        release_sensors.set()
        emit_thread.join(1.0)
        publisher.stop()


def test_transient_events_are_not_accepted_until_connection_bootstrap_finishes():
    config = AgentConfig(
        agent_id=AGENT_ID,
        mqtt=MqttConfig(enabled=True, host="ha.internal", publish_interval_s=60),
    )
    client = FakeClient(client_id="unused")
    puck = FakePuck()
    injected = threading.Event()

    def emit_during_bootstrap(topic, payload):
        if topic.endswith("/availability") and payload == "online" and not injected.is_set():
            injected.set()
            puck.emit({"event_type": "pickup_candidate", "timestamp": 123.0})

    client.publish_hook = emit_during_bootstrap
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    try:
        client.fire_connect()
        assert injected.is_set()
        assert not client.event_published.wait(0.2)
    finally:
        publisher.stop()


def test_failed_bootstrap_publish_does_not_enable_transient_events():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    client.publish_rc = 4
    puck = FakePuck()
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    try:
        client.fire_connect()
        puck.emit({"event_type": "pickup_candidate", "timestamp": 123.0})
        assert not client.event_published.wait(0.2)
    finally:
        publisher.stop()


def test_queued_event_from_old_connection_generation_is_dropped():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher._client = client
    publisher._accept_publishing.set()
    publisher._connected.set()
    publisher._publish_puck_event({"event_type": "pickup_candidate", "timestamp": 123.0})
    queued = publisher._event_queue.get_nowait()

    publisher._on_disconnect(client, None, None, 1, None)
    publisher._publish_queued_event(queued)

    assert not client.event_published.is_set()


def test_failed_bootstrap_never_publishes_retained_online():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")

    def fail_discovery(topic, payload):
        del payload
        if topic.startswith("homeassistant/device/"):
            client.publish_rc = 4

    client.publish_hook = fail_discovery
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    try:
        client.fire_connect()
        online = [
            call
            for call in client.calls
            if call[:3] == ("publish", f"uc-steamos/{AGENT_ID}/availability", "online")
        ]
        assert online == []
        assert ("sock_close",) in client.calls
        assert ("disconnect",) not in client.calls
    finally:
        publisher.stop()


def test_bootstrap_serialization_failure_aborts_transport_without_false_online():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")

    def invalid_sensors():
        sensors = _sensors()
        sensors["cpu"]["temp_c"] = float("nan")
        return sensors

    publisher = MqttPublisher(
        config,
        sensors_fn=invalid_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    try:
        client.fire_connect()
        availability = [
            call[2] for call in client.calls if call[:2] == ("publish", f"uc-steamos/{AGENT_ID}/availability")
        ]
        assert "online" not in availability
        assert ("sock_close",) in client.calls
        assert not publisher._connected.is_set()
    finally:
        publisher.stop()


def test_disconnect_during_slow_bootstrap_cannot_restore_online_readiness():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    sensors_entered = threading.Event()
    release_sensors = threading.Event()

    def sensors_fn():
        sensors_entered.set()
        release_sensors.wait(2.0)
        return _sensors()

    publisher = MqttPublisher(
        config,
        sensors_fn=sensors_fn,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    connect_thread = threading.Thread(target=client.fire_connect)
    connect_thread.start()
    try:
        assert sensors_entered.wait(1.0)
        publisher._on_disconnect(client, None, None, 1, None)
        release_sensors.set()
        connect_thread.join(1.0)

        online = [
            call
            for call in client.calls
            if call[:3] == ("publish", f"uc-steamos/{AGENT_ID}/availability", "online")
        ]
        assert online == []
        assert not publisher._connected.is_set()
    finally:
        release_sensors.set()
        connect_thread.join(1.0)
        publisher.stop()


def test_stop_during_retained_online_publish_ends_with_retained_offline():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    online_entered = threading.Event()
    release_online = threading.Event()
    stop_finished = threading.Event()

    def block_online(topic, payload):
        if topic == f"uc-steamos/{AGENT_ID}/availability" and payload == "online":
            online_entered.set()
            release_online.wait(2.0)

    client.publish_hook = block_online
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    connect_thread = threading.Thread(target=client.fire_connect)
    connect_thread.start()

    def stop_publisher():
        publisher.stop()
        stop_finished.set()

    stop_thread = threading.Thread(target=stop_publisher)
    try:
        assert online_entered.wait(1.0)
        stop_thread.start()
        assert not stop_finished.wait(0.1)
        release_online.set()
        connect_thread.join(1.0)
        stop_thread.join(2.0)

        availability = [
            call[2] for call in client.calls if call[:2] == ("publish", f"uc-steamos/{AGENT_ID}/availability")
        ]
        assert availability[-2:] == ["online", "offline"]
        assert stop_finished.is_set()
    finally:
        release_online.set()
        connect_thread.join(1.0)
        if stop_thread.ident is not None:
            stop_thread.join(2.0)
        if publisher._client is not None:
            publisher.stop()


def test_home_assistant_birth_stop_still_publishes_retained_offline():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    bootstrap_count = 0
    birth_entered = threading.Event()
    release_birth = threading.Event()

    def sensors_fn():
        nonlocal bootstrap_count
        bootstrap_count += 1
        if bootstrap_count == 2:
            birth_entered.set()
            release_birth.wait(2.0)
        return _sensors()

    publisher = MqttPublisher(
        config,
        sensors_fn=sensors_fn,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    client.fire_connect()
    message = type("Message", (), {"topic": "homeassistant/status", "payload": b"online"})()
    birth_thread = threading.Thread(target=publisher._on_message, args=(client, None, message))
    birth_thread.start()
    try:
        assert birth_entered.wait(1.0)
        publisher.stop()
        availability = [
            call[2] for call in client.calls if call[:2] == ("publish", f"uc-steamos/{AGENT_ID}/availability")
        ]
        assert availability[-1] == "offline"
    finally:
        release_birth.set()
        birth_thread.join(1.0)
        if publisher._client is not None:
            publisher.stop()


def test_disconnect_before_generation_bound_state_publish_drops_all_state():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    client.fire_connect()
    client.calls.clear()
    generation = publisher._connection_generation
    publish_entered = threading.Event()
    release_publish = threading.Event()
    original_publish = publisher._publish

    def pause_before_first_state(topic, payload, **kwargs):
        if topic.endswith("/system/state") and not publish_entered.is_set():
            publish_entered.set()
            release_publish.wait(2.0)
        return original_publish(topic, payload, **kwargs)

    publisher._publish = pause_before_first_state
    state_thread = threading.Thread(
        target=publisher._publish_states, kwargs={"required_generation": generation}
    )
    state_thread.start()
    try:
        assert publish_entered.wait(1.0)
        publisher._on_disconnect(client, None, None, 1, None)
        release_publish.set()
        state_thread.join(1.0)
        assert [call for call in client.calls if call[0] == "publish"] == []
    finally:
        release_publish.set()
        state_thread.join(1.0)
        publisher.stop()


def test_runtime_publish_failure_aborts_transport_for_last_will():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    client.fire_connect()
    client.calls.clear()
    client.publish_rc = 4

    publisher._publish_states(required_generation=publisher._connection_generation)

    assert ("sock_close",) in client.calls
    assert ("disconnect",) not in client.calls
    assert not publisher._connected.is_set()
    publisher.stop()


def test_stop_racing_client_creation_cannot_leave_live_network_loop():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    factory_entered = threading.Event()
    release_factory = threading.Event()
    stop_finished = threading.Event()

    def client_factory(client_id):
        del client_id
        factory_entered.set()
        release_factory.wait(2.0)
        return client

    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=client_factory,
    )
    start_thread = threading.Thread(target=publisher.start)
    start_thread.start()
    assert factory_entered.wait(1.0)

    def stop_publisher():
        publisher.stop()
        stop_finished.set()

    stop_thread = threading.Thread(target=stop_publisher)
    stop_thread.start()
    stop_finished.wait(0.1)
    release_factory.set()
    start_thread.join(1.0)
    stop_thread.join(1.0)

    assert stop_finished.is_set()
    assert publisher._client is None
    assert ("loop_stop",) in client.calls


def test_offline_publish_timeout_force_closes_instead_of_suppressing_last_will():
    config = AgentConfig(agent_id=AGENT_ID, mqtt=MqttConfig(enabled=True, host="ha.internal"))
    client = FakeClient(client_id="unused")
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    client.fire_connect()
    client.calls.clear()
    client.publish_succeeds = False

    publisher.stop()

    assert ("publish", f"uc-steamos/{AGENT_ID}/availability", "offline", 1, True) in client.calls
    assert ("sock_close",) in client.calls
    assert ("disconnect",) not in client.calls


def test_stop_publishes_offline_last_even_when_state_refresh_is_blocked():
    mqtt = MqttConfig(enabled=True, host="ha.internal", publish_interval_s=86400)
    config = AgentConfig(version="0.1.0", agent_id=AGENT_ID, mqtt=mqtt)
    client = FakeClient(client_id="unused")
    puck = FakePuck()
    block_sensors = threading.Event()
    sensors_entered = threading.Event()
    release_sensors = threading.Event()
    sensors_returned = threading.Event()

    def sensors_fn():
        if block_sensors.is_set():
            sensors_entered.set()
            release_sensors.wait(3.0)
            sensors_returned.set()
        return _sensors()

    publisher = MqttPublisher(
        config,
        sensors_fn=sensors_fn,
        puck=puck,
        games_fn=None,
        uinput_available_fn=lambda: True,
        client_factory=lambda client_id: client,
    )
    publisher.start()
    client.fire_connect()
    block_sensors.set()
    puck.emit({"event_type": "pickup_candidate", "timestamp": 123.0})
    assert sensors_entered.wait(1.0)

    publisher.stop()
    puck.emit({"event_type": "pickup_candidate", "timestamp": 124.0})
    offline_index = max(
        index
        for index, call in enumerate(client.calls)
        if call[:3] == ("publish", f"uc-steamos/{AGENT_ID}/availability", "offline")
    )
    release_sensors.set()
    assert sensors_returned.wait(1.0)

    assert not [call for call in client.calls[offline_index + 1 :] if call[0] == "publish"]


def test_stop_join_timeout_is_fixed_not_publish_interval_dependent():
    class CapturingThread:
        def __init__(self):
            self.timeout = None

        def join(self, timeout):
            self.timeout = timeout

    config = AgentConfig(
        agent_id=AGENT_ID,
        mqtt=MqttConfig(enabled=True, host="ha.internal", publish_interval_s=86400),
    )
    publisher = MqttPublisher(
        config,
        sensors_fn=_sensors,
        puck=FakePuck(),
        games_fn=None,
        uinput_available_fn=lambda: True,
    )
    thread = CapturingThread()
    publisher._thread = thread

    publisher.stop()

    assert thread.timeout == 1.0
