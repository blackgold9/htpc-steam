from uc_steamos_agent.sensors import storage


def test_read_usage_reports_percent(tmp_path):
    target = tmp_path / "home"
    target.mkdir()
    used_gb, total_gb, used_pct = storage.read_usage(str(target))
    assert total_gb is not None and total_gb > 0
    assert used_gb is not None
    assert 0 <= used_pct <= 100


def test_read_usage_missing_path_returns_none(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert storage.read_usage(str(missing)) == (None, None, None)


def test_read_temp_c_from_nvme_hwmon(tmp_path):
    # Ground truth from docs/hardware-notes.md: nvme temp1_input=36850, label Composite
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / "hwmon1"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text("nvme")
    (hwmon_dir / "temp1_label").write_text("Composite")
    (hwmon_dir / "temp1_input").write_text("36850")
    assert storage.read_temp_c(str(tmp_path / "sys")) == 36.85


def test_read_temp_c_none_when_no_nvme_hwmon(tmp_path):
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert storage.read_temp_c(str(tmp_path / "sys")) is None
