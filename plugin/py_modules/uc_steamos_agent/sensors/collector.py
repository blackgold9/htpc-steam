"""Background sensor sampler -> in-memory snapshot, served by GET /sensors.

Each sub-collector's failure is caught individually so a renamed sysfs path
degrades one field to None instead of crashing the whole snapshot — see
docs/protocol.md for the wire schema this produces.

Motherboard temps (`motherboard.temp_avg_c`/`temp_max_c`) are always null
for now: on Windows, LibreHardwareMonitor reads these from a Super I/O chip
(nct6775/it87-class hwmon on Linux), but no such hwmon was present on the
test hardware to verify against — left unimplemented rather than guessed.
"""

import threading
import time

from . import battery, cpu, fan, gpu, memory, network, storage

SCHEMA_VERSION = 1
DEFAULT_POLL_INTERVAL_S = 2.0


class SensorCollector:
    def __init__(self, storage_path: str = "/home", poll_interval_s: float = DEFAULT_POLL_INTERVAL_S):
        self._storage_path = storage_path
        self._poll_interval_s = poll_interval_s
        self._cpu_load = cpu.CpuLoadSampler()
        self._network = network.NetworkThroughputSampler()
        self._lock = threading.Lock()
        self._snapshot = self._sample_once()
        self._stop = threading.Event()
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_interval_s + 1)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._snapshot)

    def _run(self) -> None:
        while not self._stop.is_set():
            snap = self._sample_once()
            with self._lock:
                self._snapshot = snap
            self._stop.wait(self._poll_interval_s)

    def _sample_once(self) -> dict:
        used_gb, total_gb = self._safe(memory.read_used_total_gb, (None, None))
        storage_used, storage_total, storage_pct = self._safe(
            lambda: storage.read_usage(self._storage_path), (None, None, None)
        )

        return {
            "schema_version": SCHEMA_VERSION,
            "timestamp": time.time(),
            "cpu": {
                "name": self._safe(cpu.read_cpu_name, "CPU"),
                "temp_c": self._safe(cpu.read_temp_c, None),
                "load_pct": self._safe(self._cpu_load.sample, None),
                "clock_mhz": self._safe(cpu.read_clock_mhz, None),
                "power_w": self._safe(cpu.read_power_w, None),
            },
            "gpu": {
                "name": "GPU",
                "temp_c": self._safe(gpu.read_temp_c, None),
                "load_pct": self._safe(gpu.read_load_pct, None),
                "has_dedicated_gpu": self._safe(gpu.has_dedicated_gpu, False),
            },
            "memory": {"used_gb": used_gb, "total_gb": total_gb},
            "storage": {
                "used_gb": storage_used,
                "total_gb": storage_total,
                "used_pct": storage_pct,
                "temp_c": self._safe(storage.read_temp_c, None),
            },
            "network": self._safe(self._network.sample, {"up_kbps": None, "down_kbps": None}),
            "motherboard": {"temp_avg_c": None, "temp_max_c": None},
            "fans": self._safe(fan.read_fan_speeds, []),
            "battery": self._safe(battery.read_battery, dict(battery.EMPTY)),
        }

    @staticmethod
    def _safe(fn, default):
        try:
            return fn()
        except Exception:
            return default
