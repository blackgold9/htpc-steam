from uc_steamos_agent.sensors import sysfs_util


def _make_hwmon(tmp_path, index, name, temps=None):
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / f"hwmon{index}"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text(name)
    for i, (label, value) in enumerate((temps or {}).items(), start=1):
        (hwmon_dir / f"temp{i}_label").write_text(label)
        (hwmon_dir / f"temp{i}_input").write_text(str(value))
    return hwmon_dir


def test_find_hwmon_by_name(tmp_path):
    _make_hwmon(tmp_path, 0, "acpitz")
    _make_hwmon(tmp_path, 1, "k10temp")
    sys_root = str(tmp_path / "sys")
    found = sysfs_util.find_hwmon_by_name("k10temp", sys_root)
    assert found is not None and found.endswith("hwmon1")
    assert sysfs_util.find_hwmon_by_name("missing", sys_root) is None


def test_find_hwmon_by_name_missing_hwmon_class_dir(tmp_path):
    assert sysfs_util.find_hwmon_by_name("k10temp", str(tmp_path / "sys")) is None


def test_find_temp_input_by_label(tmp_path):
    hwmon_dir = _make_hwmon(tmp_path, 3, "k10temp", temps={"Tctl": 39125})
    value = sysfs_util.find_temp_input_by_label(str(hwmon_dir), "Tctl")
    assert value == 39125
    assert sysfs_util.find_temp_input_by_label(str(hwmon_dir), "missing") is None
    assert sysfs_util.find_temp_input_by_label(None, "Tctl") is None


def test_find_temp_input_by_label_is_case_insensitive(tmp_path):
    hwmon_dir = _make_hwmon(tmp_path, 2, "amdgpu", temps={"edge": 39000})
    assert sysfs_util.find_temp_input_by_label(str(hwmon_dir), "EDGE") == 39000


def test_read_value_handles_missing_and_bad_files(tmp_path):
    good = tmp_path / "good"
    good.write_text("42")
    assert sysfs_util.read_value(str(good)) == 42.0
    assert sysfs_util.read_value(str(tmp_path / "missing")) is None
    bad = tmp_path / "bad"
    bad.write_text("not-a-number")
    assert sysfs_util.read_value(str(bad)) is None
