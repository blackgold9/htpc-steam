"""Storage sensors: usage via statvfs, temp via NVMe hwmon.

Defaults to /home rather than the OS partition, since that's where the
Steam library lives and where usage is actually meaningful to a user.

Ground truth (docs/hardware-notes.md): `nvme` hwmon, `temp1_input` labeled
"Composite" — the NVMe spec's standard overall-drive temperature sensor.
"""

import os

from . import sysfs_util

NVME_HWMON_NAME = "nvme"
NVME_TEMP_LABEL = "Composite"


def read_usage(path: str = "/home") -> tuple[float | None, float | None, float | None]:
    """Returns (used_gb, total_gb, used_pct) for the filesystem containing `path`."""
    try:
        st = os.statvfs(path)
    except OSError:
        return None, None, None
    total_bytes = st.f_frsize * st.f_blocks
    if total_bytes == 0:
        return None, None, None
    free_bytes = st.f_frsize * st.f_bavail
    used_bytes = total_bytes - free_bytes
    total_gb = total_bytes / (1024**3)
    used_gb = used_bytes / (1024**3)
    used_pct = (used_bytes / total_bytes) * 100
    return used_gb, total_gb, used_pct


def read_temp_c(sys_root: str = "/sys") -> float | None:
    hwmon_dir = sysfs_util.find_hwmon_by_name(NVME_HWMON_NAME, sys_root)
    value = sysfs_util.find_temp_input_by_label(hwmon_dir, NVME_TEMP_LABEL)
    return value / 1000.0 if value is not None else None
