"""Network throughput: /sys/class/net/<iface>/statistics, delta-sampled.

Interface is auto-detected via /proc/net/route's default-route entry
(confirmed working on the test box: enp151s0), rather than hardcoded,
since the primary interface changes docked (ethernet) vs. undocked (wifi)
on a handheld.
"""

import os
import time


def default_interface(proc_root: str = "/proc") -> str | None:
    try:
        with open(os.path.join(proc_root, "net", "route")) as f:
            lines = f.readlines()[1:]
    except OSError:
        return None
    for line in lines:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "00000000":
            return fields[0]
    return None


def _read_bytes(iface: str, direction: str, sys_root: str) -> int | None:
    path = os.path.join(sys_root, "class", "net", iface, "statistics", f"{direction}_bytes")
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


class NetworkThroughputSampler:
    """Stateful: needs two samples to compute a rate."""

    def __init__(self, sys_root: str = "/sys", proc_root: str = "/proc", clock=time.monotonic):
        self._sys_root = sys_root
        self._proc_root = proc_root
        self._clock = clock
        self._prev = None  # (time, rx_bytes, tx_bytes)

    def sample(self) -> dict:
        empty = {"up_kbps": None, "down_kbps": None}
        iface = default_interface(self._proc_root)
        if iface is None:
            self._prev = None
            return empty

        rx = _read_bytes(iface, "rx", self._sys_root)
        tx = _read_bytes(iface, "tx", self._sys_root)
        now = self._clock()
        if rx is None or tx is None:
            self._prev = None
            return empty

        if self._prev is None:
            self._prev = (now, rx, tx)
            return empty

        prev_time, prev_rx, prev_tx = self._prev
        self._prev = (now, rx, tx)
        dt = now - prev_time
        if dt <= 0:
            return empty

        down_kbps = max(0.0, (rx - prev_rx) * 8 / 1000 / dt)
        up_kbps = max(0.0, (tx - prev_tx) * 8 / 1000 / dt)
        return {"up_kbps": up_kbps, "down_kbps": down_kbps}
