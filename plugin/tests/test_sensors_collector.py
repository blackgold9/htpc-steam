import time

from uc_steamos_agent.sensors import cpu
from uc_steamos_agent.sensors.collector import SensorCollector


def test_snapshot_has_expected_schema_shape():
    collector = SensorCollector()
    snap = collector.snapshot()
    assert snap["schema_version"] == 1
    assert set(snap.keys()) == {
        "schema_version",
        "timestamp",
        "cpu",
        "gpu",
        "memory",
        "storage",
        "network",
        "motherboard",
        "fans",
        "battery",
    }
    assert set(snap["cpu"].keys()) == {"name", "temp_c", "load_pct", "clock_mhz", "power_w"}
    assert set(snap["gpu"].keys()) == {"name", "temp_c", "load_pct", "has_dedicated_gpu"}
    assert set(snap["storage"].keys()) == {"used_gb", "total_gb", "used_pct", "temp_c"}
    assert set(snap["network"].keys()) == {"up_kbps", "down_kbps"}
    assert set(snap["battery"].keys()) == {"present", "percent", "charging", "power_w"}
    assert isinstance(snap["fans"], list)


def test_a_broken_sub_collector_degrades_to_default_not_a_crash(monkeypatch):
    def boom():
        raise RuntimeError("simulated sysfs failure")

    monkeypatch.setattr(cpu, "read_temp_c", boom)
    collector = SensorCollector()
    snap = collector.snapshot()
    assert snap["cpu"]["temp_c"] is None  # degraded, not raised


def test_start_stop_runs_background_thread_without_crashing():
    collector = SensorCollector(poll_interval_s=0.05)
    collector.start()
    time.sleep(0.2)
    collector.stop()
    snap = collector.snapshot()
    assert snap["timestamp"] > 0
