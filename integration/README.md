# integration/ — uc_intg_steamos

Fork of [`uc_intg_htpc`](https://github.com/mase1981/uc-intg-htpc) rebranded and rewired to talk to `../plugin/`'s protocol (see `../docs/protocol.md`) instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor. Runs on the UC Remote itself, or in Docker on your network — not on the SteamOS/Bazzite box (that's `../plugin/`).

Ported near-verbatim from upstream: `device.py`, `entities/media_player.py`, `entities/sensor.py`. Rewritten: `client.py` (flat-JSON parser against the agent's single `/sensors` endpoint instead of a LibreHardwareMonitor tree-walker), `entities/remote.py` (SteamOS/Gamescope command set and pages — see `../docs/command-mapping.md`), `driver.json`/`config.py` (rebranded, plus an optional `auth_token` field).

## Status

- All modules import and construct cleanly against the real `ucapi`/`ucapi-framework` packages (not just syntax-checked) — every entity constructor signature was checked against the actually-installed framework version, not assumed from upstream's usage.
- `python -m uc_intg_steamos` actually starts: the real `ucapi.IntegrationAPI` logs `Driver is up: uc_intg_steamos, version: 0.1.0, api: 0.7.0` and its WebSocket server (the protocol a Remote connects over) is confirmed listening and accepting TCP connections.
- 21 unit tests pass, including a protocol contract test that feeds the **actual live `/sensors` and `/games` JSON captured from the Bazzite test box** (`tests/fixtures/`, `tests/test_client_parsing.py`) through `client.py`'s parsers.
- **Full pairing/setup flow confirmed on a real UC Remote 3 (2026-08-23)**: driver run on the Bazzite box, discovered by the Remote over mDNS across a different subnet (`ws://bazzite.local:9090/` — direct `.local` WebSocket resolution failed cross-subnet and had to be overridden with the plain IP at registration, but mDNS *discovery* itself worked cross-subnet), registered via `POST /intg/discover/{driverId}`, and driven end-to-end through `SteamOSSetupFlow`'s real multi-step `RequestUserInput` flow (the framework's restore-prompt screen, then our device-details form) via the Remote's local REST API (`PUT /intg/setup/{driverId}`) — not simulated. Setup completed with `state: OK`, all entities came up `ACTIVE`/`CONNECTED`: `remote.*`, `media_player.*` (monitoring dashboard), `media_player.*_games` (Game Launcher), and 11 `sensor.*` entities.

What's still **not** verified:

- Whether the Remote's on-device UI renders the custom pages (`entities/remote.py`'s Navigation/Volume/Gamescope/Game Session/Function Keys/Power pages) as intended, and the Game Launcher's SOURCE_LIST — entities were confirmed created and connected via the REST API, but attributes only push live once a human adds an entity to a button/activity on the physical Remote (`ucapi_framework` no-ops attribute updates for unconfigured entities) — that UI-layout step is a personalization choice left to the user, not driven from here. Icon references (`uc:arrow-up` etc.) are copied from upstream but never visually confirmed either.
- Media-player monitoring views' icons: `SOURCE_ICONS` in `entities/media_player.py` references `icons/*.png` files that don't exist yet in this repo (upstream's originals weren't available to port) — `device.get_icon_base64()` degrades gracefully to an empty string when a file is missing, so nothing crashes, but the media player entity will show no image until icons are added.

## Installing once you have the Remote

There are three ways to run this, in rough order of how much you'll like living with them.

### Option A — upload to the Remote (custom driver)

