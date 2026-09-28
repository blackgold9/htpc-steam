"""Steam Controller Puck HID report decoding and pickup state.

The Puck stays attached to USB when its controller is lifted, so udev cannot
observe pickup. The controller reports an immediate wireless edge (0x79) and a
slower, semantically stronger battery charge-state transition (0x43). This
module keeps those signals separate and only confirms pickup when charging or
charged changes to discharging.
"""

import glob
import os
import selectors
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable

_CHARGE_STATES = {
    0: "reset",
    1: "discharging",
    2: "charging",
    3: "source_validation",
    4: "charged",
}
_DOCKED_CHARGE_STATES = {2, 4}


def _default_device_paths() -> list[str]:
    base = "/dev/input/by-id/usb-Valve_Software_Steam_Controller_Puck_*"
    return sorted(set(glob.glob(f"{base}-if02-hidraw") + glob.glob(f"{base}-if06-hidraw")))


def _device_key(path: str) -> str:
    for suffix in ("-if02-hidraw", "-if06-hidraw"):
        if path.endswith(suffix):
            return path[: -len(suffix)]
    return path


class PuckState:
    """Thread-safe state machine for reports from one Steam Controller Puck."""

    def __init__(
        self,
        *,
        confirmation_window_s: float = 3.0,
        monotonic_fn: Callable[[], float] = time.monotonic,
        wall_time_fn: Callable[[], float] = time.time,
        boot_id: str | None = None,
    ):
        self._confirmation_window_s = confirmation_window_s
        self._monotonic = monotonic_fn
        self._wall_time = wall_time_fn
        self._boot_id = boot_id or uuid.uuid4().hex
        self._lock = threading.Lock()
        self._docked: bool | None = None
        self._charge_state: str | None = None
        self._battery_percent: int | None = None
        self._candidate_at: float | None = None
        self._event_sequence = 0
        self._last_pickup_event: dict | None = None
        self._events: deque[dict] = deque(maxlen=64)
        self._event_listeners: list[Callable[[dict], None]] = []
        self._notifications: list[dict] = []
        self._diagnostics = {
            "wireless_disconnect_count": 0,
            "wireless_connect_count": 0,
            "confirmed_pickup_count": 0,
            "unconfirmed_disconnect_count": 0,
        }

    def consume(self, report: bytes, interface: str | None = None) -> None:
        """Consume one complete HID input report, including its report ID."""
        del interface  # retained for diagnostics/API evolution
        if len(report) < 2:
            return
        with self._lock:
            if report[0] == 0x79:
                self._consume_wireless(report[1])
            elif report[0] == 0x43 and len(report) >= 3:
                self._consume_battery(report[1], report[2])
            notifications, listeners = self._take_notifications()
        self._dispatch_notifications(notifications, listeners)

    def add_event_listener(self, listener: Callable[[dict], None]) -> None:
        """Register a non-blocking listener for semantic puck events."""
        with self._lock:
            self._event_listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[dict], None]) -> None:
        """Remove a previously registered semantic-event listener."""
        with self._lock:
            try:
                self._event_listeners.remove(listener)
            except ValueError:
                pass

    def _consume_wireless(self, value: int) -> None:
        now = self._monotonic()
        self._expire_candidate(now)
        if value == 1:
            self._diagnostics["wireless_disconnect_count"] += 1
            if self._docked is True and self._candidate_at is None:
                self._candidate_at = now
                self._emit(
                    {
                        "event_type": "pickup_candidate",
                        "timestamp": self._wall_time(),
                        "battery_percent": self._battery_percent,
                    }
                )
        elif value == 2:
            self._diagnostics["wireless_connect_count"] += 1
            self._reject_candidate()

    def _consume_battery(self, value: int, percent: int) -> None:
        now = self._monotonic()
        self._expire_candidate(now)
        was_docked = self._docked
        self._charge_state = _CHARGE_STATES.get(value, "unknown")
        self._battery_percent = percent if percent <= 100 else None

        if value in _DOCKED_CHARGE_STATES:
            self._docked = True
            self._reject_candidate()
            return
        if value != 1:
            self._docked = None
            self._reject_candidate()
            return

        self._docked = False
        if was_docked is not True or self._candidate_at is None:
            self._clear_candidate()
            return

        delay_ms = round((now - self._candidate_at) * 1000)

        self._event_sequence += 1
        self._diagnostics["confirmed_pickup_count"] += 1
        event = {
            "boot_id": self._boot_id,
            "sequence": self._event_sequence,
            "timestamp": self._wall_time(),
            "confirmation_delay_ms": delay_ms,
            "source": "wireless_then_charge",
        }
        self._last_pickup_event = event
        self._events.append(event)
        self._emit({"event_type": "picked_up", **event, "battery_percent": self._battery_percent})
        self._clear_candidate()

    def _expire_candidate(self, now: float) -> None:
        if self._candidate_at is None:
            return
        if now - self._candidate_at > self._confirmation_window_s:
            self._emit(
                {
                    "event_type": "candidate_expired",
                    "timestamp": self._wall_time(),
                    "battery_percent": self._battery_percent,
                }
            )
            self._reject_candidate()

    def _reject_candidate(self) -> None:
        if self._candidate_at is not None:
            self._diagnostics["unconfirmed_disconnect_count"] += 1
            self._clear_candidate()

    def _clear_candidate(self) -> None:
        self._candidate_at = None

    def _emit(self, event: dict) -> None:
        self._notifications.append(event)

    def _take_notifications(self) -> tuple[list[dict], tuple[Callable[[dict], None], ...]]:
        notifications = self._notifications
        self._notifications = []
        return notifications, tuple(self._event_listeners)

    @staticmethod
    def _dispatch_notifications(notifications, listeners) -> None:
        for event in notifications:
            for listener in listeners:
                try:
                    listener(dict(event))
                except Exception:
                    pass

    def snapshot(self) -> dict:
        with self._lock:
            self._expire_candidate(self._monotonic())
            snapshot = {
                "schema_version": 1,
                "boot_id": self._boot_id,
                "current_sequence": self._event_sequence,
                "available": self._charge_state is not None,
                "docked": self._docked,
                "charge_state": self._charge_state,
                "battery_percent": self._battery_percent,
                "pickup_candidate": self._candidate_at is not None,
                "last_pickup_event": dict(self._last_pickup_event) if self._last_pickup_event else None,
                "diagnostics": dict(self._diagnostics),
            }
            notifications, listeners = self._take_notifications()
        self._dispatch_notifications(notifications, listeners)
        return snapshot

    def events_since(self, sequence: int) -> dict:
        """Return a restart-aware cursor and retained events newer than ``sequence``."""
        with self._lock:
            return {
                "boot_id": self._boot_id,
                "current_sequence": self._event_sequence,
                "events": [dict(event) for event in self._events if event["sequence"] > sequence],
            }

    def device_lost(self) -> None:
        """Forget observations that must not survive a USB disconnect."""
        with self._lock:
            self._reject_candidate()
            self._docked = None
            self._charge_state = None
            self._battery_percent = None


