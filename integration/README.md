# integration/ — uc_intg_steamos

Fork of [`uc_intg_htpc`](https://github.com/mase1981/uc-intg-htpc) rebranded and rewired to talk to `../plugin/`'s protocol (see `../docs/protocol.md`) instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor. Runs on the UC Remote itself, or in Docker on your network — not on the SteamOS/Bazzite box (that's `../plugin/`).

Ported near-verbatim from upstream: `device.py`, `entities/media_player.py`, `entities/sensor.py`. Rewritten: `client.py` (flat-JSON parser against the agent's single `/sensors` endpoint instead of a LibreHardwareMonitor tree-walker), `entities/remote.py` (SteamOS/Gamescope command set and pages — see `../docs/command-mapping.md`), `driver.json`/`config.py` (rebranded, plus an optional `auth_token` field).

## Status

Built and verified as far as possible **without a physical UC Remote** (none available yet). What's been confirmed:

- All modules import and construct cleanly against the real `ucapi`/`ucapi-framework` packages (not just syntax-checked) — every entity constructor signature was checked against the actually-installed framework version, not assumed from upstream's usage.
- `python -m uc_intg_steamos` actually starts: the real `ucapi.IntegrationAPI` logs `Driver is up: uc_intg_steamos, version: 0.1.0, api: 0.7.0` and its WebSocket server (the protocol a Remote connects over) is confirmed listening and accepting TCP connections.
- 15 unit tests pass, including a protocol contract test that feeds the **actual live `/sensors` JSON captured from the Bazzite test box** (`tests/fixtures/agent_sensors_response.json`) through `client.parse_sensor_data()` and asserts the resulting `SystemData`.

What's **not** verified and needs the real Remote once you have one:

- The actual pairing/setup flow through the Remote's UI (`SteamOSSetupFlow`) — the logic is unit-tested with a mocked agent, but the real multi-step UI flow (`RequestUserInput` rendering, field validation round-trips) has never been driven by a real Remote or its web-configurator.
- Whether the Remote's UI renders the custom pages (`entities/remote.py`'s Navigation/Media/Gamescope/Function Keys/Power pages) as intended — icon references (`uc:arrow-up` etc.) are copied from upstream but never visually confirmed.
- Media-player monitoring views' icons: `SOURCE_ICONS` in `entities/media_player.py` references `icons/*.png` files that don't exist yet in this repo (upstream's originals weren't available to port) — `device.get_icon_base64()` degrades gracefully to an empty string when a file is missing, so nothing crashes, but the media player entity will show no image until icons are added.

## Installing once you have the Remote

This integration is an **external driver** (runs on a separate device, talks to the Remote over the network) — not the Remote's separate sandboxed "custom driver" feature, which needs a PyInstaller-compiled binary via Unfolded Circle's own `r2-pyinstaller` toolchain (that's what upstream's `.tar.gz` release asset and its `.github/workflows/build.yml` actually build; it's unnecessary extra work for us). External drivers self-advertise over mDNS, so setup is just "run the process somewhere on the same LAN as the Remote":

1. Run the driver on any machine on the **same LAN/subnet** as the Remote (mDNS discovery requires this — it won't cross VLANs or networks with client isolation, e.g. some guest Wi-Fi/mesh setups):
   ```bash
   cd integration
   pip install -e .
   python -m uc_intg_steamos
   ```
   Leave `UC_DISABLE_MDNS_PUBLISH` unset (defaults to `false`/on) — that env var exists for dev use when you don't want mDNS noise, not for real pairing.
2. On the Remote: open the Web Configurator (`http://<remote-ip>`) → **Integrations & Docks** → tap **+** → "SteamOS HTPC" should appear in the discovered list. Select it and follow the setup form (host IP, monitoring toggle, temp unit, MAC, auth token — `SteamOSSetupFlow`'s fields).
3. If it doesn't appear: confirm the Remote and the driver's host are genuinely on the same subnet and that mDNS/multicast isn't blocked between them (the most common real-world failure, especially on mesh/guest Wi-Fi). Whether the manual-add flow accepts a bare host/IP for integrations (as opposed to Docks, which need a full `ws://` URL) hasn't been confirmed — check this hands-on if auto-discovery fails.

Alternatively, **Docker** (runs on any machine on your network, no local Python needed):

```bash
cd integration/docker
docker compose up -d --build
```

`docker-compose.yml` uses `network_mode: host` deliberately — mDNS multicast doesn't traverse Docker's default bridge network, so bridge-mode would make the integration invisible to the Remote's auto-discovery. Pairing then works the same as step 2 above.

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
