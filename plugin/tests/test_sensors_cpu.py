from uc_steamos_agent.sensors import cpu


def _write_hwmon(tmp_path, index, name, temps):
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / f"hwmon{index}"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text(name)
    for i, (label, value) in enumerate(temps.items(), start=1):
        (hwmon_dir / f"temp{i}_label").write_text(label)
        (hwmon_dir / f"temp{i}_input").write_text(str(value))
    return hwmon_dir


def test_read_temp_c_matches_real_hardware_reading(tmp_path):
    # Ground truth from docs/hardware-notes.md: k10temp temp1_input=39125, label Tctl
    _write_hwmon(tmp_path, 3, "k10temp", {"Tctl": 39125})
    assert cpu.read_temp_c(str(tmp_path / "sys")) == 39.125


def test_read_temp_c_none_when_no_matching_hwmon(tmp_path):
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert cpu.read_temp_c(str(tmp_path / "sys")) is None


def test_read_cpu_name_from_proc_cpuinfo(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    (proc_root / "cpuinfo").write_text("processor\t: 0\nmodel name\t: AMD Ryzen Test CPU\n")
    assert cpu.read_cpu_name(str(proc_root)) == "AMD Ryzen Test CPU"


def test_read_cpu_name_falls_back_when_missing(tmp_path):
    assert cpu.read_cpu_name(str(tmp_path / "proc")) == "CPU"


def test_read_clock_mhz_averages_all_cores(tmp_path):
    cpu_root = tmp_path / "sys" / "devices" / "system" / "cpu"
    for i, freq in enumerate([3000000, 4000000]):
        core_dir = cpu_root / f"cpu{i}" / "cpufreq"
        core_dir.mkdir(parents=True)
        (core_dir / "scaling_cur_freq").write_text(str(freq))
    assert cpu.read_clock_mhz(str(tmp_path / "sys")) == 3500.0


def test_read_power_w_converts_microwatts(tmp_path):
    # Ground truth: this exact field name/value showed up under amdgpu's hwmon
    # (PPT), not k10temp's, on the test box -- CPU power itself returned
    # nothing there. This test exercises the probe mechanism generically.
    hwmon_dir = tmp_path / "sys" / "class" / "hwmon" / "hwmon0"
    hwmon_dir.mkdir(parents=True)
    (hwmon_dir / "name").write_text("k10temp")
    (hwmon_dir / "power1_input").write_text("32304000")
    assert cpu.read_power_w(str(tmp_path / "sys")) == 32.304


def test_read_power_w_none_when_not_found(tmp_path):
    # Ground truth: this is the actual, confirmed result on the test box.
    (tmp_path / "sys" / "class" / "hwmon").mkdir(parents=True)
    assert cpu.read_power_w(str(tmp_path / "sys")) is None


def _write_stat(proc_root, idle, busy_extra):
    # cpu  user nice system idle iowait irq softirq steal guest guest_nice
    (proc_root / "stat").write_text(f"cpu  {busy_extra} 0 0 {idle} 0 0 0 0 0 0\n")


def test_cpu_load_sampler_first_call_returns_none(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_stat(proc_root, idle=1000, busy_extra=0)
    sampler = cpu.CpuLoadSampler(str(proc_root))
    assert sampler.sample() is None


def test_cpu_load_sampler_second_call_computes_delta(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_stat(proc_root, idle=1000, busy_extra=0)
    sampler = cpu.CpuLoadSampler(str(proc_root))
    sampler.sample()
    # idle unchanged, "user" time jumps 500 -> all-busy delta -> 100% load
    _write_stat(proc_root, idle=1000, busy_extra=500)
    assert sampler.sample() == 100.0


def test_cpu_load_sampler_missing_stat_returns_none(tmp_path):
    sampler = cpu.CpuLoadSampler(str(tmp_path / "proc"))
    assert sampler.sample() is None
