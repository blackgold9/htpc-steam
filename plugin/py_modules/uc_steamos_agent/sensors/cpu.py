"""CPU sensors: temp, load, clock, power.

Ground truth (docs/hardware-notes.md): `k10temp` hwmon, `temp1_input`
labeled "Tctl" on the AMD desktop test box — no CPU package power was
found anywhere in hwmon on that box, so read_power_w is a best-effort
probe expected to return None on similar hardware. Fused-die APU naming
(Deck-class hardware) is unverified — see hardware-notes.md's open items.
"""

import os

from . import sysfs_util

CPU_TEMP_HWMON_NAMES = ["k10temp", "coretemp"]  # AMD desktop, Intel — APU naming unverified
CPU_TEMP_LABELS = ["Tctl", "Tdie", "Package id 0", "Core 0"]
CPU_POWER_HWMON_NAMES = ["k10temp", "amd_energy"]


def read_cpu_name(proc_root: str = "/proc") -> str:
    try:
        with open(f"{proc_root}/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return "CPU"


def read_temp_c(sys_root: str = "/sys") -> float | None:
    for hwmon_name in CPU_TEMP_HWMON_NAMES:
        hwmon_dir = sysfs_util.find_hwmon_by_name(hwmon_name, sys_root)
        if hwmon_dir is None:
            continue
        for label in CPU_TEMP_LABELS:
            value = sysfs_util.find_temp_input_by_label(hwmon_dir, label)
            if value is not None:
                return value / 1000.0
    return None


def read_clock_mhz(sys_root: str = "/sys") -> float | None:
    cpu_root = os.path.join(sys_root, "devices", "system", "cpu")
    try:
        entries = sorted(os.listdir(cpu_root))
    except OSError:
        return None
    freqs = []
    for entry in entries:
        if not (entry.startswith("cpu") and entry[3:].isdigit()):
            continue
        value = sysfs_util.read_value(os.path.join(cpu_root, entry, "cpufreq", "scaling_cur_freq"))
        if value is not None:
            freqs.append(value)
    if not freqs:
        return None
    return sum(freqs) / len(freqs) / 1000.0  # kHz -> MHz


def read_power_w(sys_root: str = "/sys") -> float | None:
    for hwmon_name in CPU_POWER_HWMON_NAMES:
        hwmon_dir = sysfs_util.find_hwmon_by_name(hwmon_name, sys_root)
        if hwmon_dir is None:
            continue
        try:
            entries = sorted(os.listdir(hwmon_dir))
        except OSError:
            continue
        for entry in entries:
            if entry.startswith("power") and entry.endswith("_input"):
                value = sysfs_util.read_value(os.path.join(hwmon_dir, entry))
                if value is not None:
                    return value / 1_000_000  # microwatts -> watts
    return None


class CpuLoadSampler:
    """Stateful: needs two /proc/stat snapshots to compute a load delta."""

    def __init__(self, proc_root: str = "/proc"):
        self._proc_root = proc_root
        self._prev = None  # (idle, total)

    def _read_stat(self):
        with open(os.path.join(self._proc_root, "stat")) as f:
            line = f.readline()
        fields = [int(x) for x in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
        total = sum(fields)
        return idle, total

    def sample(self) -> float | None:
        try:
            idle, total = self._read_stat()
        except (OSError, ValueError, IndexError):
            return None
        if self._prev is None:
            self._prev = (idle, total)
            return None
        prev_idle, prev_total = self._prev
        self._prev = (idle, total)
        delta_total = total - prev_total
        delta_idle = idle - prev_idle
        if delta_total <= 0:
            return None
        return max(0.0, min(100.0, (1 - delta_idle / delta_total) * 100))
