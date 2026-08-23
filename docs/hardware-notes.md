# Hardware Notes

hwmon/sysfs ground truth per device, gathered by running `plugin/scripts/hwmon-dump.sh` on real hardware over SSH. Every sensor-mapping decision in `plugin/py_modules/uc_steamos_agent/sensors/` depends on this — fill in before implementing Phase 3.

## Dev tooling: seeing the box's screen remotely

For visually confirming what a command actually did on the box (nav, launches, recovery attempts) instead of relying on someone physically watching and narrating — which was slow and once led to a stranding incident going unnoticed until reported:

```bash
ssh <user>@<box-ip> 'env DISPLAY=:0 magick x:root png:-' > screenshot.png
```

Validated on the "bazzite" box below: produces a correct, correctly-sized PNG (~1.2MB, matching the display resolution) in ~145ms, purely passive (reads the X server's root window pixmap via ImageMagick's `x:` pseudo-format — no input sent, no focus change, no risk of side effects). Works against the XWayland display Gamescope/Steam render through (`DISPLAY=:0`), no gamescope/compositor cooperation or D-Bus/portal needed. No setup required if `magick`/`imagemagick` and `DISPLAY=:0` are already present, which they were here.

**Known limitation, found 2026-08-23**: this only captures the *primary* XWayland surface (Big Picture / Steam's own UI). An actual running game renders black in the capture — consistent with Steam's `STEAM_MULTIPLE_XWAYLANDS=1` env var, which means each game gets its own separate XWayland instance this tool doesn't see. Fine for verifying Big Picture navigation and Steam's own screens (menus, overlay chrome); not useful for confirming in-game rendering itself. Process-list checks (`pgrep`/`ps`) remain the reliable way to confirm a game is actually running/closed when the screenshot can't show it directly.

Things that looked promising but didn't work here, for reference: `import -window root` (ImageMagick's older screenshot tool) failed with an arg-parsing error on this box's ImageMagick 7.1.2 beta — `magick x:root` is the working equivalent. `spectacle -b -f -o file.png` (KDE's tool) hung indefinitely — its `org.freedesktop.portal.Desktop` Screenshot backend doesn't support the gamescope compositor. Wayland-native tools (`grim` etc.) aren't applicable since gamescope isn't wlroots-based.

## Devices tested

### "bazzite" box — Bazzite 44.20260820.0 (Kinoite/bazzite-deck image), kernel 7.2.0-ogc4.1.fc44.x86_64

**Correction (Phase 3):** `GET /sensors` later identified the CPU as an **AMD Ryzen 9 8945HS w/ Radeon 780M Graphics** — a mobile/handheld-class APU (used in devices like the ROG Ally X, GPD Win Max 2, and similar compact PCs), not a desktop-socket chip as originally assumed below. The Gamescope launch args' `--prefer-output *,eDP-1` (an embedded-display connector, not DP/HDMI) was a hint missed at the time. Likely a mini-PC/SFF or laptop-class device with a built-in or LCD panel, not a full desktop tower. Doesn't change any finding below, but corrects the framing — this is closer to the plan's actual target hardware class than "desktop" suggested.

Reached over SSH at 192.168.6.193. Confirmed running a real Gamescope session at the time of this dump: `gamescope-session-plus ogui-steam` launching `gamescope --prefer-output *,eDP-1 ... --steam` with Steam in `-gamepadui -steamos3 -steampal -steamdeck` (Big Picture/Deck UI), auto-started via SDDM autologin — i.e. this box is genuinely in the target environment, not just installed-but-idle.

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

~~Open, still needed: a real Deck/handheld APU dump~~ — **resolved**: this box's CPU turned out to be an APU (Ryzen 9 8945HS w/ Radeon 780M — see the Phase 3 correction above), and it still exposes `k10temp` (CPU) + `amdgpu` (GPU) as separate hwmon nodes despite being a fused die. The split-node convention holds on APU hardware, at least this one. Still open: the actual fan hwmon name — this box has none to compare against.

**Phase 0 on-device checklist — all confirmed on this box (2026-08-22/23):**
- Decky Loader was already installed; the plugin was picked up cleanly (`found plugin: uc-steamos-agent`, `Loaded UC SteamOS Agent` in `plugin_loader`'s journal).
- `plugin.json`'s `_root` flag genuinely grants `/dev/uinput` access — `GET /health` returns `uinput_available: true`.
- The HTTP server is reachable both from the box itself and over the LAN (`http://192.168.6.193:8086/health`).
- **Cold reboot survival verified for real** (not just inferred from `enabled` unit status): rebooted the box, `plugin_loader.service` came back automatically (it's a system-level unit, not tied to any login session), our plugin auto-loaded, the Gamescope/Steam Big Picture session auto-started via SDDM autologin, and the agent was reachable again within ~30s of boot — no manual steps.
- **Startup-time race found**: the plugin's own startup log line captured `uinput_available=False` at the exact moment `_main()` fired right after boot, but `GET /health` a few seconds later correctly showed `true`. `/dev/uinput` likely isn't immediately accessible the instant the plugin process starts during early boot. This validates re-probing live on every `/health` call (`uinput_writable()` is called fresh each request, not cached at startup) rather than trusting a one-time boot-time check — keep it that way through Phase 1+.

**Phase 3 — `GET /sensors` confirmed fully live on this box (2026-08-23):**
```
cpu:     name="AMD Ryzen 9 8945HS w/ Radeon 780M Graphics", temp_c=42.75, load_pct=9.57,
         clock_mhz=3680.0, power_w=null (confirmed: no CPU power hwmon on this box, as predicted)
gpu:     temp_c=35.0, load_pct=26.0 (via gpu_busy_percent on the discovered card, not hwmon)
memory:  used_gb=3.17, total_gb=13.41 (total is less than physical RAM — plausible for an APU,
         which reserves shared memory for the iGPU framebuffer)
storage: used_gb=236.6, total_gb=928.9, used_pct=25.5, temp_c=37.85
network: up_kbps=72.2, down_kbps=511.0
motherboard: null/null (unimplemented, as documented — no Super I/O hwmon to verify against)
fans:    []  (confirmed: none present, as expected)
battery: not present (confirmed: no BAT* entry, as expected)
```
Every field that was predicted to degrade to `null`/`[]` (CPU power, motherboard, fans, battery) did so correctly rather than crashing or returning a misleading value — the graceful-degradation design (`SensorCollector._safe`) held up under real conditions, not just the unit tests' simulated failures.

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
