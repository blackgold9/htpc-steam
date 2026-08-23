import os

from uc_steamos_agent.games.library import list_recent_games, steam_root_for_home


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _localconfig(steam_root, user="7189784", apps_block=""):
    path = os.path.join(steam_root, "userdata", user, "config", "localconfig.vdf")
    text = (
        '"UserLocalConfigStore"\n{\n'
        '\t"Software"\n\t{\n'
        '\t\t"Valve"\n\t\t{\n'
        '\t\t\t"Steam"\n\t\t\t{\n'
        '\t\t\t\t"apps"\n\t\t\t\t{\n'
        f"{apps_block}"
        '\t\t\t\t}\n'
        '\t\t\t}\n'
        '\t\t}\n'
        '\t}\n'
        '}\n'
    )
    _write(path, text)


def _app_entry(appid, last_played):
    return f'\t\t\t\t\t"{appid}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LastPlayed"\t\t"{last_played}"\n\t\t\t\t\t}}\n'


def _appmanifest(steam_root, appid, name, last_played="0"):
    path = os.path.join(steam_root, "steamapps", f"appmanifest_{appid}.acf")
    text = (
        '"AppState"\n{\n'
        f'\t"appid"\t\t"{appid}"\n'
        f'\t"name"\t\t"{name}"\n'
        f'\t"LastPlayed"\t\t"{last_played}"\n'
        '}\n'
    )
    _write(path, text)


def test_list_recent_games_orders_most_recent_first(tmp_path):
    root = str(tmp_path)
    apps = _app_entry("100", "1787507429") + _app_entry("200", "1786754345")
    _localconfig(root, apps_block=apps)
    _appmanifest(root, "100", "Bopl Battle")
    _appmanifest(root, "200", "Dokapon Kingdom: Connect")

    games = list_recent_games(steam_root=root)
    assert [g["name"] for g in games] == ["Bopl Battle", "Dokapon Kingdom: Connect"]
    assert games[0] == {"appid": 100, "name": "Bopl Battle", "last_played": 1787507429}


def test_never_played_sentinel_is_excluded(tmp_path):
    root = str(tmp_path)
    apps = _app_entry("100", "86400") + _app_entry("200", "86401")
    _localconfig(root, apps_block=apps)
    _appmanifest(root, "100", "Never Played")
    _appmanifest(root, "200", "Played Once")

    games = list_recent_games(steam_root=root)
    assert [g["name"] for g in games] == ["Played Once"]


def test_played_but_no_longer_installed_is_excluded(tmp_path):
    root = str(tmp_path)
    apps = _app_entry("100", "1787507429") + _app_entry("999", "1786754345")
    _localconfig(root, apps_block=apps)
    _appmanifest(root, "100", "Still Installed")
    # no appmanifest for 999 -- uninstalled

    games = list_recent_games(steam_root=root)
    assert [g["name"] for g in games] == ["Still Installed"]


def test_compat_tools_are_filtered_out(tmp_path):
    root = str(tmp_path)
    apps = (
        _app_entry("100", "1787507429")
        + _app_entry("200", "1781559441")
        + _app_entry("300", "1781559441")
        + _app_entry("400", "1781550742")
    )
    _localconfig(root, apps_block=apps)
    _appmanifest(root, "100", "Bopl Battle")
    _appmanifest(root, "200", "Proton 11.0")
    _appmanifest(root, "300", "Steam Linux Runtime 4.0")
    _appmanifest(root, "400", "Steamworks Common Redistributables")

    games = list_recent_games(steam_root=root)
    assert [g["name"] for g in games] == ["Bopl Battle"]


def test_max_games_truncates(tmp_path):
    root = str(tmp_path)
    apps = "".join(_app_entry(str(i), str(100000 + i)) for i in range(5))
    _localconfig(root, apps_block=apps)
    for i in range(5):
        _appmanifest(root, str(i), f"Game {i}")

    games = list_recent_games(steam_root=root, max_games=2)
    assert len(games) == 2


def test_multiple_users_takes_max_last_played(tmp_path):
    root = str(tmp_path)
    _localconfig(root, user="111", apps_block=_app_entry("100", "1700000000"))
    _localconfig(root, user="222", apps_block=_app_entry("100", "1787507429"))
    _appmanifest(root, "100", "Shared Game")

    games = list_recent_games(steam_root=root)
    assert games == [{"appid": 100, "name": "Shared Game", "last_played": 1787507429}]


def test_appmanifest_own_last_played_field_is_ignored(tmp_path):
    """appmanifest's own LastPlayed is stale/unreliable -- localconfig.vdf
    is the only source of truth used here (see docs/hardware-notes.md)."""
    root = str(tmp_path)
    _localconfig(root, apps_block=_app_entry("100", "1787507429"))
    _appmanifest(root, "100", "Bopl Battle", last_played="0")

    games = list_recent_games(steam_root=root)
    assert games == [{"appid": 100, "name": "Bopl Battle", "last_played": 1787507429}]


def test_no_steam_data_returns_empty_list(tmp_path):
    assert list_recent_games(steam_root=str(tmp_path)) == []


def test_steam_root_for_home_joins_expected_path():
    assert steam_root_for_home("/var/home/stephen") == "/var/home/stephen/.local/share/Steam"
