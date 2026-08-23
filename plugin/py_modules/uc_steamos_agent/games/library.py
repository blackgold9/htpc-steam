"""Recently-played, currently-installed games -- for the Game Launcher entity.

localconfig.vdf is the authoritative LastPlayed source. appmanifest_*.acf's
own LastPlayed field is stale/unreliable (confirmed live: it read 0 for
every installed game except the one just played in a real test session) --
see docs/hardware-notes.md. appmanifest files are only used here for the
display name, and to confirm a previously-played app is still installed
(localconfig.vdf's apps section includes games no longer on disk).

"Favorites" (a stretch goal considered alongside this) turned out not to be
practically extractable from local VDF data -- see docs/hardware-notes.md.
"""

import glob
import os

from .vdf import parse as parse_vdf

LAST_PLAYED_NEVER = 86400  # Steam's sentinel for "never really played", not a real 1970 timestamp
DEFAULT_STEAM_ROOT = os.path.expanduser("~/.local/share/Steam")


def steam_root_for_home(home_dir: str) -> str:
    """The plugin runs as root, so `~` above resolves to /root, not the
    desktop user's home -- callers with a real uid (see user_session.py)
    should build the root from that user's home dir instead."""
    return os.path.join(home_dir, ".local", "share", "Steam")

# Compat tools (Proton, Steam Linux Runtime, redistributables) get a
# LastPlayed entry in localconfig.vdf too -- Steam logs when they're
# invoked to run some other game, not just when a real game is launched.
# Confirmed live: Proton 10.0/11.0 and Steam Linux Runtime 4.0 all showed
# up as "recently played" on a real box. There's no local, offline field
# marking an app as a tool vs. a game (that's only in Valve's appinfo.vdf
# cache or the store API), so this is a name-based denylist of Valve's
# own, stable tool naming -- see docs/hardware-notes.md.
_NON_GAME_NAME_PREFIXES = (
    "Proton ",
    "Steam Linux Runtime",
    "Steamworks Common Redistributables",
    "SteamVR",
)


def _is_probably_a_game(name: str) -> bool:
    return not any(name.startswith(prefix) for prefix in _NON_GAME_NAME_PREFIXES)


def _find_localconfig_paths(steam_root: str) -> list[str]:
    pattern = os.path.join(steam_root, "userdata", "*", "config", "localconfig.vdf")
    return sorted(glob.glob(pattern))


def _read_last_played(steam_root: str) -> dict[str, int]:
    """appid (str) -> most recent LastPlayed epoch across all local users."""
    result: dict[str, int] = {}
    for path in _find_localconfig_paths(steam_root):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                data = parse_vdf(f.read())
        except OSError:
            continue

        apps = (
            data.get("UserLocalConfigStore", {})
            .get("Software", {})
            .get("Valve", {})
            .get("Steam", {})
            .get("apps", {})
        )
        if not isinstance(apps, dict):
            continue
        for appid, entry in apps.items():
            if not isinstance(entry, dict):
                continue
            raw = entry.get("LastPlayed")
            if raw is None:
                continue
            try:
                last_played = int(raw)
            except ValueError:
                continue
            if last_played <= LAST_PLAYED_NEVER:
                continue
            if last_played > result.get(appid, 0):
                result[appid] = last_played
    return result


def _read_installed_names(steam_root: str) -> dict[str, str]:
    """appid (str) -> display name, for every currently-installed app."""
    pattern = os.path.join(steam_root, "steamapps", "appmanifest_*.acf")
    result: dict[str, str] = {}
    for path in glob.glob(pattern):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                data = parse_vdf(f.read())
        except OSError:
            continue
        state = data.get("AppState", {})
        appid = state.get("appid")
        name = state.get("name")
        if appid and name:
            result[appid] = name
    return result


def list_recent_games(steam_root: str = DEFAULT_STEAM_ROOT, max_games: int = 10) -> list[dict]:
    """Recently-played games that are still installed, most recent first."""
    last_played = _read_last_played(steam_root)
    names = _read_installed_names(steam_root)

    games = []
    for appid, played_at in last_played.items():
        name = names.get(appid)
        if name is None:
            continue  # played before, but not currently installed
        if not _is_probably_a_game(name):
            continue
        games.append({"appid": int(appid), "name": name, "last_played": played_at})

    games.sort(key=lambda g: g["last_played"], reverse=True)
    return games[:max_games]
