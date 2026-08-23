from uc_steamos_agent.sensors import memory


def test_read_used_total_gb(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "meminfo").write_text(
        "MemTotal:       16384000 kB\nMemFree:         2000000 kB\nMemAvailable:    8192000 kB\n"
    )
    used_gb, total_gb = memory.read_used_total_gb(str(proc_root))
    assert total_gb == 16384000 / (1024 * 1024)
    assert used_gb == (16384000 - 8192000) / (1024 * 1024)


def test_missing_meminfo_returns_none(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    assert memory.read_used_total_gb(str(proc_root)) == (None, None)


def test_missing_mem_available_still_returns_total(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "meminfo").write_text("MemTotal:       16384000 kB\n")
    used_gb, total_gb = memory.read_used_total_gb(str(proc_root))
    assert used_gb is None
    assert total_gb == 16384000 / (1024 * 1024)
