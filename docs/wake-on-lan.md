# Wake-on-LAN (design — proposed, not yet implemented)

**Status: design/plan only.** No WoL code exists in this repo yet. This document supersedes the
2026-08-23 descope recorded in [`command-mapping.md`](command-mapping.md) ("Wake-on-LAN | **Descoped** —
a separate, existing UC integration already handles WoL"). That was a scope decision, not a technical
limit; this doc re-opens it and specifies *how* to build it once the decision to build is confirmed.

Confidence markers follow the repo convention: everything here is **Unverified** until run against
the real Bazzite box, which is the only way to confirm the agent-side half.

## Why re-open a deliberately descoped feature

The original rationale ("a separate UC integration owns WoL") is still true for the *waking* itself.
But WoL turns out to be the one feature in this project that **cannot live entirely in either half**,
and the arming half is something the standalone integration genuinely cannot provide on SteamOS:

**The agent can never send the magic packet.** WoL is used precisely when the box is powered off — at
which moment the agent (which runs on the box) is down and unreachable. The packet must originate from
an always-on host: the UC Remote itself, or the Docker host (already `network_mode: host`,
`integration/docker/docker-compose.yml:13`, so a broadcast frame egresses onto the LAN fine).

**But the NIC has to be *armed* to accept one, and that only happens on the box, as root, while it's
awake.** On Bazzite/SteamOS this is the fragile part: most NIC drivers clear the `wol` wake flag on
every boot, the OS is image-based/read-only so a hand-written persistent systemd unit is awkward, and
`ethtool -s <iface> wol g` has to be re-applied. The plugin already runs as root, already loads at
boot (Decky), and already owns the shutdown path — so it is the natural, and arguably only clean, place
to keep the NIC armed. The separate WoL integration cannot do this.

That asymmetry — sender must be off-box, armer must be on-box — is the reason to build WoL *here*
rather than pair a second integration.

## Core architecture: two halves

| Half | Runs on | Responsibility | New code lands in |
|---|---|---|---|
| **Send** | UC Remote / Docker (always on) | Build + fire the magic packet | `integration/` |
| **Arm** | HTPC (root, while awake) | Keep the NIC accepting magic packets across boot + power-off | `plugin/` |

### Design decision: WoL is NOT an agent `/command`

A naive design adds a `power_on` command to the dispatcher. **Do not do that** — the agent is offline
exactly when it's needed, so such a command could never fire. `POST /command`
([`protocol.md`](protocol.md)) and the dispatcher vocabulary are **unchanged** by this feature. The
"wake" action is handled entirely on the integration side and never crosses the wire. The only agent-
side change is *arming*, which is a local side effect of the power-off path it already runs, not a new
command.

## Magic packet (reference)

48-byte frame, no IP/UDP header semantics beyond delivery: `6 × 0xFF` (the "sync stream") immediately
followed by the 6-byte target MAC repeated **16 times**. Sent as a UDP datagram to port **7** or **9**
(conventionally 9), addressed to either:

- `255.255.255.255` (limited broadcast) — simplest; or
- the subnet broadcast (e.g. `192.168.1.255`) — better across some routers; or
- the box's **last-known unicast IP** ("directed WoL") — most reliable where switches/VLANs/firmware
  drop broadcasts, and the case most likely to matter on a managed home network.

The integration already remembers `config.host`, so we can opportunistically send a unicast attempt in
addition to broadcast. Standard practice is to repeat the packet ~3× over ~1–2s (a sleeping NIC's bus
power state can make it drop the first frame).

## Integration side (send)

- **New `integration/src/uc_intg_steamos/wol.py`** (stdlib `socket`/`binascii` only — do *not*
  reintroduce the old `wakeonlan` PyPI dep; the packet is trivial to build):
  - `build_magic_packet(mac: str) -> bytes`
  - `validate_mac(mac: str) -> bool` — accepts `aa:bb:cc:dd:ee:ff` and `aabbccddeeff`.
  - `send_wol(mac, broadcast="255.255.255.255", port=9, *, unicast: str | None = None, repeats=3, delay_s=0.5) -> bool`
    — `SO_BROADCAST` datagram; also fires a directed copy to `unicast` when given.
- **`config.py`**: add `mac_address: str = ""`, `broadcast_address: str = "255.255.255.255"`,
  `wol_port: int = 9`. **Empty `mac_address` = WoL disabled**, mirroring the `auth_token` opt-in
  posture — no wake surface, no UI button, no behavior change for users who don't want WoL.
- **`setup_flow.py`**: one optional "MAC address (optional, enables Wake-on-LAN)" field + format
  validation (reject a malformed MAC at setup, same spirit as the agent-status 401 check).
- **`device.py`**: `async wake_on_lan() -> bool` that offloads the blocking socket send via
  `asyncio.to_thread`, then on success nudges the existing UNAVAILABLE reconnect loop
  (`_try_reconnect`, `device.py:166`) to poll faster for ~60s so the booting box is picked up quickly.
  **No new power-state tracking**: "is it on?" stays inferred by the agent answering `/health`, exactly
  like `power_shutdown` is already optimistic fire-and-forget.
- **`entities/remote.py`**: add a "Power On" button to `_create_power_page()` (`remote.py:192`) and to
  the `simple_commands` list; special-case `power_on_wol` in `_execute_command` (`remote.py:98`) so it
  calls `device.wake_on_lan()` instead of `send_command`. Only emit the button when a MAC is configured.
- **`entities/media_player.py`**: wire the currently-`pass` ON command (`media_player.py:225`) to
  `wake_on_lan()`, giving OFF=`power_sleep` / ON=wake. Note this is a nicety: a `media_player` in
  `UNAVAILABLE` state may not surface the toggle on the device, so the remote-page button is the
  reliable wake path — don't rely on the media_player alone.

## Plugin side (arm)

- **`commands/power.py`**: before running `systemctl poweroff|hibernate|suspend`, best-effort
  `ethtool -s <iface> wol g`. **Never block or fail the power action on arming** — log and continue.
- **Arm at plugin startup too** (`main.py._main`), not just before power-off, so the wake flag survives
  every ordinary reboot. This is the specific behavior that makes the plugin superior to a one-off
  systemd drop-in on a driver that resets the flag at boot.
- **Interface selection**: auto-detect the default-route interface by parsing `/proc/net/route`
  (destination `00000000`), with a `wol_interface` config override for multi-NIC / bonded boxes.
- **Config gate**: `wol_enabled` in `plugin/…/config.py` + `config.json`. When false (the default), the
  plugin does not touch the NIC at all.

## Hardware / firmware prerequisites (document, not code)

None of these are things the code can verify remotely from an *off* box — call them out in setup +
`hardware-notes.md` and expect a "confirm on real hardware" pass before this is marked anything but
Unverified:

- BIOS/UEFI: Wake-on-LAN / "Power on PCI-E / PCI devices" enabled.
- NIC standby power: PSU 5 V standby rail present and enabled; many boards disable WoL on shutdown
  ("ErP / EuP ready" deep-sleep power settings kill the 5 Vsb rail and defeat WoL entirely).
- Disable OS/firmware "Fast Startup"-style paths that fully power down the NIC.
- `ethtool` present on the box (Bazzite ships it — confirm).
- Wake from S3 (suspend, i.e. `power_sleep`), S4 (hibernate) and S5 (soft off) each behave differently;
  `wake-on: g` covers the magic-packet case but the driver/board must keep NIC power in the target
  state. Confirm which of sleep/hibernate/off actually wake on the real box.
- **SecureOn password**: WoL supports an optional 6-byte "SecureOn" password appended to the packet.
  Out of scope initially; note it as a config extension if any target NIC requires it.

## Testing plan (all unit, no hardware required)

- `build_magic_packet` byte layout (6×FF + 16×MAC) for both MAC formats.
- `validate_mac` accept/reject matrix.
- `send_wol` opens a broadcast datagram socket and calls `sendto` with the packet + expected addr/port
  (mock `socket`); repeats honored; unicast copy fired when a host IP is supplied.
- `_execute_command("power_on_wol")` routes to `device.wake_on_lan()`, **not** `send_command`.
- `media_player` ON command triggers wake.
- Blank `mac_address` ⇒ no Power On button in the page, `wake_on_lan()` is a no-op returning False.
- Agent side: `arm_wol` builds the correct `["ethtool","-s",iface,"wol","g"]` argv and detects the
  default iface from a `/proc/net/route` fixture (mock `subprocess.run`, mock a failing ethtool and
  assert the power action still proceeds).

**Needs the real box to confirm**: NIC actually armed after reboot with the plugin running; box
actually wakes from each power state; broadcast vs directed-WoL behavior on the target network.

## Files to touch (checklist)

- `integration/src/uc_intg_steamos/wol.py` — **new**
- `integration/src/uc_intg_steamos/config.py` — `mac_address`, `broadcast_address`, `wol_port`
- `integration/src/uc_intg_steamos/setup_flow.py` — MAC field + validation
- `integration/src/uc_intg_steamos/device.py` — `wake_on_lan()`, reconnect nudge
- `integration/src/uc_intg_steamos/entities/remote.py` — Power On button + `_execute_command` case; drop
  the "No PowerOn button" note from the power-page docstring
- `integration/src/uc_intg_steamos/entities/media_player.py` — ON → wake
- `plugin/py_modules/uc_steamos_agent/commands/power.py` — `arm_wol()` + iface detection
- `plugin/py_modules/uc_steamos_agent/config.py` + `main.py` — `wol_enabled` / `wol_interface`, arm at boot
- `docs/command-mapping.md` — flip the WoL row from Descoped to implemented (mechanism + Unverified)
- `docs/hardware-notes.md` — BIOS/ethtool/standby-power prerequisites + whatever the confirm pass finds
- `docs/protocol.md` — a note that wake is integration-local and *not* a `/command`
- README — remove WoL from the "deliberately out of scope" line

## Open questions / risks

- **Is unification worth it?** The separate UC WoL integration already wakes the box; the sole new value
  here is the agent-side arming + a single PowerOn button in the same power page. If arming already
  works on your board out-of-the-box (some do), that value shrinks a lot.
- **Directed vs broadcast**: which delivery actually reaches the box is network-specific and only
  knowable live; plan for the unicast fallback to not be optional in practice.
- **Off-box verification is dark**: nothing about the wake path can be self-tested from the integration;
  expect real-hardware iteration and keep it marked Unverified until then.

## Suggested build order

1. Integration sender + config + setup + UI + unit tests (fully testable, no hardware) → commit.
2. Agent arming + iface detection + boot/pre-poweroff + unit tests → commit (Unverified on hardware).
3. Docs flip (command-mapping, README, hardware-notes prereqs).
4. Real-box confirm pass → update confidence in `command-mapping.md` / `hardware-notes.md`.
