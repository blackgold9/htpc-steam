from uc_steamos_agent.sensors import battery


def test_no_power_supply_entries(tmp_path):
    (tmp_path / "sys" / "class" / "power_supply").mkdir(parents=True)
    assert battery.read_battery(str(tmp_path / "sys")) == battery.EMPTY


def test_hidpp_peripheral_battery_is_excluded(tmp_path):
    # Ground truth: the test box's only power_supply entry is a wireless
    # mouse (hidpp_battery_0), which must not be mistaken for a system battery.
    ps_dir = tmp_path / "sys" / "class" / "power_supply" / "hidpp_battery_0"
    ps_dir.mkdir(parents=True)
    (ps_dir / "type").write_text("Battery")
    (ps_dir / "capacity").write_text("70")
    assert battery.read_battery(str(tmp_path / "sys")) == battery.EMPTY


def test_real_system_battery_detected(tmp_path):
    bat_dir = tmp_path / "sys" / "class" / "power_supply" / "BAT1"
    bat_dir.mkdir(parents=True)
    (bat_dir / "capacity").write_text("85")
    (bat_dir / "status").write_text("Charging")
    (bat_dir / "power_now").write_text("15000000")
    result = battery.read_battery(str(tmp_path / "sys"))
    assert result == {"present": True, "percent": 85.0, "charging": True, "power_w": 15.0}


def test_discharging_status(tmp_path):
    bat_dir = tmp_path / "sys" / "class" / "power_supply" / "BAT0"
    bat_dir.mkdir(parents=True)
    (bat_dir / "capacity").write_text("42")
    (bat_dir / "status").write_text("Discharging")
    result = battery.read_battery(str(tmp_path / "sys"))
    assert result["charging"] is False
    assert result["power_w"] is None  # power_now not present in this fixture
