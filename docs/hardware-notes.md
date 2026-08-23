# Hardware Notes

hwmon/sysfs ground truth per device, gathered by running `plugin/scripts/hwmon-dump.sh` on real hardware over SSH. Every sensor-mapping decision in `plugin/py_modules/uc_steamos_agent/sensors/` depends on this — fill in before implementing Phase 3.

## Devices tested

### "bazzite" desktop box — Bazzite 44.20260820.0 (Kinoite/bazzite-deck image), kernel 7.2.0-ogc4.1.fc44.x86_64

AMD desktop (Ryzen-class CPU + AMD dGPU/APU, not a handheld), reached over SSH at 192.168.6.193. Confirmed running a real Gamescope session at the time of this dump: `gamescope-session-plus ogui-steam` launching `gamescope --prefer-output *,eDP-1 ... --steam` with Steam in `-gamepadui -steamos3 -steampal -steamdeck` (Big Picture/Deck UI), auto-started via SDDM autologin — i.e. this box is genuinely in the target environment, not just installed-but-idle.

Raw dump: see `hwmon-dump.sh` output captured 2026-08-23T02:58:15Z (not committed verbatim — summarized below).

```
hwmon0  acpitz         temp1_input
hwmon1  nvme           temp1_input/crit/max (label "Composite"), temp2 "Sensor 1", temp3 "Sensor 2"
hwmon2  amdgpu         freq1_input (label sclk), in0/in1 (vddgfx/vddnb), power1_input (label PPT), temp1_input (label edge)
hwmon3  k10temp        temp1_input (label "Tctl")
hwmon4  r8169_0_200:00 temp1_input/max
hwmon5  r8169_0_300:00 temp1_input/max
hwmon6  spd5118        temp1_input/crit/max   (RAM SPD temp sensor, DDR5 — not currently in scope)
hwmon7  mt7921_phy0    temp1_input            (WiFi chip temp — not currently in scope)
hwmon8  enp151so       temp1 "PHY Temperature", temp2 "MAC Temperature"
hwmon9  hidpp_battery_0  (no temp sensors)

power_supply: only hidpp_battery_0 (type Battery, capacity 70%) — a wireless Logitech
peripheral's battery, NOT a system battery. Does not match the `BAT*` glob the plan's
battery.py design uses, so it's correctly excluded without any extra filtering logic.

/sys/class/drm/card1/device/gpu_busy_percent = 64   (direct 0-100 GPU load, no hwmon needed)

default route: enp151s0 (matches the /proc/net/route auto-detect design)
```

Findings:
- **CPU temp**: `k10temp` hwmon, `temp1_input`, label `Tctl`. This is the standard AMD desktop convention (control temp, junction-proxy) — matches what most Linux monitoring tools treat as "the" CPU temp for Ryzen-class chips. `find_hwmon_by_name("k10temp")` is a reliable match here; still need to confirm on an actual APU (Deck-class) whether the hwmon name differs.
- **GPU temp**: `amdgpu` hwmon, `temp1_input`, label `edge`. **GPU load**: not from hwmon at all — read directly from `/sys/class/drm/card*/device/gpu_busy_percent` (0-100 int, no math needed). Card index isn't stable/predictable (this box's active GPU was `card1`, not `card0`) — the sensor collector needs to iterate `/sys/class/drm/card*/device/` and pick the one whose `hwmon*/name` reads `amdgpu`, rather than assuming an index.
- **GPU power**: `amdgpu` hwmon `power1_input`, label `PPT` (Package Power Tracking), in µW (32304000 µW = 32.3W here, plausible for near-idle). Confirms the plan's `power1_average`/`energy1_input` guess was close but the actual key on this box is `power1_input` — sensor code should probe a small set of candidate keys (`power1_average`, `power1_input`, `energy1_input`) rather than hardcoding one.
- **NVMe temp**: `nvme` hwmon, `temp1_input`, label `Composite` — this is the NVMe spec's standard "overall drive temp" sensor, the right one to surface as storage temp.
- **Fan**: **no fan hwmon present on this box at all** (no `fan*_input` anywhere in the dump) — either this system has no fan-speed-reporting sensor exposed, or it's genuinely fanless/liquid-cooled without a monitored header. Sensor collector must treat "no fans found" as a normal, expected case (empty `fans: []`), not an error — already the plan's design, confirmed necessary in practice, not just in theory.
- **Battery**: not present on this box (desktop). The `BAT*` glob correctly avoids the misleading `hidpp_battery_0` peripheral entry — validates that design choice, no change needed.
- **Network temp sensors**: naming varies by NIC driver — `r8169_0_*` (older Realtek driver convention, PCI-ID-suffixed name) vs. the active interface's own `enp151s0` hwmon with `PHY Temperature`/`MAC Temperature` labels (newer r8125-style). Not used by the network throughput sensor anyway (that reads `/sys/class/net/*/statistics/*_bytes` directly), so this is just a naming-convention note, not a blocker.
- **Default route auto-detect**: confirmed working — `enp151s0` is both the default-route interface and the one with live PHY/MAC temps, consistent with the plan's `/proc/net/route`-based auto-detection approach.

Open, still needed: a real Deck/handheld APU dump, to confirm CPU/GPU hwmon naming on fused-die hardware (this box has discrete `k10temp` + `amdgpu` as separate hwmon nodes, which may not hold on an APU) and to find the actual fan hwmon name (this box has none to compare against).

**Phase 0 on-device checklist — all confirmed on this box (2026-08-22/23):**
- Decky Loader was already installed; the plugin was picked up cleanly (`found plugin: uc-steamos-agent`, `Loaded UC SteamOS Agent` in `plugin_loader`'s journal).
- `plugin.json`'s `_root` flag genuinely grants `/dev/uinput` access — `GET /health` returns `uinput_available: true`.
- The HTTP server is reachable both from the box itself and over the LAN (`http://192.168.6.193:8086/health`).
- **Cold reboot survival verified for real** (not just inferred from `enabled` unit status): rebooted the box, `plugin_loader.service` came back automatically (it's a system-level unit, not tied to any login session), our plugin auto-loaded, the Gamescope/Steam Big Picture session auto-started via SDDM autologin, and the agent was reachable again within ~30s of boot — no manual steps.
- **Startup-time race found**: the plugin's own startup log line captured `uinput_available=False` at the exact moment `_main()` fired right after boot, but `GET /health` a few seconds later correctly showed `true`. `/dev/uinput` likely isn't immediately accessible the instant the plugin process starts during early boot. This validates re-probing live on every `/health` call (`uinput_writable()` is called fresh each request, not cached at startup) rather than trusting a one-time boot-time check — keep it that way through Phase 1+.

Template for the next device once dumped:

```
### <device name/model> — <OS> <version>, kernel <uname -r>

<paste plugin/scripts/hwmon-dump.sh output>

Findings:
- CPU temp hwmon: ...
- GPU temp/load hwmon: ...
- Fan hwmon (driver name): ...
- NVMe temp hwmon: ...
- Battery present: yes/no, path: ...
```
