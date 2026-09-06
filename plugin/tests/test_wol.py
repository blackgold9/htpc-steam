"""ethtool/Wake-on parsing and the arming path.

`parse_ethtool` runs against verbatim `ethtool` output: the real risk in this
module is a regex that silently matches nothing and reports every NIC as
unsupported, which a test feeding it a synthetic dict would never catch. The
`reported` flag and its tests came directly from the live box, where an
unprivileged `ethtool` exits 0 and prints a complete link dump containing
neither Wake-on line.
"""

import subprocess

from uc_steamos_agent.commands import wol

ARMED = """Settings for enp9s0:
\tSupported ports: [ TP	 MII ]
\tSupported link modes:   10baseT/Half 10baseT/Full
\tSpeed: 1000Mb/s
\tDuplex: Full
\tLink detected: yes
\tSupports Wake-on: pumbg
\tWake-on: g
"""

DISARMED = ARMED.replace("\tWake-on: g", "\tWake-on: d")
UNSUPPORTED = ARMED.replace("\tSupports Wake-on: pumbg", "\tSupports Wake-on:").replace("\tWake-on: g", "")
# Verbatim shape of an unprivileged run on the live box: valid output, exit 0,
# and nothing at all about wake.
NO_WAKE_INFO = "Settings for enp9s0:\n\tSpeed: 1000Mb/s\n\tLink detected: yes\n"


def _completed(stdout="", returncode=0):
    return lambda *args, **kwargs: subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")


def test_parse_reports_armed_nic():
    parsed = wol.parse_ethtool(ARMED)
    assert parsed["reported"] is True
    assert parsed["supported"] is True
    assert parsed["enabled"] is True


def test_parse_reports_a_nic_that_can_do_wol_but_isnt_armed():
    """The state that must produce a warning rather than a dead Power On button."""
    parsed = wol.parse_ethtool(DISARMED)
    assert parsed["reported"] is True
    assert parsed["supported"] is True
    assert parsed["enabled"] is False


def test_parse_reports_a_nic_without_wol_support():
    """`Supports Wake-on:` printed without a g is a real answer: unsupported."""
    parsed = wol.parse_ethtool(UNSUPPORTED)
    assert parsed["reported"] is True
    assert parsed["supported"] is False
    assert parsed["enabled"] is False


def test_parse_flags_output_that_says_nothing_about_wake():
    parsed = wol.parse_ethtool(NO_WAKE_INFO)
    assert parsed["reported"] is False
    assert parsed["supported"] is False
    assert parsed["enabled"] is False


def test_empty_supports_value_does_not_capture_the_next_line():
    """ethtool prints `Supports Wake-on:` with nothing after it on a NIC that
    can't do WoL, immediately above `Wake-on:`. A `\\s*` before the value would
    swallow that newline and read the following key as the flags."""
    parsed = wol.parse_ethtool("Settings for enp9s0:\n\tSupports Wake-on:\n\tWake-on: d\n")
    assert parsed["supported_flags"] == ""
    assert parsed["wake_on"] == ""
    assert parsed["reported"] is True
    assert parsed["supported"] is False


def test_parse_of_unrelated_output_is_all_false_not_a_crash():
    parsed = wol.parse_ethtool("netlink error: Operation not permitted\n")
    assert parsed["reported"] is False
    assert parsed["supported"] is False
    assert parsed["enabled"] is False


def test_wakeup_source_reads_sysfs(tmp_path):
    power = tmp_path / "class" / "net" / "enp9s0" / "device" / "power"
    power.mkdir(parents=True)
    (power / "wakeup").write_text("enabled\n")
    assert wol.wakeup_enabled("enp9s0", sys_root=str(tmp_path)) is True

    (power / "wakeup").write_text("disabled\n")
    assert wol.wakeup_enabled("enp9s0", sys_root=str(tmp_path)) is False


def test_missing_wakeup_file_is_false(tmp_path):
    """Absent means the kernel doesn't list the device as a wakeup source — the
    same practical answer as "disabled"."""
    assert wol.wakeup_enabled("enp9s0", sys_root=str(tmp_path)) is False


def _fake_sysfs(tmp_path, iface="enp9s0", driver="r8169", wakeup="enabled"):
    device = tmp_path / "class" / "net" / iface / "device"
    (device / "power").mkdir(parents=True)
    (tmp_path / "drivers" / driver).mkdir(parents=True)
    (device / "driver").symlink_to(tmp_path / "drivers" / driver)
    (device / "power" / "wakeup").write_text(wakeup)
    return str(tmp_path)


def test_read_status_merges_ethtool_driver_and_wakeup(monkeypatch, tmp_path):
    sys_root = _fake_sysfs(tmp_path)
    monkeypatch.setattr(wol.subprocess, "run", _completed(stdout=ARMED))

    status = wol.read_status("enp9s0", sys_root=sys_root)

    assert status == {
        "reported": True,
        "supported": True,
        "enabled": True,
        "supported_flags": "pumbg",
        "wake_on": "g",
        "interface": "enp9s0",
        "driver": "r8169",
        "may_wakeup": True,
    }


