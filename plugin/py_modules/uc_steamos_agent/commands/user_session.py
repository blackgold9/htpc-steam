"""Helpers for reaching the desktop user's session resources from a root process.

The plugin itself runs as root (Decky's `_root` flag), but commands like
`wpctl` need to reach resources that live under the desktop user's
per-session XDG_RUNTIME_DIR (e.g. the PipeWire socket). Confirmed on the
Bazzite test box: `wpctl` fails with "Could not connect to PipeWire"
without it, and succeeds with nothing else needed (no D-Bus session bus
address required) once XDG_RUNTIME_DIR is set. Likely needed again for
Phase 4's `steam://`/`xdg-open`/flatpak launches.
"""

import os
import pwd


def resolve_uid(username: str) -> int:
    return pwd.getpwnam(username).pw_uid


def session_env(uid: int, base_env: dict | None = None) -> dict:
    env = dict(base_env if base_env is not None else os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{uid}"
    return env
