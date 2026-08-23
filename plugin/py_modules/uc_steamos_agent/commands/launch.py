"""Steam URI launching, used by the fixed Gamescope-native shortcuts
(steam_settings, steam_library) and their close_last_launch recovery valve.

General-purpose launch_exe/launch_url/shortcut support (arbitrary
executable/URL launching) was removed after live testing found a real,
unresolved recovery gap: opening a web URL via xdg-open took over
Gamescope's UI full-screen with no way back through any agent command,
including close_last_launch's process-group kill (the launched browser
wasn't even a child of our process -- likely a pre-existing/D-Bus-activated
instance). See docs/command-mapping.md's Web URLs row for the full finding.

steam:// URIs are kept because they were confirmed to open and recover
cleanly (steam_settings via `escape`, twice, due to nested menu depth).
"""

import os
import signal
import subprocess


def launch_steam_uri(uri: str, env: dict | None = None) -> int:
    """Launches `uri` via the Steam client and returns the pid (also its
    process-group id, since start_new_session=True makes it a new
    session/group leader)."""
    proc = subprocess.Popen(["steam", uri], start_new_session=True, env=env)
    return proc.pid


def close_process_group(pid: int) -> bool:
    """Best-effort: SIGTERM the process group led by `pid`."""
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except ProcessLookupError:
        return False
