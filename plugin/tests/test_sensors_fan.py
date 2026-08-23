from uc_steamos_agent.sensors import fan


def test_no_fan_hwmon_returns_empty_list(tmp_path):
    # Confirmed on real hardware: the Bazzite desktop test box has no fan
    # hwmon at all -- this is the normal, expected result, not an error.
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert fan.read_fan_speeds(str(tmp_path / "sys")) == []


def test_finds_fan_input_across_any_hwmon(tmp_path):
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / "hwmon5"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text("nct6775")
    (hwmon_dir / "fan1_input").write_text("1800")
    (hwmon_dir / "fan2_input").write_text("0")  # inactive fan, excluded
    assert fan.read_fan_speeds(str(tmp_path / "sys")) == [{"label": "nct6775 fan1", "rpm": 1800}]


def test_collects_fans_from_multiple_hwmon_dirs(tmp_path):
    for idx, (name, rpm) in enumerate([("nct6775", 1200), ("it87", 2400)]):
        hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / f"hwmon{idx}"
        hwmon_dir.mkdir(parents=True)
        (hwmon_dir / "name").write_text(name)
        (hwmon_dir / "fan1_input").write_text(str(rpm))
    fans = fan.read_fan_speeds(str(tmp_path / "sys"))
    assert {f["rpm"] for f in fans} == {1200, 2400}