class PuckMonitor:
    """Background hidraw reader that tolerates unplug/replug and missing hardware."""

    def __init__(
        self,
        *,
        state: PuckState | None = None,
        path_provider: Callable[[], list[str]] = _default_device_paths,
        rescan_interval_s: float = 2.0,
    ):
        self._state = state or PuckState()
        self._path_provider = path_provider
        self._rescan_interval_s = rescan_interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._paths_lock = threading.RLock()
        self._open_paths: set[str] = set()
        self._selected_device: str | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="steam-puck-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=max(1.0, self._rescan_interval_s + 0.5))

    def snapshot(self) -> dict:
        with self._paths_lock:
            snapshot = self._state.snapshot()
            snapshot["available"] = bool(self._open_paths)
        return snapshot

    def events_since(self, sequence: int) -> dict:
        return self._state.events_since(sequence)

    def add_event_listener(self, listener: Callable[[dict], None]) -> None:
        self._state.add_event_listener(listener)

    def remove_event_listener(self, listener: Callable[[dict], None]) -> None:
        self._state.remove_event_listener(listener)

    def _run(self) -> None:
        selector = selectors.DefaultSelector()
        descriptors: dict[str, int] = {}
        last_scan = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_scan >= self._rescan_interval_s:
                    self._scan(selector, descriptors)
                    last_scan = now
                for key, _ in selector.select(timeout=min(0.1, self._rescan_interval_s)):
                    try:
                        report = os.read(key.fd, 64)
                    except (BlockingIOError, InterruptedError):
                        continue
                    except OSError:
                        report = b""
                    if report:
                        self._state.consume(report, os.path.basename(key.data))
                    else:
                        self._close_path(selector, descriptors, key.data)
        finally:
            for path in list(descriptors):
                self._close_path(selector, descriptors, path)
            selector.close()

    def _scan(self, selector: selectors.BaseSelector, descriptors: dict[str, int]) -> None:
        try:
            paths = sorted(self._path_provider())
        except OSError:
            return
        for path in paths:
            device = _device_key(path)
            if self._selected_device is not None and device != self._selected_device:
                continue
            if path in descriptors:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            try:
                selector.register(fd, selectors.EVENT_READ, path)
            except OSError:
                os.close(fd)
                continue
            descriptors[path] = fd
            self._selected_device = device
            with self._paths_lock:
                self._open_paths.add(path)

    def _close_path(self, selector: selectors.BaseSelector, descriptors: dict[str, int], path: str) -> None:
        fd = descriptors.pop(path, None)
        if fd is None:
            return
        try:
            selector.unregister(fd)
        except (KeyError, ValueError):
            pass
        os.close(fd)
        with self._paths_lock:
            self._open_paths.discard(path)
            self._state.device_lost()
        if not any(_device_key(open_path) == self._selected_device for open_path in descriptors):
            self._selected_device = None
