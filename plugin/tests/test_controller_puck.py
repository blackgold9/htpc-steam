import os
import threading
import time

from uc_steamos_agent.controller_puck import PuckMonitor, PuckState


class FakeClock:
    def __init__(self, monotonic=100.0, wall=1_800_000_000.0):
        self.monotonic_value = monotonic
        self.wall_value = wall

    def monotonic(self):
        return self.monotonic_value

    def wall(self):
        return self.wall_value

    def advance(self, seconds):
        self.monotonic_value += seconds
        self.wall_value += seconds


def test_confirmed_pickup_requires_known_docked_state_and_charge_transition():
    clock = FakeClock()
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall, boot_id="boot-test")

    state.consume(bytes.fromhex("43 02 36 59 0f 78 0f 0c 12 6f 01 a9 01 5f 62"), "if02")
    clock.advance(0.2)
    state.consume(bytes.fromhex("79 01"), "if06")
    clock.advance(1.3)
    state.consume(bytes.fromhex("43 01 36 19 0f 28 0f a4 01 00 00 00 00 5f 62"), "if02")

    snapshot = state.snapshot()
    assert snapshot["docked"] is False
    assert snapshot["charge_state"] == "discharging"
    assert snapshot["battery_percent"] == 54
    assert snapshot["pickup_candidate"] is False
    assert snapshot["last_pickup_event"] == {
        "boot_id": "boot-test",
        "sequence": 1,
        "timestamp": 1_800_000_001.5,
        "confirmation_delay_ms": 1300,
        "source": "wireless_then_charge",
    }
    assert snapshot["diagnostics"]["confirmed_pickup_count"] == 1


def test_events_since_supports_polling_consumers_without_replaying_old_pickups():
    clock = FakeClock()
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall)

    for _ in range(2):
        state.consume(bytes.fromhex("43 02 36"), "if02")
        clock.advance(0.1)
        state.consume(bytes.fromhex("79 01"), "if06")
        clock.advance(0.2)
        state.consume(bytes.fromhex("43 01 36"), "if02")
        clock.advance(0.1)

    assert [event["sequence"] for event in state.events_since(0)["events"]] == [1, 2]
    assert [event["sequence"] for event in state.events_since(1)["events"]] == [2]
    assert state.events_since(2)["events"] == []


def test_events_cursor_exposes_restart_before_sequence_catches_up():
    previous = PuckState(boot_id="boot-a")
    previous.consume(bytes.fromhex("43 02 36"), "if02")
    previous.consume(bytes.fromhex("79 01"), "if06")
    previous.consume(bytes.fromhex("43 01 36"), "if02")
    previous_cursor = previous.events_since(0)

    restarted = PuckState(boot_id="boot-b")
    cursor = restarted.events_since(previous_cursor["current_sequence"])

    assert cursor == {"boot_id": "boot-b", "current_sequence": 0, "events": []}


