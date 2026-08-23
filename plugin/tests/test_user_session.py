import os
import pwd

from uc_steamos_agent.commands import user_session


def test_resolve_uid_for_current_user():
    me = pwd.getpwuid(os.getuid())
    assert user_session.resolve_uid(me.pw_name) == os.getuid()


def test_session_env_sets_xdg_runtime_dir_without_mutating_base(tmp_path):
    base = {"PATH": "/usr/bin", "XDG_RUNTIME_DIR": "/run/user/0"}
    env = user_session.session_env(1000, base_env=base, proc_root=str(tmp_path / "no-such-proc"))
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["PATH"] == "/usr/bin"
    assert base["XDG_RUNTIME_DIR"] == "/run/user/0"  # base dict untouched


def test_session_env_defaults_to_current_environ(monkeypatch, tmp_path):
    monkeypatch.setenv("SOME_TEST_VAR", "hello")
    env = user_session.session_env(1000, proc_root=str(tmp_path / "no-such-proc"))
    assert env["SOME_TEST_VAR"] == "hello"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"


def _write_environ(proc_root, pid, uid, env_vars, monkeypatch):
    """Fake a /proc/<pid>/environ file, faking its owning uid via a
    monkeypatched os.stat (real chown would need real privileges)."""
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True)
    environ_path = pid_dir / "environ"
    raw = b"\0".join(f"{k}={v}".encode() for k, v in env_vars.items()) + b"\0"
    environ_path.write_bytes(raw)

    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path) == str(environ_path):
            return os.stat_result(
                (result.st_mode, result.st_ino, result.st_dev, result.st_nlink, uid) + result[5:]
            )
        return result

    monkeypatch.setattr(os, "stat", fake_stat)


def test_find_session_process_env_finds_process_with_display(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(
        proc_root,
        pid=2384,
        uid=1000,
        env_vars={
            "DISPLAY": ":0",
            "XDG_CURRENT_DESKTOP": "gamescope",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "SOME_OTHER_VAR": "ignored",
        },
        monkeypatch=monkeypatch,
    )

    env = user_session.find_session_process_env(1000, proc_root=str(proc_root))
    assert env["DISPLAY"] == ":0"
    assert env["XDG_CURRENT_DESKTOP"] == "gamescope"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"


def test_find_session_process_env_skips_processes_without_display(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, pid=100, uid=1000, env_vars={"PATH": "/usr/bin"}, monkeypatch=monkeypatch)
    assert user_session.find_session_process_env(1000, proc_root=str(proc_root)) is None


def test_find_session_process_env_skips_other_users(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(proc_root, pid=200, uid=0, env_vars={"DISPLAY": ":0"}, monkeypatch=monkeypatch)
    assert user_session.find_session_process_env(1000, proc_root=str(proc_root)) is None


def test_find_session_process_env_missing_proc_root_returns_none(tmp_path):
    assert user_session.find_session_process_env(1000, proc_root=str(tmp_path / "missing")) is None


def test_session_env_picks_up_real_session_vars(tmp_path, monkeypatch):
    proc_root = tmp_path / "proc"
    _write_environ(
        proc_root,
        pid=2384,
        uid=1000,
        env_vars={
            "DISPLAY": ":0",
            "XDG_CURRENT_DESKTOP": "gamescope",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "XDG_DATA_DIRS": "/home/stephen/.local/share/flatpak/exports/share:/usr/share",
        },
        monkeypatch=monkeypatch,
    )

    env = user_session.session_env(1000, proc_root=str(proc_root))
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["DISPLAY"] == ":0"
    assert env["XDG_CURRENT_DESKTOP"] == "gamescope"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert "flatpak/exports" in env["XDG_DATA_DIRS"]
