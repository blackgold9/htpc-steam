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

You don't need to know Python or run anything by hand for the normal path — the Remote's own web interface installs a packaged integration:

1. Zip this directory's contents the way upstream's release does (`driver.json`, `src/`, `pyproject.toml`, `README.md` at the root of the zip — see upstream's `.github/workflows/build.yml` for the exact packaging step, which this repo hasn't automated yet).
2. Open the Remote's web interface (`http://<remote-ip>`) → **Settings → Integrations → Add Integration → Upload**, and select the zip.
3. It'll appear as "SteamOS HTPC" in Available Integrations. Configure it with your SteamOS box's IP (the same one `plugin/` is deployed to) and the settings from `setup_flow.py`'s form.

Alternatively, **Docker** (doesn't require touching the Remote's filesystem, runs on any machine on your network):

```bash
cd integration/docker
docker compose up -d --build
```

Then add the integration from the Remote's web interface the same way — Docker mode just runs the driver process somewhere other than the Remote itself; pairing still happens through the Remote's UI.

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