def test_event_listener_gets_immediate_candidate_and_confirmed_pickup():
    clock = FakeClock()
    events = []
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall, boot_id="boot-test")
    state.add_event_listener(events.append)

    state.consume(bytes.fromhex("43 02 36"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")
    assert events == [
        {
            "event_type": "pickup_candidate",
            "timestamp": 1_800_000_000.0,
            "battery_percent": 54,
        }
    ]

    clock.advance(1.25)
    state.consume(bytes.fromhex("43 01 36"), "if02")
    assert events[1] == {
        "event_type": "picked_up",
        "boot_id": "boot-test",
        "sequence": 1,
        "timestamp": 1_800_000_001.25,
        "confirmation_delay_ms": 1250,
        "source": "wireless_then_charge",
        "battery_percent": 54,
    }


def test_event_listener_can_be_removed():
    events = []
    state = PuckState()
    state.add_event_listener(events.append)
    state.remove_event_listener(events.append)

    state.consume(bytes.fromhex("43 02 36"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")

    assert events == []


def _wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_monitor_reads_reports_and_stops_cleanly():
    read_fd, write_fd = os.pipe()
    monitor = PuckMonitor(path_provider=lambda: [f"/proc/self/fd/{read_fd}"], rescan_interval_s=0.01)
    monitor.start()
    try:
        os.write(write_fd, bytes.fromhex("43 02 36"))
        _wait_until(lambda: monitor.snapshot()["docked"] is True)
        os.write(write_fd, bytes.fromhex("79 01"))
        _wait_until(lambda: monitor.snapshot()["pickup_candidate"] is True)
        os.write(write_fd, bytes.fromhex("43 01 36"))
        _wait_until(lambda: monitor.snapshot()["diagnostics"]["confirmed_pickup_count"] == 1)
    finally:
        monitor.stop()
        os.close(read_fd)
        os.close(write_fd)

    assert monitor.running is False


def test_wireless_disconnect_alone_never_confirms_pickup():
    clock = FakeClock()
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall)
    state.consume(bytes.fromhex("43 04 64"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")

    assert state.snapshot()["pickup_candidate"] is True
    clock.advance(3.1)
    snapshot = state.snapshot()

    assert snapshot["pickup_candidate"] is False
    assert snapshot["last_pickup_event"] is None
    assert snapshot["diagnostics"]["confirmed_pickup_count"] == 0
    assert snapshot["diagnostics"]["unconfirmed_disconnect_count"] == 1


def test_expired_candidate_notifies_event_listeners():
    clock = FakeClock()
    events = []
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall)
    state.add_event_listener(events.append)
    state.consume(bytes.fromhex("43 04 64"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")

    clock.advance(3.1)
    state.snapshot()

    assert events[-1] == {
        "event_type": "candidate_expired",
        "timestamp": 1_800_000_003.1,
        "battery_percent": 100,
    }


def test_starting_while_already_discharging_does_not_replay_pickup():
    state = PuckState()
    state.consume(bytes.fromhex("43 01 36"), "if02")

    snapshot = state.snapshot()
    assert snapshot["docked"] is False
    assert snapshot["last_pickup_event"] is None
    assert state.events_since(0)["events"] == []


def test_charge_transition_without_immediate_candidate_does_not_confirm_pickup():
    state = PuckState()
    state.consume(bytes.fromhex("43 02 36"), "if02")
    state.consume(bytes.fromhex("43 01 36"), "if02")

    snapshot = state.snapshot()
    assert snapshot["docked"] is False
    assert snapshot["last_pickup_event"] is None
    assert snapshot["diagnostics"]["confirmed_pickup_count"] == 0


def test_redock_rejects_pending_candidate_for_soak_diagnostics():
    state = PuckState()
    state.consume(bytes.fromhex("43 02 36"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")
    state.consume(bytes.fromhex("43 02 36"), "if02")

    snapshot = state.snapshot()
    assert snapshot["pickup_candidate"] is False
    assert snapshot["diagnostics"]["unconfirmed_disconnect_count"] == 1


def test_device_loss_invalidates_state_and_rejects_candidate():
    state = PuckState()
    state.consume(bytes.fromhex("43 02 36"), "if02")
    state.consume(bytes.fromhex("79 01"), "if06")

    state.device_lost()
    snapshot = state.snapshot()

    assert snapshot["available"] is False
    assert snapshot["docked"] is None
    assert snapshot["charge_state"] is None
    assert snapshot["battery_percent"] is None
    assert snapshot["pickup_candidate"] is False
    assert snapshot["diagnostics"]["unconfirmed_disconnect_count"] == 1

    state.consume(bytes.fromhex("43 01 36"), "if02")
    assert state.snapshot()["last_pickup_event"] is None


def test_non_operational_battery_state_invalidates_dock_certainty_and_candidate():
    for value in (0, 3, 99):
        state = PuckState()
        state.consume(bytes((0x43, 2, 54)), "if02")
        state.consume(bytes((0x79, 1)), "if06")

        state.consume(bytes((0x43, value, 54)), "if02")
        invalidated = state.snapshot()
        assert invalidated["docked"] is None
        assert invalidated["pickup_candidate"] is False
        assert invalidated["diagnostics"]["unconfirmed_disconnect_count"] == 1

        state.consume(bytes((0x43, 1, 54)), "if02")
        assert state.snapshot()["last_pickup_event"] is None


def test_snapshot_listener_can_recursively_snapshot_monitor_without_deadlock():
    clock = FakeClock()
    state = PuckState(monotonic_fn=clock.monotonic, wall_time_fn=clock.wall)
    monitor = PuckMonitor(state=state)
    monitor._open_paths.add("/dev/puck-A-if02-hidraw")
    recursive_snapshots = []
    state.add_event_listener(lambda event: recursive_snapshots.append(monitor.snapshot()))
    state.consume(bytes((0x43, 2, 54)), "if02")
    state.consume(bytes((0x79, 1)), "if06")
    clock.advance(3.1)

    snapshot_result = {}
    snapshot_thread = threading.Thread(target=lambda: snapshot_result.update(monitor.snapshot()))
    snapshot_thread.start()
    snapshot_thread.join(1.0)

    assert not snapshot_thread.is_alive()
    assert snapshot_result["pickup_candidate"] is False
    assert recursive_snapshots[-1]["pickup_candidate"] is False


def test_descriptor_loss_and_snapshot_are_atomic(monkeypatch):
    path = "/dev/puck-A-if02-hidraw"
    state = PuckState()
    state.consume(bytes((0x43, 2, 54)), "if02")
    state.consume(bytes((0x79, 1)), "if06")
    monitor = PuckMonitor(state=state)
    monitor._open_paths.add(path)
    monitor._selected_device = path.removesuffix("-if02-hidraw")
    descriptors = {path: 42}

    loss_started = threading.Event()
    allow_loss = threading.Event()
    snapshot_captured = threading.Event()
    allow_snapshot_return = threading.Event()
    snapshot_result = {}
    original_device_lost = state.device_lost
    original_snapshot = state.snapshot

    def blocked_device_lost():
        loss_started.set()
        assert allow_loss.wait(1.0)
        original_device_lost()

    def observed_snapshot():
        captured = original_snapshot()
        snapshot_captured.set()
        assert allow_snapshot_return.wait(1.0)
        return captured

    class FakeSelector:
        def unregister(self, fd):
            assert fd == 42

    state.device_lost = blocked_device_lost
    state.snapshot = observed_snapshot
    monkeypatch.setattr(os, "close", lambda fd: None)

    close_thread = threading.Thread(target=monitor._close_path, args=(FakeSelector(), descriptors, path))
    close_thread.start()
    assert loss_started.wait(1.0)

    snapshot_thread = threading.Thread(target=lambda: snapshot_result.update(monitor.snapshot()))
    snapshot_thread.start()
    snapshot_captured.wait(0.2)
    allow_loss.set()
    allow_snapshot_return.set()
    close_thread.join(1.0)
    snapshot_thread.join(1.0)

    assert not close_thread.is_alive()
    assert not snapshot_thread.is_alive()
    assert monitor._selected_device is None
    assert snapshot_result["available"] is False
    assert snapshot_result["docked"] is None
    assert snapshot_result["charge_state"] is None
    assert snapshot_result["battery_percent"] is None
    assert snapshot_result["pickup_candidate"] is False


def test_scan_closes_fd_when_selector_registration_fails(monkeypatch):
    path = "/dev/puck-A-if02-hidraw"
    closed_fds = []

    class FakeSelector:
        def register(self, fd, events, registered_path):
            raise OSError("registration failed")

    monitor = PuckMonitor(path_provider=lambda: [path])
    descriptors = {}
    monkeypatch.setattr(os, "open", lambda opened_path, flags: 42)
    monkeypatch.setattr(os, "close", closed_fds.append)

    monitor._scan(FakeSelector(), descriptors)

    assert closed_fds == [42]
    assert descriptors == {}


def test_scan_recovers_when_failed_device_disappears_and_another_device_opens(monkeypatch):
    failed_path = "/dev/puck-A-if02-hidraw"
    valid_path = "/dev/puck-B-if02-hidraw"
    provided_paths = [failed_path]
    opened_paths = []

    class FakeSelector:
        def register(self, fd, events, path):
            opened_paths.append(path)

    def fake_open(path, flags):
        del flags
        if path == failed_path:
            raise OSError("unopenable")
        return 42

    monitor = PuckMonitor(path_provider=lambda: provided_paths)
    descriptors = {}
    monkeypatch.setattr(os, "open", fake_open)

    monitor._scan(FakeSelector(), descriptors)
    provided_paths[:] = [valid_path]
    monitor._scan(FakeSelector(), descriptors)

    assert descriptors == {valid_path: 42}
    assert opened_paths == [valid_path]


def test_monitor_does_not_mix_reports_from_multiple_pucks(tmp_path):
    a_read, a_write = os.pipe()
    b_read, b_write = os.pipe()
    a_path = tmp_path / "usb-Valve_Software_Steam_Controller_Puck_A-if02-hidraw"
    b_path = tmp_path / "usb-Valve_Software_Steam_Controller_Puck_B-if06-hidraw"
    a_path.symlink_to(f"/proc/self/fd/{a_read}")
    b_path.symlink_to(f"/proc/self/fd/{b_read}")
    monitor = PuckMonitor(path_provider=lambda: [str(b_path), str(a_path)], rescan_interval_s=0.01)
    monitor.start()
    try:
        os.write(a_write, bytes.fromhex("43 02 36"))
        _wait_until(lambda: monitor.snapshot()["docked"] is True)

        os.write(b_write, bytes.fromhex("79 01"))
        time.sleep(0.05)
        os.write(b_write, bytes.fromhex("43 01 36"))
        time.sleep(0.05)

        snapshot = monitor.snapshot()
        assert snapshot["docked"] is True
        assert snapshot["last_pickup_event"] is None
    finally:
        monitor.stop()
        for fd in (a_read, a_write, b_read, b_write):
            os.close(fd)
