import os

from uc_steamos_agent.commands import user_session


def test_resolve_uid_for_current_user():
    import pwd

    me = pwd.getpwuid(os.getuid())
    assert user_session.resolve_uid(me.pw_name) == os.getuid()


def test_session_env_sets_xdg_runtime_dir_without_mutating_base():
    base = {"PATH": "/usr/bin", "XDG_RUNTIME_DIR": "/run/user/0"}
    env = user_session.session_env(1000, base_env=base)
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["PATH"] == "/usr/bin"
    assert base["XDG_RUNTIME_DIR"] == "/run/user/0"  # base dict untouched


def test_session_env_defaults_to_current_environ(monkeypatch):
    monkeypatch.setenv("SOME_TEST_VAR", "hello")
    env = user_session.session_env(1000)
    assert env["SOME_TEST_VAR"] == "hello"
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