def test_read_status_is_none_when_ethtool_says_nothing_about_wake(monkeypatch, tmp_path):
    """The live-box case. Must be unknown — not the misleading claim that the
    NIC can't do Wake-on-LAN."""
    sys_root = _fake_sysfs(tmp_path)
    monkeypatch.setattr(wol.subprocess, "run", _completed(stdout=NO_WAKE_INFO))
    assert wol.read_status("enp9s0", sys_root=sys_root) is None


def test_read_status_reports_an_unsupported_nic_as_supported_false(monkeypatch, tmp_path):
    """Distinct from unknown: here ethtool did answer, and the answer is no."""
    sys_root = _fake_sysfs(tmp_path)
    monkeypatch.setattr(wol.subprocess, "run", _completed(stdout=UNSUPPORTED))

    status = wol.read_status("enp9s0", sys_root=sys_root)

    assert status["supported"] is False
    assert status["enabled"] is False


def test_read_status_is_none_when_ethtool_fails(monkeypatch):
    monkeypatch.setattr(wol.subprocess, "run", _completed(returncode=1))
    assert wol.read_status("enp9s0") is None


def test_read_status_is_none_when_ethtool_is_missing(monkeypatch):
    def raise_oserror(*args, **kwargs):
        raise FileNotFoundError("ethtool")

    monkeypatch.setattr(wol.subprocess, "run", raise_oserror)
    assert wol.read_status("enp9s0") is None


def test_read_status_is_none_with_no_routing_interface(monkeypatch):
    monkeypatch.setattr(wol, "default_interface", lambda: None)
    assert wol.read_status() is None


def test_monitor_caches_until_the_ttl_expires(monkeypatch):
    calls = []
    now = {"t": 1000.0}

    def fake(iface=None, sys_root="/sys"):
        calls.append(now["t"])
        return {"interface": "enp9s0", "enabled": True}

    monkeypatch.setattr(wol, "read_status", fake)
    monitor = wol.WakeOnLanMonitor(cache_s=30.0, clock=lambda: now["t"])

    monitor.status()
    monitor.status()
    assert len(calls) == 1

    now["t"] += 31
    assert monitor.status()["enabled"] is True
    assert len(calls) == 2


def test_monitor_caches_a_failure_too(monkeypatch):
    """Otherwise a box where ethtool can't answer (the live one, unprivileged)
    spawns a doomed subprocess on every 2s sensor tick, forever."""
    calls = []

    def fake(iface=None, sys_root="/sys"):
        calls.append(1)
        return None

    monkeypatch.setattr(wol, "read_status", fake)
    monitor = wol.WakeOnLanMonitor()

    assert monitor.status() is None
    assert monitor.status() is None
    assert len(calls) == 1


def test_arm_returns_false_when_the_flag_does_not_take(monkeypatch):
    """ethtool can exit 0 while the driver ignores the flag, so arming is
    confirmed by re-reading. Trusting the exit status would report success and
    then the wake silently wouldn't happen."""
    monkeypatch.setattr(wol, "default_interface", lambda: "enp9s0")
    monkeypatch.setattr(wol.subprocess, "run", _completed())
    monitor = wol.WakeOnLanMonitor()
    monkeypatch.setattr(monitor, "status", lambda force=False: {"interface": "enp9s0", "enabled": False})

    assert monitor.arm() is False


def test_arm_succeeds_when_a_reread_confirms_it(monkeypatch):
    run_calls = []

    def fake_run(*args, **kwargs):
        run_calls.append(args[0])
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(wol, "default_interface", lambda: "enp9s0")
    monkeypatch.setattr(wol.subprocess, "run", fake_run)
    monitor = wol.WakeOnLanMonitor()
    monkeypatch.setattr(
        monitor, "status", lambda force=False: {"interface": "enp9s0", "enabled": True, "driver": "r8169"}
    )

    assert monitor.arm() is True
    assert run_calls == [["ethtool", "-s", "enp9s0", "wol", "g"]]


def test_arm_reports_failure_with_no_routing_interface(monkeypatch):
    monkeypatch.setattr(wol, "default_interface", lambda: None)
    assert wol.WakeOnLanMonitor(arm=True).arm() is False


def test_start_does_not_arm_unless_asked(monkeypatch):
    """Default posture: a monitoring plugin must not flip NIC power settings."""
    monkeypatch.setattr(wol, "read_status", lambda iface=None, sys_root="/sys": None)
    monitor = wol.WakeOnLanMonitor(arm=False)
    armed = []
    monkeypatch.setattr(monitor, "arm", lambda: armed.append(True) or True)

    monitor.start()

    assert armed == []


def test_start_arms_and_primes_the_cache_when_enabled(monkeypatch):
    monkeypatch.setattr(wol, "read_status", lambda iface=None, sys_root="/sys": {"interface": "enp9s0"})
    monitor = wol.WakeOnLanMonitor(arm=True)
    armed = []
    monkeypatch.setattr(monitor, "arm", lambda: armed.append(True) or True)

    monitor.start()

    assert armed == [True]
    assert monitor.status() == {"interface": "enp9s0"}
