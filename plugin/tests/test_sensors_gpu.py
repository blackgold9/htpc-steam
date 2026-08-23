import os

from uc_steamos_agent.sensors import gpu


def _make_amdgpu_hwmon(tmp_path, temp_c_milli):
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / "hwmon2"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text("amdgpu")
    (hwmon_dir / "temp1_label").write_text("edge")
    (hwmon_dir / "temp1_input").write_text(str(temp_c_milli))


def _make_card(tmp_path, card_name, driver_name, busy_percent=None):
    device_dir = tmp_path / "sys" / "class" / "drm" / card_name / "device"
    device_dir.mkdir(parents=True)
    if busy_percent is not None:
        (device_dir / "gpu_busy_percent").write_text(str(busy_percent))
    driver_target = tmp_path / "sys" / "bus" / "pci" / "drivers" / driver_name
    driver_target.mkdir(parents=True, exist_ok=True)
    os.symlink(driver_target, device_dir / "driver")


def test_read_temp_c_from_amdgpu_hwmon_matches_real_hardware(tmp_path):
    # Ground truth from docs/hardware-notes.md: amdgpu temp1_input=39000, label edge
    _make_amdgpu_hwmon(tmp_path, 39000)
    assert gpu.read_temp_c(str(tmp_path / "sys")) == 39.0


def test_read_temp_c_none_when_no_amdgpu_hwmon(tmp_path):
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert gpu.read_temp_c(str(tmp_path / "sys")) is None


def test_read_load_pct_discovers_non_card0_index(tmp_path):
    # Ground truth: the test box's active GPU was card1, not card0 -- the
    # collector must discover the amdgpu card, not assume a fixed index.
    _make_card(tmp_path, "card0", driver_name="i915")  # decoy, different driver
    _make_card(tmp_path, "card1", driver_name="amdgpu", busy_percent=64)
    assert gpu.read_load_pct(str(tmp_path / "sys")) == 64


def test_read_load_pct_none_when_no_amdgpu_card(tmp_path):
    _make_card(tmp_path, "card0", driver_name="i915")
    assert gpu.read_load_pct(str(tmp_path / "sys")) is None


def test_has_dedicated_gpu_true_when_amdgpu_hwmon_present(tmp_path):
    _make_amdgpu_hwmon(tmp_path, 39000)
    assert gpu.has_dedicated_gpu(str(tmp_path / "sys")) is True


def test_has_dedicated_gpu_false_when_absent(tmp_path):
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert gpu.has_dedicated_gpu(str(tmp_path / "sys")) is False
