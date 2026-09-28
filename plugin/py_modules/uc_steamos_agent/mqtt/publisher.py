"""Read-only MQTT bridge for Home Assistant.

The bridge publishes discovery, retained snapshots, availability, and transient
controller events. It deliberately has no command-topic subscription.
"""

import copy
import json
import queue
import threading
import uuid
from collections.abc import Callable

from ..config import AgentConfig
from .discovery import discovery_messages

_STOP_WORKER = object()


def _default_client_factory(client_id: str):
    from paho.mqtt.client import CallbackAPIVersion, Client, MQTTv311

    return Client(CallbackAPIVersion.VERSION2, client_id=client_id, protocol=MQTTv311)


class MqttPublisher:
    def __init__(
        self,
        config: AgentConfig,
        *,
        sensors_fn: Callable[[], dict],
        puck,
        games_fn: Callable[[], list[dict]] | None,
        uinput_available_fn: Callable[[], bool],
        client_factory=_default_client_factory,
        boot_id: str | None = None,
    ):
        self._config = config
        self._mqtt = config.mqtt
        self._sensors_fn = sensors_fn
        self._puck = puck
        self._games_fn = games_fn
        self._uinput_available_fn = uinput_available_fn
        self._client_factory = client_factory
        self._boot_id = boot_id or uuid.uuid4().hex
        self._base = f"{self._mqtt.topic_prefix.rstrip('/')}/{config.agent_id}"
        self._client = None
        self._connected = threading.Event()
        self._stop = threading.Event()
        self._accept_publishing = threading.Event()
        self._publish_failed = threading.Event()
        self._broker_online = False
        self._stopped = False
        self._thread = None
        self._last_error: str | None = None
        self._event_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._publish_lock = threading.RLock()
        self._discovery_lock = threading.Lock()
        self._event_queue: queue.Queue = queue.Queue(maxsize=64)
        self._event_sequence = 0
        self._connection_generation = 0
        self._discovery_payloads: dict[str, dict] = {}
        self._listener_registered = True
        self._puck.add_event_listener(self._publish_puck_event)

    @property
    def enabled(self) -> bool:
        return bool(self._mqtt.enabled and self._mqtt.host)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def status(self) -> dict:
        with self._lifecycle_lock:
            return {
                "enabled": self.enabled,
                "connected": self._connected.is_set(),
                "broker_online": self._broker_online,
                "last_error": self._last_error,
            }

    def start(self) -> None:
        with self._lifecycle_lock:
            if not self.enabled or self._client is not None or self._stopped:
                return
            client = None
            try:
                self._stop.clear()
                self._accept_publishing.set()
                self._event_queue = queue.Queue(maxsize=64)
                client = self._client_factory(f"uc-steamos-{self._config.agent_id}")
                self._client = client
                client.on_connect = self._on_connect
                client.on_disconnect = self._on_disconnect
                client.on_message = self._on_message
                if self._mqtt.username:
                    client.username_pw_set(self._mqtt.username, self._mqtt.password)
                if self._mqtt.tls:
                    client.tls_set()
                client.will_set(f"{self._base}/availability", "offline", qos=1, retain=True)
                client.connect_async(self._mqtt.host, int(self._mqtt.port), keepalive=30)
                client.loop_start()
            except Exception:
                self._accept_publishing.clear()
                self._last_error = "MQTT client initialization failed"
                self._client = None
                if client is not None:
                    try:
                        client.disconnect()
                        client.loop_stop()
                    except Exception:
                        pass
                return
            self._last_error = None
            self._thread = threading.Thread(target=self._run, name="steamos-mqtt-publisher", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stopped = True
            if self._listener_registered:
                try:
                    self._puck.remove_event_listener(self._publish_puck_event)
                except Exception:
                    pass
                self._listener_registered = False
            broker_online = self._broker_online
            self._accept_publishing.clear()
            self._connection_generation += 1
            self._connected.clear()
        self._stop.set()
        try:
            self._event_queue.put_nowait(_STOP_WORKER)
        except queue.Full:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        client = self._client
        if client is None:
            return
        self._client = None
        self._thread = None
        try:
            graceful = not broker_online or self._publish_offline(client)
            try:
                if graceful:
                    client.disconnect()
                else:
                    self._abort_transport(client)
            except Exception:
                self._abort_transport(client)
        finally:
            try:
                client.loop_stop()
            except Exception:
                pass

    def _publish_interval(self) -> float:
        try:
            return max(1.0, float(self._mqtt.publish_interval_s))
        except (TypeError, ValueError):
            return 5.0

    def _invalidate_readiness(self) -> int:
        with self._lifecycle_lock:
            self._connection_generation += 1
            self._connected.clear()
            return self._connection_generation

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._event_queue.get(timeout=self._publish_interval())
            except queue.Empty:
                with self._lifecycle_lock:
                    generation = self._connection_generation
                    ready = self._connected.is_set() and self._accept_publishing.is_set()
                if ready:
                    self._publish_states(required_generation=generation)
                continue
            if event is _STOP_WORKER:
                return
            self._publish_queued_event(event)

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        del userdata, flags, properties
        reason = self._reason_code_value(reason_code)
        if reason != 0:
            with self._lifecycle_lock:
                self._last_error = f"Broker connection failed (reason code {reason})"
                self._broker_online = False
                self._connected.clear()
            return
        if not self._accept_publishing.is_set():
            return
        with self._lifecycle_lock:
            self._last_error = None
        generation = self._invalidate_readiness()
        self._publish_failed.clear()
        client.subscribe(f"{self._mqtt.discovery_prefix.rstrip('/')}/status", qos=0)
        if not self._publish_all(generation):
            if self._publish_failed.is_set():
                self._bootstrap_failed(client)
            return
        if not self._complete_bootstrap(generation) and self._publish_failed.is_set():
            self._bootstrap_failed(client)

    def _on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties) -> None:
        del client, userdata, disconnect_flags, properties
        reason = self._reason_code_value(reason_code)
        with self._lifecycle_lock:
            self._broker_online = False
            self._connection_generation += 1
            self._connected.clear()
            if reason != 0 and not self._stopped:
                self._last_error = f"Broker disconnected (reason code {reason})"

    @staticmethod
    def _reason_code_value(reason_code) -> int:
        value = getattr(reason_code, "value", reason_code)
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            return -1

    def _on_message(self, client, userdata, message) -> None:
        del userdata
        if not self._accept_publishing.is_set():
            return
        expected = f"{self._mqtt.discovery_prefix.rstrip('/')}/status"
        if message.topic == expected and message.payload.decode("utf-8", "replace") == "online":
            generation = self._invalidate_readiness()
            self._publish_failed.clear()
            if not self._publish_all(generation):
                if self._publish_failed.is_set():
                    self._bootstrap_failed(client)
                return
            if not self._complete_bootstrap(generation) and self._publish_failed.is_set():
                self._bootstrap_failed(client)

    def _publish_all(self, generation: int) -> bool:
        if not self._accept_publishing.is_set():
            return False
        sensors = self._safe_call(self._sensors_fn, {})
        with self._lifecycle_lock:
            if generation != self._connection_generation or not self._accept_publishing.is_set():
                return False
        if not self._publish_discovery(sensors, force=True, required_generation=generation):
            return False
        return self._publish_states(
            sensors,
            reconcile_discovery=False,
            required_generation=generation,
        )

    def _complete_bootstrap(self, generation: int) -> bool:
        with self._lifecycle_lock:
            if (
                generation != self._connection_generation
                or not self._accept_publishing.is_set()
                or self._publish_failed.is_set()
            ):
                return False
            if not self._publish(
                f"{self._base}/availability",
                "online",
                qos=1,
                retain=True,
                required_generation=generation,
            ):
                return False
            if generation != self._connection_generation or not self._accept_publishing.is_set():
                return False
            self._connected.set()
            self._broker_online = True
            return True

    def _bootstrap_failed(self, client) -> None:
        self._invalidate_readiness()
        if client is None:
            return
        self._abort_transport(client)

    def _publish_offline(self, client) -> bool:
        try:
            with self._publish_lock:
                result = client.publish(f"{self._base}/availability", "offline", qos=1, retain=True)
                if getattr(result, "rc", 0) != 0:
                    return False
                result.wait_for_publish(timeout=1.0)
                if not result.is_published():
                    return False
        except Exception:
            return False
        with self._lifecycle_lock:
            self._broker_online = False
        return True

    @staticmethod
    def _abort_transport(client) -> None:
        try:
            client._sock_close()
        except Exception:
            pass

    def _publish_discovery(
        self,
        sensors: dict,
        *,
        force: bool = False,
        required_generation: int | None = None,
    ) -> bool:
        with self._discovery_lock:
            for message in discovery_messages(self._config, sensors):
                previous = self._discovery_payloads.get(message.topic)
                if not force and previous == message.payload:
                    continue
                if previous is not None:
                    removed = previous["components"].keys() - message.payload["components"].keys()
                    if removed:
                        transition = copy.deepcopy(message.payload)
                        for key in removed:
                            transition["components"][key] = {
                                "platform": previous["components"][key]["platform"]
                            }
                        if not self._publish(
                            message.topic,
                            transition,
                            qos=message.qos,
                            retain=message.retain,
                            required_generation=required_generation,
                        ):
                            return False
                if not self._publish(
                    message.topic,
                    message.payload,
                    qos=message.qos,
                    retain=message.retain,
                    required_generation=required_generation,
                ):
                    return False
                self._discovery_payloads[message.topic] = copy.deepcopy(message.payload)
        return True

    def _publish_states(
        self,
        sensors: dict | None = None,
        *,
        reconcile_discovery: bool = True,
        required_generation: int | None = None,
    ) -> bool:
        sensors = sensors if sensors is not None else self._safe_call(self._sensors_fn, {})
        games = self._safe_call(self._games_fn, []) if self._games_fn is not None else []
        puck = self._safe_call(self._puck.snapshot, {"available": False})
        if not self._accept_publishing.is_set():
            return False
        if required_generation is not None:
            with self._lifecycle_lock:
                if required_generation != self._connection_generation or not self._accept_publishing.is_set():
                    return False
        if reconcile_discovery and not self._publish_discovery(
            sensors,
            required_generation=required_generation,
        ):
            return False
        system = {
            "version": self._config.version,
            "uinput_available": bool(self._safe_call(self._uinput_available_fn, False)),
            "wol_arm": self._config.wol_arm,
            "recent_games_count": len(games),
            "sensors": sensors,
        }
        if not self._publish(
            f"{self._base}/system/state",
            system,
            qos=1,
            retain=True,
            required_generation=required_generation,
        ):
            return False
        if not self._publish(
            f"{self._base}/games/state",
            {"games": games},
            qos=1,
            retain=True,
            required_generation=required_generation,
        ):
            return False
        if not self._publish(
            f"{self._base}/puck/state",
            puck,
            qos=1,
            retain=True,
            required_generation=required_generation,
        ):
            return False
        puck_availability = "online" if puck.get("available") else "offline"
        return self._publish(
            f"{self._base}/puck/availability",
            puck_availability,
            qos=1,
            retain=True,
            required_generation=required_generation,
        )

    def _publish_puck_event(self, event: dict) -> None:
        with self._lifecycle_lock:
            if not self._connected.is_set() or not self._accept_publishing.is_set():
                return
            generation = self._connection_generation
            with self._event_lock:
                self._event_sequence += 1
                sequence = self._event_sequence
        payload = dict(event)
        if "sequence" in payload:
            payload["puck_sequence"] = payload["sequence"]
        payload["boot_id"] = self._boot_id
        payload["sequence"] = sequence
        payload["event_id"] = f"{self._boot_id}:{sequence}"
        try:
            self._event_queue.put_nowait((generation, payload))
        except queue.Full:
            pass

    def _publish_queued_event(self, queued_event) -> None:
        generation, payload = queued_event
        with self._lifecycle_lock:
            if (
                generation != self._connection_generation
                or not self._connected.is_set()
                or not self._accept_publishing.is_set()
            ):
                return
            published = self._publish(
                f"{self._base}/puck/event",
                payload,
                qos=0,
                retain=False,
                required_generation=generation,
            )
        if published:
            self._publish_states(required_generation=generation)

    def _publish(
        self,
        topic: str,
        payload,
        *,
        qos: int,
        retain: bool,
        required_generation: int | None = None,
    ) -> bool:
        failed = False
        client = None
        with self._lifecycle_lock:
            if not self._accept_publishing.is_set():
                return False
            if required_generation is not None and required_generation != self._connection_generation:
                return False
            if not isinstance(payload, str):
                try:
                    payload = json.dumps(payload, separators=(",", ":"), allow_nan=False)
                except (TypeError, ValueError, OverflowError):
                    client = self._client
                    failed = True
            if not failed:
                with self._publish_lock:
                    client = self._client
                    if client is None or not self._accept_publishing.is_set():
                        return False
                    if required_generation is not None and required_generation != self._connection_generation:
                        return False
                    try:
                        result = client.publish(topic, payload, qos=qos, retain=retain)
                        if getattr(result, "rc", 0) != 0:
                            failed = True
                    except Exception:
                        failed = True
            if failed:
                self._publish_failed.set()
                self._connection_generation += 1
                self._connected.clear()
        if failed and client is not None:
            self._abort_transport(client)
            return False
        return True

    @staticmethod
    def _safe_call(fn, default):
        try:
            return fn()
        except Exception:
            return default
