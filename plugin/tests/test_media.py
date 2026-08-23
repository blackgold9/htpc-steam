from uc_steamos_agent.commands import media


def test_simple_commands_target_default_sink():
    assert media.SIMPLE_COMMANDS["volume_up"] == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"]
    assert media.SIMPLE_COMMANDS["volume_down"] == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]
    assert media.SIMPLE_COMMANDS["mute"] == ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]
    assert media.SIMPLE_COMMANDS["mute_toggle"] == media.SIMPLE_COMMANDS["mute"]


def test_set_volume_argv_builds_percent():
    assert media.set_volume_argv(75) == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "75%"]


def test_execute_runs_the_given_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    media.execute(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"])
    assert calls[0][0] == ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "50%"]
    assert calls[0][1]["check"] is True
    assert calls[0][1]["env"] is None


def test_execute_passes_through_env(monkeypatch):
    calls = []
    monkeypatch.setattr(media.subprocess, "run", lambda argv, **kw: calls.append(kw))
    media.execute(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], env={"XDG_RUNTIME_DIR": "/run/user/1000"})
    assert calls[0]["env"] == {"XDG_RUNTIME_DIR": "/run/user/1000"}
