from uc_steamos_agent.commands import launch


class _FakeProc:
    def __init__(self, pid):
        self.pid = pid


def _fake_popen(calls, pid=4242):
    def popen(argv, **kw):
        calls.append((argv, kw))
        return _FakeProc(pid)

    return popen


def test_launch_exe_uses_shlex_split(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", _fake_popen(calls))
    pid = launch.launch_exe("/usr/bin/konsole --arg value")
    assert calls[0][0] == ["/usr/bin/konsole", "--arg", "value"]
    assert calls[0][1]["start_new_session"] is True
    assert pid == 4242


def test_launch_url_steam_uri_uses_steam_binary(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", _fake_popen(calls))
    launch.launch_url("steam://open/settings")
    assert calls[0][0] == ["steam", "steam://open/settings"]


def test_launch_url_web_uses_xdg_open(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", _fake_popen(calls))
    launch.launch_url("https://youtube.com")
    assert calls[0][0] == ["xdg-open", "https://youtube.com"]


def test_launch_passes_through_env(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.subprocess, "Popen", _fake_popen(calls))
    launch.launch_exe("/bin/true", env={"XDG_RUNTIME_DIR": "/run/user/1000"})
    assert calls[0][1]["env"] == {"XDG_RUNTIME_DIR": "/run/user/1000"}


def test_close_process_group_sends_sigterm(monkeypatch):
    calls = []
    monkeypatch.setattr(launch.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    result = launch.close_process_group(4242)
    assert result is True
    assert calls == [(4242, launch.signal.SIGTERM)]


def test_close_process_group_missing_pid_returns_false(monkeypatch):
    def raise_lookup(pid, sig):
        raise ProcessLookupError()

    monkeypatch.setattr(launch.os, "killpg", raise_lookup)
    assert launch.close_process_group(999999) is False
