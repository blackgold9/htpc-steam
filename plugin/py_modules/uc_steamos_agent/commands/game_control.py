"""Force-quitting a running game.

Games are launched by the Steam client itself, not spawned directly by this
agent (unlike a browser launch via steam:// URIs), so there's no pid we
already know to track. Steam sets SteamAppId (and SteamGameId) in the
environment of every process it launches for a game -- the standard
mechanism Proton and the Steamworks SDK rely on to detect "running under
Steam". This scans /proc the same way user_session.py's session-process
discovery does, since this agent runs as root and can read any process's
environ regardless of owner.

Confirmed live (2026-08-23) against a real running game (Bopl Battle via
Proton): SteamAppId is genuinely set on every process in the tree, and
killing the first match's process group fully tore down the whole game --
including two other process groups it didn't directly own (reaper+bwrap;
the Proton/pressure-vessel wrapper chain; the game binary itself are three
separate groups). Almost certainly bubblewrap's sandbox teardown cascading
to everything inside it, not simple process-group semantics -- see
docs/command-mapping.md's exit-game row for the full finding.
"""

import os
import signal


def find_running_game_pid(proc_root: str = "/proc") -> int | None:
    """Find a process with SteamAppId set in its environment. Returns the
    first match's pid (sorted for determinism), or None if no game appears
    to be running."""
    try:
        entries = sorted(os.listdir(proc_root))
    except OSError:
        return None

    for entry in entries:
        if not entry.isdigit():
            continue
        environ_path = os.path.join(proc_root, entry, "environ")
        try:
            with open(environ_path, "rb") as f:
                raw = f.read()
        except OSError:
            continue

        if b"SteamAppId=" in raw:
            return int(entry)

    return None


def force_quit_game(proc_root: str = "/proc") -> bool:
    """Best-effort: find the running game's process and SIGTERM its process
    group. Returns False if no game process was found or the kill failed."""
    pid = find_running_game_pid(proc_root)
    if pid is None:
        return False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        return True
    except (ProcessLookupError, PermissionError):
        return False
