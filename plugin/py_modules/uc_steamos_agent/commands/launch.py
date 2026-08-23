"""Application/URL launching: steam:// URIs, xdg-open, and direct exec.

Confirmed live on the test box (docs/command-mapping.md): `launch_url` for a
web URL opens the browser full-screen, replacing Gamescope's UI entirely,
with no built-in way back through the agent's other commands. `close_process_group`
exists specifically to let a caller (Dispatcher's `close_last_launch` command)
recover from that remotely instead of requiring physical access to the box.
"""

import os
import shlex
import signal
import subprocess


def launch_exe(path: str, env: dict | None = None) -> int:
    """Launches `path` and returns its pid (also its process-group id, since
    start_new_session=True makes it a new session/group leader)."""
    proc = subprocess.Popen(shlex.split(path), start_new_session=True, env=env)
    return proc.pid


def launch_url(url: str, env: dict | None = None) -> int:
    if url.startswith("steam://"):
        proc = subprocess.Popen(["steam", url], start_new_session=True, env=env)
    else:
        proc = subprocess.Popen(["xdg-open", url], start_new_session=True, env=env)
    return proc.pid


def close_process_group(pid: int) -> bool:
    """Best-effort: SIGTERM the process group led by `pid`. Valid only for a
    pid returned by launch_exe/launch_url, since start_new_session=True is
    what makes pgid == pid. Anything the launched process execs or forks
    (e.g. the actual browser xdg-open hands off to) normally stays in that
    same group, so this can close more than just the immediate child --
    but it's still best-effort: an app that detaches into its own session
    won't be reachable this way.
    """
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
