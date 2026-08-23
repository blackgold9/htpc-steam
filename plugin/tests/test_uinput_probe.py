from uc_steamos_agent.commands.uinput_probe import uinput_writable


def test_uinput_writable_missing_path(tmp_path):
    missing = tmp_path / "no-such-uinput"
    assert uinput_writable(str(missing)) is False


def test_uinput_writable_present_and_writable(tmp_path):
    fake = tmp_path / "uinput"
    fake.write_text("")
    fake.chmod(0o666)
    assert uinput_writable(str(fake)) is True
