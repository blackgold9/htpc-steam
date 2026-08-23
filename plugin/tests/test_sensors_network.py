from uc_steamos_agent.sensors.network import NetworkThroughputSampler, default_interface


def _write_route(proc_root, iface):
    (proc_root / "net").mkdir(parents=True, exist_ok=True)
    (proc_root / "net" / "route").write_text(f"Iface\tDestination\tGateway\n{iface}\t00000000\t0101A8C0\n")


def _write_stats(sys_root, iface, rx, tx):
    stats_dir = sys_root / "class" / "net" / iface / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    (stats_dir / "rx_bytes").write_text(str(rx))
    (stats_dir / "tx_bytes").write_text(str(tx))


def test_default_interface_parses_route_table(tmp_path):
    # Ground truth from docs/hardware-notes.md: enp151s0 is the default route.
    proc_root = tmp_path / "proc"
    _write_route(proc_root, "enp151s0")
    assert default_interface(str(proc_root)) == "enp151s0"


def test_default_interface_none_when_no_default_route(tmp_path):
    proc_root = tmp_path / "proc"
    (proc_root / "net").mkdir(parents=True)
    (proc_root / "net" / "route").write_text("Iface\tDestination\n")
    assert default_interface(str(proc_root)) is None


def test_sampler_first_call_returns_none_second_computes_rate(tmp_path):
    sys_root = tmp_path / "sys"
    proc_root = tmp_path / "proc"
    _write_route(proc_root, "eth0")
    _write_stats(sys_root, "eth0", rx=1000, tx=500)

    clock_values = iter([0.0, 1.0])
    sampler = NetworkThroughputSampler(str(sys_root), str(proc_root), clock=lambda: next(clock_values))

    assert sampler.sample() == {"up_kbps": None, "down_kbps": None}

    _write_stats(sys_root, "eth0", rx=1000 + 12500, tx=500 + 6250)  # +100kbit down, +50kbit up over 1s
    second = sampler.sample()
    assert second["down_kbps"] == 100.0
    assert second["up_kbps"] == 50.0


def test_sampler_resets_when_interface_disappears(tmp_path):
    sys_root = tmp_path / "sys"
    proc_root = tmp_path / "proc"
    _write_route(proc_root, "eth0")
    _write_stats(sys_root, "eth0", rx=0, tx=0)
    sampler = NetworkThroughputSampler(str(sys_root), str(proc_root))
    sampler.sample()

    (proc_root / "net" / "route").write_text("Iface\tDestination\n")  # no default route now
    assert sampler.sample() == {"up_kbps": None, "down_kbps": None}
