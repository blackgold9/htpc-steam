"""GPU sensors: amdgpu hwmon for temp, /sys/class/drm for load.

Ground truth (docs/hardware-notes.md): GPU load isn't in hwmon at all —
it's read directly from /sys/class/drm/card*/device/gpu_busy_percent. The
card index isn't stable (the test box's active GPU was card1, not card0),
so the right card is discovered by checking which one's driver is amdgpu,
not assumed by index. MVP is AMD-only, matching SteamOS's primary hardware.

`has_dedicated_gpu` doesn't map cleanly to Linux: an APU's integrated GPU
also shows up as an `amdgpu` hwmon, identically to a discrete card. Here it
just means "an amdgpu-class GPU sensor was found at all", kept for wire
compatibility with the schema rather than a real discrete/integrated
distinction.
"""

import os

from . import sysfs_util

GPU_HWMON_NAME = "amdgpu"
GPU_TEMP_LABEL = "edge"


def _find_amdgpu_device_dir(sys_root: str = "/sys") -> str | None:
    drm_root = os.path.join(sys_root, "class", "drm")
    try:
        entries = sorted(os.listdir(drm_root))
    except OSError:
        return None
    for entry in entries:
        if not entry.startswith("card") or "-" in entry:
            continue  # skip cardN-<connector> entries, only want cardN itself
        device_dir = os.path.join(drm_root, entry, "device")
        try:
            driver_name = os.path.basename(os.readlink(os.path.join(device_dir, "driver")))
        except OSError:
            continue
        if driver_name == "amdgpu":
            return device_dir
    return None


def read_load_pct(sys_root: str = "/sys") -> float | None:
    device_dir = _find_amdgpu_device_dir(sys_root)
    if device_dir is None:
        return None
    return sysfs_util.read_value(os.path.join(device_dir, "gpu_busy_percent"))


def read_temp_c(sys_root: str = "/sys") -> float | None:
    hwmon_dir = sysfs_util.find_hwmon_by_name(GPU_HWMON_NAME, sys_root)
    value = sysfs_util.find_temp_input_by_label(hwmon_dir, GPU_TEMP_LABEL)
    return value / 1000.0 if value is not None else None


def has_dedicated_gpu(sys_root: str = "/sys") -> bool:
    return sysfs_util.find_hwmon_by_name(GPU_HWMON_NAME, sys_root) is not None
