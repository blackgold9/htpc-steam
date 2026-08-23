"""Battery: /sys/class/power_supply/BAT*.

New capability upstream (the Windows agent) never had — desktop HTPCs have
no battery. Confirmed on real hardware: the Bazzite desktop test box has
none; its only power_supply entry is a wireless mouse's hidpp_battery_0,
which the BAT* glob correctly excludes without any extra filtering.
"""

import glob
import os

EMPTY = {"present": False, "percent": None, "charging": None, "power_w": None}


def read_battery(sys_root: str = "/sys") -> dict:
    matches = sorted(glob.glob(os.path.join(sys_root, "class", "power_supply", "BAT*")))
    if not matches:
        return dict(EMPTY)

    bat_dir = matches[0]
    percent = _read_float(os.path.join(bat_dir, "capacity"))
    status = _read_text(os.path.join(bat_dir, "status"))
    charging = status.lower() == "charging" if status else None
    power_uw = _read_float(os.path.join(bat_dir, "power_now"))
    power_w = power_uw / 1_000_000 if power_uw is not None else None

    return {"present": True, "percent": percent, "charging": charging, "power_w": power_w}


def _read_float(path: str) -> float | None:
    try:
        with open(path) as f:
            return float(f.read().strip())
    except (OSError, ValueError):
        return None


def _read_text(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None
