from uc_steamos_agent.commands import game_control


def _write_environ(proc_root, pid, env_vars):
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    raw = b"\0".join(f"{k}={v}".encode() for k, v in env_vars.items()) + b"\0"
    (pid_dir / "environ").write_bytes(raw)


def test_find_running_game_pid_matches_steam_app_id(tmp_path):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 1234, {"PATH": "/usr/bin", "SteamAppId": "1889580"})
    assert game_control.find_running_game_pid(str(proc_root)) == 1234


def test_find_running_game_pid_none_when_no_game_running(tmp_path):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 999, {"PATH": "/usr/bin"})
    assert game_control.find_running_game_pid(str(proc_root)) is None


def test_find_running_game_pid_missing_proc_root_returns_none(tmp_path):
    assert game_control.find_running_game_pid(str(tmp_path / "missing")) is None


def test_find_running_game_pid_picks_lowest_pid_deterministically(tmp_path):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 5000, {"SteamAppId": "1889580"})
    _write_environ(proc_root, 2000, {"SteamAppId": "1889580"})
    assert game_control.find_running_game_pid(str(proc_root)) == 2000


def test_force_quit_game_kills_process_group(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 4242, {"SteamAppId": "1889580"})

    calls = []
    monkeypatch.setattr(game_control.os, "getpgid", lambda pid: 4200)
    monkeypatch.setattr(game_control.os, "killpg", lambda pgid, sig: calls.append((pgid, sig)))

    assert game_control.force_quit_game(str(proc_root)) is True
    assert calls == [(4200, game_control.signal.SIGTERM)]


def test_force_quit_game_no_game_running_returns_false(tmp_path):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 1, {"PATH": "/usr/bin"})
    assert game_control.force_quit_game(str(proc_root)) is False


def test_force_quit_game_handles_process_already_gone(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, 4242, {"SteamAppId": "1889580"})

    def raise_lookup(pid):
        raise ProcessLookupError()

    monkeypatch.setattr(game_control.os, "getpgid", raise_lookup)
    assert game_control.force_quit_game(str(proc_root)) is False
