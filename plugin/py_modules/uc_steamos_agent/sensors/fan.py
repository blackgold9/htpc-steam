"""Fan sensors: enumerate every hwmon fan*_input system-wide rather than
hardcoding a driver name — uncertain across Deck LCD/OLED revisions and
generic SteamOS boxes.

Confirmed on real hardware: the Bazzite desktop test box has NO fan hwmon
at all. An empty list is the normal, expected result on such systems, not
an error — callers must not treat it as a failure.
"""

import os

from . import sysfs_util


def read_fan_speeds(sys_root: str = "/sys") -> list[dict]:
    fans = []
    for hwmon_dir in sysfs_util.list_hwmon_dirs(sys_root):
        name = sysfs_util.read_hwmon_name(hwmon_dir)
        try:
            entries = sorted(os.listdir(hwmon_dir))
        except OSError:
            continue
        for entry in entries:
            if not (entry.startswith("fan") and entry.endswith("_input")):
                continue
            value = sysfs_util.read_value(os.path.join(hwmon_dir, entry))
            if value is None or value <= 0:
                continue
            label = f"{name} {entry[:-len('_input')]}" if name else entry
            fans.append({"label": label, "rpm": int(value)})
    return fans