The driver runs **on the Remote itself**, so there's no always-on host to keep
alive. Grab `uc-intg-uc_intg_steamos-<version>-aarch64.tar.gz` from
[Releases](https://github.com/blackgold9/htpc-steam/releases) and upload it in the
Web Configurator under **Integrations & Docks -> + -> Install custom integration**.

This is the path to prefer. The tarball is an aarch64 PyInstaller bundle built by
`.github/workflows/release-integration.yml` using Unfolded Circle's own
`r2-pyinstaller` image. Note that it is the one delivery path **not** yet
exercised end-to-end — the pairing confirmed below was done with an external
driver — so treat the first upload as the test.

### Option B — Docker

```bash
docker run -d --name uc-intg-steamos --network host \
  -v uc-intg-steamos:/config \
  ghcr.io/blackgold9/uc-intg-steamos:latest
```

Or from a checkout, `cd integration/docker && docker compose up -d --build`.

`network_mode: host` is required, not optional: mDNS multicast doesn't traverse
Docker's default bridge network, so bridge-mode makes the integration invisible
to the Remote's auto-discovery.

### Option C — run it directly (external driver)

External drivers self-advertise over mDNS, so setup is just "run the process
somewhere on the same LAN as the Remote":

```bash
cd integration
pip install -e .
python -m uc_intg_steamos
```

Leave `UC_DISABLE_MDNS_PUBLISH` unset (defaults to `false`/on) — that env var exists for dev use when you don't want mDNS noise, not for real pairing.

### Pairing (all three options)

1. On the Remote: open the Web Configurator (`http://<remote-ip>`) → **Integrations & Docks** → tap **+** → "SteamOS HTPC" should appear in the discovered list. Select it, confirm past the restore-from-backup prompt (nothing to restore on a first setup), then fill in the device form (name, HTPC IP, monitoring toggle, temp unit, optional auth token, optional WoL MAC + broadcast address — `SteamOSSetupFlow`'s fields). Confirmed working end-to-end on real UC Remote 3 hardware, 2026-08-23.
2. If "SteamOS HTPC" doesn't appear in the discovered list: mDNS *discovery* was confirmed to work even across different subnets in testing (a router-level mDNS reflector, evidently), so a same-subnet requirement is less likely to be the blocker than it once seemed — but if discovery genuinely comes up empty, that's still the first thing to check. A different failure mode was hit in testing instead: discovery found the driver via its `.local` mDNS hostname, but the Remote's own follow-up WebSocket connection to that hostname failed (`Connection refused`) — registering the driver again with the plain IP overridden worked. If the auto-discovered entry connects to a `.local` URL and setup won't progress, that's worth checking first.

### Wake-on-LAN (opt-in)

Leave the MAC blank and there is no wake capability and no behaviour change. Enter it (`aa:bb:cc:dd:ee:ff`, any common separator form) and you get:

- **Power On** on the `remote` entity — modelled with the entity's native `on_off`/`toggle` rather than a custom command, so the Remote's physical POWER button can be mapped to it. OFF means "asleep, wakeable"; ON means the agent answered.
- A **"Wake-on-LAN"** monitoring view reporting what the agent measured: whether the NIC's magic-packet filter is armed *and* whether the kernel keeps power to the device while suspended. Both gates have to be open, and the view names the fix (`ethtool -s <iface> wol g`) when only the first is missing.

The magic packet is built and sent here, not by the agent — the agent is asleep whenever a wake is needed. Each wake attempt fires the packet three times to the limited broadcast, to your configured subnet broadcast if you set one, and to the box's last-known IP (the unicast copy is what gets through networks that drop broadcasts) on UDP/9.

Four things worth knowing before blaming the code when a box won't rise:

- `WAKING` is a real state: after sending, the device probes every poll tick and only claims ON when the agent actually answers. Silence during a wake is expected — the NIC comes back long before the agent can — so it does not abort the wake; only the ~2-minute deadline does, and then the state returns to OFF rather than pretending the box is up.
- Wake works with the "hardware monitoring" toggle off. The ladder that demotes a silent box runs off the game-list fetch precisely because sensors may not be polled; a monitoring-disabled integration can still see the box die and offer Power On.
- Whether the box is *asleep* is decided by a TCP probe of the agent's port (`probe.py`), and it can only be that decisive where a closed port **answers** — a RST, or the ICMP "prohibited" a firewall sends — while an absent host stays silent. The test box's firewalld does exactly that (documented in `docs/hardware-notes.md`), which is why the probe counts an immediate `EHOSTUNREACH` as an answer and only treats a *timeout* as "asleep".
- The failure mode that follows: on a network where a **router**, not the box, rejects closed ports, a sleeping box answers like an awake one. The probe then reports UNAVAILABLE — "Box is on, agent is not answering" — and `can_wake` refuses, because it will not claim a wake on a box it believes is running. WoL is effectively dead on such a network, and there is no honest way to detect around it; the reading is wrong-but-safe rather than a guess. Same-subnet setups (the normal case for WoL anyway) don't hit this.
- A wake is refused while the agent is answering — you can't wake a box that is on — and the Power On item doesn't even appear unless a MAC is configured.

## Local dev loop (no Remote needed)

```bash
cd integration
pip install -e ".[dev]"
pytest tests/ -v
```

To actually start the driver process locally (useful for checking it doesn't crash, or watching its logs) without a real Remote or mDNS:

```bash
UC_DISABLE_MDNS_PUBLISH=true UC_INTEGRATION_HTTP_PORT=9090 UC_CONFIG_HOME=/tmp/uc-intg-config python -m uc_intg_steamos
```

It'll log `Driver is up: ...` and sit listening on the WebSocket port — that's the correct idle state waiting for a Remote to connect. Ctrl+C to stop.
