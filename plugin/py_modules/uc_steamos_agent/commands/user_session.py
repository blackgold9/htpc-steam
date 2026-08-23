"""Helpers for reaching the desktop user's session resources from a root process.

The plugin itself runs as root (Decky's `_root` flag), but commands like
`wpctl` and app launchers need to reach resources that live in the desktop
user's session -- PipeWire's socket, the D-Bus session bus, the X/Wayland
display, and (crucially for Flatpak apps like Firefox) XDG_DATA_DIRS.

Confirmed on the Bazzite test box:
- `wpctl` fails with "Could not connect to PipeWire" without XDG_RUNTIME_DIR
  set, and works with nothing else needed once it is.
- `xdg-open` is NOT satisfied by XDG_RUNTIME_DIR alone: with only that set,
  it fell through every graphical-open helper straight to text-mode
  browsers (all absent) and failed outright ("no method available"). It
  needs DISPLAY/DBUS_SESSION_BUS_ADDRESS/XDG_CURRENT_DESKTOP/XDG_DATA_DIRS
  too, to detect the desktop and find `gio`/similar helpers, and to locate
  Flatpak-exported apps at all.

Rather than hardcode those values (session type, bus path, and desktop name
could all vary across setups), `session_env` reads them live from an actual
running session process -- found by scanning /proc for a process owned by
the target uid with DISPLAY or WAYLAND_DISPLAY set. Root can read any
process's /proc/<pid>/environ, so this works without special permissions.
"""

import os
import pwd

_SESSION_ENV_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_CURRENT_DESKTOP",
    "XDG_SESSION_TYPE",
    "XDG_DATA_DIRS",
)


def resolve_uid(username: str) -> int:
    return pwd.getpwnam(username).pw_uid


def find_session_process_env(uid: int, proc_root: str = "/proc") -> dict[str, str] | None:
    """Find a process owned by uid with DISPLAY/WAYLAND_DISPLAY set (a real
    desktop session process, not just any background process owned by the
    user) and return its full environment, or None if none is found."""
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None

    for entry in entries:
        if not entry.isdigit():
            continue
        environ_path = os.path.join(proc_root, entry, "environ")
        try:
            if os.stat(environ_path).st_uid != uid:
                continue
            with open(environ_path, "rb") as f:
                raw = f.read()
        except OSError:
            continue

        env: dict[str, str] = {}
        for item in raw.split(b"\0"):
            if b"=" not in item:
                continue
            key, _, value = item.partition(b"=")
            try:
                env[key.decode()] = value.decode()
            except UnicodeDecodeError:
                continue

        if "DISPLAY" in env or "WAYLAND_DISPLAY" in env:
            return env

    return None


def session_env(uid: int, base_env: dict | None = None, proc_root: str = "/proc") -> dict:
    env = dict(base_env if base_env is not None else os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"

    session_vars = find_session_process_env(uid, proc_root)
    if session_vars:
        for key in _SESSION_ENV_KEYS:
            if key in session_vars:
                env[key] = session_vars[key]

    return env
