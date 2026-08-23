from uc_steamos_agent.commands import power


def test_power_commands_map_to_systemctl_actions():
    assert power.POWER_COMMANDS["power_sleep"] == ["systemctl", "suspend"]
    assert power.POWER_COMMANDS["power_hibernate"] == ["systemctl", "hibernate"]
    assert power.POWER_COMMANDS["power_shutdown"] == ["systemctl", "poweroff"]
    assert power.POWER_COMMANDS["power_restart"] == ["systemctl", "reboot"]


def test_execute_runs_the_right_argv(monkeypatch):
    calls = []
    monkeypatch.setattr(power.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)))
    power.execute("power_shutdown")
    assert calls[0][0] == ["systemctl", "poweroff"]
    assert calls[0][1]["check"] is True
