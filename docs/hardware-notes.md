# Hardware Notes

hwmon/sysfs ground truth per device, gathered by running `plugin/scripts/hwmon-dump.sh` on real hardware over SSH. Every sensor-mapping decision in `plugin/py_modules/uc_steamos_agent/sensors/` depends on this — fill in before implementing Phase 3.

## Dev tooling: seeing the box's screen remotely

For visually confirming what a command actually did on the box (nav, launches, recovery attempts) instead of relying on someone physically watching and narrating — which was slow and once led to a stranding incident going unnoticed until reported:

```bash
ssh <user>@<box-ip> 'env DISPLAY=:0 magick x:root png:-' > screenshot.png
```

Validated on the "bazzite" box below: produces a correct, correctly-sized PNG (~1.2MB, matching the display resolution) in ~145ms, purely passive (reads the X server's root window pixmap via ImageMagick's `x:` pseudo-format — no input sent, no focus change, no risk of side effects). Works against the XWayland display Gamescope/Steam render through (`DISPLAY=:0`), no gamescope/compositor cooperation or D-Bus/portal needed. No setup required if `magick`/`imagemagick` and `DISPLAY=:0` are already present, which they were here.

**Known limitation, found 2026-08-23**: this only captures the *primary* XWayland surface (Big Picture / Steam's own UI). An actual running game renders black in the capture — consistent with Steam's `STEAM_MULTIPLE_XWAYLANDS=1` env var, which means each game gets its own separate XWayland instance this tool doesn't see. Fine for verifying Big Picture navigation and Steam's own screens (menus, overlay chrome); not useful for confirming in-game rendering itself. Process-list checks (`pgrep`/`ps`) remain the reliable way to confirm a game is actually running/closed when the screenshot can't show it directly.

## Steam local data: recently-played games (ground truth for the Game Launcher entity)

Researched 2026-08-23 on the "bazzite" box below, cross-checked against real values (a just-played game and the home screen's own displayed stats):

- **`~/.local/share/Steam/userdata/<steam3id>/config/localconfig.vdf`** is the authoritative source, NOT `appmanifest_*.acf`'s own `LastPlayed` field (which is stale/unreliable — it read `0` for every game except the one just played in this session, even ones clearly played recently per the home screen's "Recent Games" carousel). Standard VDF (Valve's tab-indented, quoted-key nested-brace KeyValues format, no commas) — needs a small stdlib-only recursive parser, no pip dependency.
- Path: `UserLocalConfigStore` → `Software` → `Valve` → `Steam` → `apps` → `"<appid>"` → `{"LastPlayed": "<unix_epoch>", "Playtime": "<total minutes>", "Playtime2wks": "<minutes>", ...}`. Confirmed exact match against reality: Bopl Battle's `LastPlayed` (1787507429) landed ~155s after our test launch; Kingdom Come: Deliverance II's `Playtime2wks` (47) matched the home screen's "LAST TWO WEEKS: 47 MIN" exactly.
- Games never played (or long enough ago to not matter) show `LastPlayed: "86400"` — a sentinel value (exactly 1 day in epoch seconds), not a real timestamp. Filter these out rather than treating them as "played on Jan 2 1970".
- The `apps` section includes entries for games the user has ever owned/played, **including ones no longer installed** — cross-reference against `steamapps/appmanifest_<appid>.acf` (only that file's `"name"` field is needed from there; its own `LastPlayed` is the unreliable one above) to get both the display name and confirm the game is still actually installed/launchable before including it in a "recently played" list.
- A separate `"RecentLocalPlayedGameIDs"` key exists as a single packed-binary string (likely little-endian appid+timestamp pairs, matches the exact carousel Steam shows) — not used; the textual `apps` section above is simpler and sufficiently reliable to parse.
- **Correction, found once `games/library.py` actually ran end-to-end (not just spot-checked):** non-game infrastructure appids do NOT get filtered by the "never played" sentinel check — Proton 10.0/11.0 and Steam Linux Runtime 4.0 all showed up with real, recent `LastPlayed` timestamps in `localconfig.vdf` (Steam logs when a compat tool gets invoked to run some other game, same as a real launch). There's no local, offline field distinguishing a "tool" app from a "game" app (that classification only lives in Valve's binary `appinfo.vdf` cache or the store API) — `library.py` filters by a small denylist of Valve's own stable tool-name prefixes (`Proton `, `Steam Linux Runtime`, `Steamworks Common Redistributables`, `SteamVR`) instead.
- **Favorites stretch goal: not easily extractable, not pursued.** No per-game "favorite" flag exists in the plain-text VDF files searched (`localconfig.vdf`'s only "Favorite" hit is `FavoriteServersLastUpdateTime`, about multiplayer server bookmarks, unrelated). Modern Steam's library "Collections" (which favorites are a special case of) live in the client's newer Chromium-based UI storage — likely a leveldb/IndexedDB store, not a simple local file — too fragile to reverse-engineer for this. Recents (already the priority per the grilling session) is the only practical path for now.

Things that looked promising but didn't work here, for reference: `import -window root` (ImageMagick's older screenshot tool) failed with an arg-parsing error on this box's ImageMagick 7.1.2 beta — `magick x:root` is the working equivalent. `spectacle -b -f -o file.png` (KDE's tool) hung indefinitely — its `org.freedesktop.portal.Desktop` Screenshot backend doesn't support the gamescope compositor. Wayland-native tools (`grim` etc.) aren't applicable since gamescope isn't wlroots-based.

## Devices tested

### "bazzite" — the current test box: Bazzite 43.20260415.0 (Kinoite), kernel 6.17.7-ba29.fc43.x86_64

Reached over SSH as `stephen@192.168.6.196` (key auth; `user@` and `deck@` are not the account names here). Re-surveyed 2026-09-05. **This is a different machine from the 2026-08-22/23 dump recorded further below** — that one was reached at `192.168.6.193` with a Ryzen 9 8945HS APU on `enp151s0`; this one is a desktop-socket box. `192.168.6.193` is not reachable from the dev machine anymore, so the older section can no longer be re-verified and is kept as a historical record rather than being edited into agreement.

Facts confirmed live on this box:

```
CPU     AMD Ryzen 5 7600X3D 6-Core Processor          (hwmon: k10temp)
GPU     Navi 48 [Radeon RX 9070/9070 XT/9070 GRE]     1002:7550 -> card1
iGPU    Raphael [AMD/ATI]                             1002:164e -> card0
Board   Gigabyte X870 GAMING WIFI6, BIOS F13
NIC     enp9s0, driver r8169, MAC 30:56:0f:b6:7a:9e (default route)
        wlan0 present and DOWN
hwmons  acpitz, nvme, amdgpu, amdgpu, k10temp, gigabyte_wmi, zenergy, r8169_0_900:00
suspend freeze mem disk;  mem_sleep: s2idle [deep]  (deep is selected)
resume  /sys/power/resume = 0:0  (hibernate image device NOT configured)
        => suspend works and is WoL-recoverable; hibernate is effectively
           "suspend-to-disk unconfigured" and must not be offered as a
           WoL-round-trip path on this box without setting up a resume= device.
firewall firewalld active — and it changes what the probe can conclude (below)
GET /sensors (agent 0.1.0): cpu temp 46.4C, gpu temp 57C, mem 3.7/14.7 GiB,
        storage 340.5/951.3 GiB @ 47.85C, cpu_power null, fans [], battery absent.
```

Two sensor conclusions from the earlier box survived the hardware change unchanged: CPU power has no hwmon here either (still `null`), and there are still no `fan*_input` nodes, so `fans: []` remains a normal outcome rather than a fault. Note `gigabyte_wmi` and `zenergy` hwmons now exist and are unread by any sub-collector — potential future fan/pump sources on Gigabyte boards, deliberately not guessed at.

### Wake-on-LAN ground truth (this box, 2026-09-05)

The part that matters for the WoL feature, because three of its assumptions came back wrong from the lab:

- **Both kernel gates are open.** `/sys/class/net/enp9s0/device/power/wakeup` reads `enabled`, and `deep` (not `s2idle`) is the selected suspend mode — so an armed r8169 keeps enough power to see a magic packet. `ethtool -s enp9s0 wol g` is the only thing missing.
- **Unprivileged `ethtool` cannot see Wake-on at all.** `ethtool enp9s0` as the SSH user prints a *complete link dump* (`Speed: 1000Mb/s`, `Link detected: yes`), exits **0**, and contains neither `Supports Wake-on:` nor `Wake-on:` — with `netlink error: Operation not permitted` on stderr. A parser that reads absent fields as "unsupported" would tell the user this NIC can't do Wake-on-LAN. `commands/wol.py` therefore reports `reported: false` → `None` → *unknown*, and never conflates "couldn't read" with "can't do it". Root (i.e. the agent itself, via `wol_arm`) is what makes the fields appear.
- **No passwordless sudo** for the SSH user here, so arming could only be confirmed through the agent's own root context, not from the dev shell.
- **The OS already ships the mechanism, disabled:** `force-wol.service` (`/usr/lib/systemd/system/`, `Type=oneshot`, `ExecStart=/usr/libexec/force-wol`, `WantedBy=network-online.target`) is `disabled/disabled`. It is exactly the "re-arm on every boot" job the agent's `wol_arm` option does. Either is sufficient; both are idempotent. Documented so a user with the systemd unit enabled doesn't conclude the agent's flag is broken.
- **firewalld rejects closed ports instead of dropping them.** `192.168.6.196:8086` connects; `:9` and `:7` fail in ~1ms with `EHOSTUNREACH`; `:12345`/`:8087` fail with `ECONNREFUSED`; a genuinely absent host on the same LAN (`192.168.6.201`) produces a *timeout*. So "silence = asleep" only holds for timeouts, and the probe must treat `EHOSTUNREACH` as an answer. Consequence recorded in `integration/src/uc_intg_steamos/probe.py`: only the agent's own port is probed, since a firewalled port can't discriminate at all.
- **BIOS-side settings could not be inspected, and are not claimed.** Wake-on-LAN on this board (Gigabyte X870 GAMING WIFI6, BIOS F13) also depends on firmware: the NIC wake option and, critically, whether the board's standby power rails stay live — an enabled ErP/EuP setting or "Deep Sleep" mode kills the NIC's 5 V standby and no amount of `ethtool wol g` survives it. There is no Linux-readable surface for any of that (nothing in sysfs or `ethtool` reports it), so it stays an unverified prerequisite that only a power-off test can settle. `wol_supported`/`wol_enabled`/`may_wakeup` being all true says the OS half is ready; it says nothing about the firmware half.

Persistence, since it decides whether a wake still works next week: `Wake-on: g` is RAM state on r8169 and most other drivers. It survives suspend (which is the point — suspend is what keeps the NIC powered) but is cleared by a driver reload, a kernel update, NetworkManager re-creating the link, and by a full power-off. So a box that is `power_sleep`'d keeps its arming, a box that is `power_shutdown`'d does not unless something re-arms it on boot: that is the job of `wol_arm` in the agent, or of Bazzite's `force-wol.service`, or of a oneshot unit the user writes. Firmware is the only setting durable across a power cut.

Not yet verified, and deliberately not claimed anywhere: that a magic packet actually brings this box back. That requires powering it off, which takes the test box (and the agent reporting it) down; it is the one remaining step and needs the box's MAC armed first.


### Previous test box (2026-08-22/23) — Bazzite 44.20260820.0 (Kinoite/bazzite-deck image), kernel 7.2.0-ogc4.1.fc44.x86_64

**Historical.** Reachable at the time via `192.168.6.193`, which no longer answers; kept because it is the source of record for the sensor-mapping decisions in `plugin/py_modules/uc_steamos_agent/sensors/` and for the `enp151s0` fixture in `plugin/tests/test_sensors_network.py`, and none of the findings below were contradicted by the newer box above. Its interface and CPU names are *not* this box's.

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
