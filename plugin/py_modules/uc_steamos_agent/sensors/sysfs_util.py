"""Shared sysfs/hwmon helpers, with an injectable root path for testing.

Real hwmon layout (ground truth from docs/hardware-notes.md, gathered via
scripts/hwmon-dump.sh on the Bazzite test box) uses fuzzy name/label
matching rather than fixed indices, since hwmon numbering isn't stable
across boots or hardware.
"""

import os


def list_hwmon_dirs(sys_root: str = "/sys") -> list[str]:
    hwmon_root = os.path.join(sys_root, "class", "hwmon")
    try:
        entries = sorted(os.listdir(hwmon_root))
    except OSError:
        return []
    return [os.path.join(hwmon_root, e) for e in entries]


def read_hwmon_name(hwmon_dir: str) -> str | None:
    try:
        with open(os.path.join(hwmon_dir, "name")) as f:
            return f.read().strip()
    except OSError:
        return None


def find_hwmon_by_name(name: str, sys_root: str = "/sys") -> str | None:
    """Return the hwmon directory path whose `name` file matches exactly, or None."""
    for hwmon_dir in list_hwmon_dirs(sys_root):
        if read_hwmon_name(hwmon_dir) == name:
            return hwmon_dir
    return None


def read_value(path: str) -> float | None:
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def find_temp_input_by_label(hwmon_dir: str | None, label: str) -> float | None:
    """Find a temp*_input whose matching temp*_label equals `label` (case-insensitive)."""
    if hwmon_dir is None:
        return None
    try:
        entries = sorted(os.listdir(hwmon_dir))
    except OSError:
        return None
    for entry in entries:
        if not entry.endswith("_label"):
            continue
        try:
            with open(os.path.join(hwmon_dir, entry)) as f:
                entry_label = f.read().strip()
        except OSError:
            continue
        if entry_label.lower() == label.lower():
            input_entry = entry[: -len("_label")] + "_input"
            return read_value(os.path.join(hwmon_dir, input_entry))
    return None
