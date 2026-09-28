# plugin/ — UC SteamOS Agent (Decky Loader plugin)

Runs on the HTPC (SteamOS or Bazzite, Game Mode) as a Decky Loader plugin. Exposes the HTTP API documented in `../docs/protocol.md` on the LAN for the `integration/` side to talk to.

## Installing

This plugin is **not on the Decky store** and won't be: the store's submission
process requires attesting that generative AI wasn't used to write the majority
of the code, which isn't true here. It installs by sideload instead.

1. Enable developer mode in Decky: Quick Access Menu -> the Decky (plug) icon ->
   gear -> **Settings** -> **General** -> toggle **Developer mode**.
2. A **Developer** tab appears in Decky's settings. Use **Install Plugin from URL**
   and paste the `uc-steamos-agent-<version>.zip` URL from
   [Releases](https://github.com/blackgold9/htpc-steam/releases).
3. Decky will warn that the plugin requests root. It genuinely needs it — see
   "Why this plugin needs `_root`" below before accepting.
4. Confirm it came up: `curl http://<htpc-ip>:8086/health` should return JSON
   with `"uinput_available": true`.

Then set up the `integration/` half to talk to it.

**Before you leave it running:** the agent has no authentication by default.
Set `auth_token` in the plugin's `config.json` and restart the plugin, then
enter the same token during integration setup. On the tested Bazzite host the
file is `~/homebrew/settings/uc-steamos-agent/config.json` (Decky's
`DECKY_PLUGIN_SETTINGS_DIR`). It becomes root-owned and mode `0600` after a QAM
save, so manual edits then require `sudo`. If Decky's settings layout changes,
locate `config.json` under `~/homebrew/settings/`.
See `../docs/protocol.md`'s "Auth posture" for what the token does and doesn't
protect against.

**Optional — Wake-on-LAN arming.** `"wol_arm": true` in the same `config.json`
makes the agent re-apply `ethtool -s <routing-iface> wol g` each time the plugin
starts. Only needed if you want the box wakeable by magic packet: the flag is RAM
state on most drivers, so a driver reload or a power-off clears it and firmware is
the only durable place to set it. Off by default because writing a NIC-wide power
setting the user didn't ask for is not a monitoring plugin's business. Bazzite
ships an equivalent `force-wol.service` (disabled); enabling that instead is fine —
both are idempotent, and the agent reports the resulting state either way.

`GET /health` and `GET /sensors` then carry a `wol` block (arming state, both
kernel gates, interface, driver). It is *omitted* when it can't be read — notably
an unprivileged `ethtool` cannot see the Wake-on fields at all — and absence means
"unknown", never "this NIC can't do Wake-on-LAN".

## Steam Controller Puck pickup monitoring

The backend automatically watches a connected second-generation Steam
Controller Puck (`28de:1304`) and exposes passive state at
`GET /controller-puck`. Confirmed pickup events can be consumed incrementally
from `GET /controller-puck/events?since=<sequence>`. No automation is fired by
the agent itself.

The immediate `0x79=01` report is logged as a candidate but is not trusted on
its own: the event is emitted only after a known charging/charged controller
reports discharging. This deliberately adds roughly 1–2 seconds of latency to
avoid waking an entertainment system because of an ordinary wireless
disconnect. Before attaching actions, leave the agent running during idle,
sleep/wake, Steam restarts, and controller power-off, then inspect
`diagnostics.unconfirmed_disconnect_count` for false candidates. Full field
semantics are in `../docs/protocol.md`.

## Home Assistant MQTT discovery

The agent can publish the HTPC sensors and Steam Controller state directly to
an existing Home Assistant MQTT broker. It creates linked **SteamOS Agent** and
**Steam Controller Puck** devices through MQTT Discovery; pickup candidates are
published immediately and confirmed pickups follow when the charge transition
arrives.

MQTT is disabled by default and is strictly read-only: this implementation has
no MQTT command topic and cannot trigger key input, launch games, terminate a
game, or change power state. Configure and live-apply the broker connection from
the plugin's **Home Assistant MQTT** QAM section; the saved password is never
returned to the frontend. Broker fields can still be edited manually for
recovery. Entity details, topic retention, and a least-privilege Mosquitto ACL
are documented in [`../docs/mqtt.md`](../docs/mqtt.md).

## Prerequisites

- [Decky Loader](https://decky.xyz/) already installed on the target box (`ujust setup-decky` on Bazzite).
- Node.js + `pnpm` locally, for building the QAM frontend panel.
- Python 3.11+ with `pip` locally, for installing the pinned runtime dependency
  into the staged plugin. Set `PYTHON=/path/to/venv/bin/python` if the system
  Python has no `pip`. The target does not need Python package installation.
- SSH access to the target box.

## Dev loop

```bash
pnpm install
pnpm build                 # builds src/index.tsx -> dist/index.js
DECK_HOST=my-box.local DECK_USER=my-user ./scripts/deploy.sh
```

`deploy.sh` and the release workflow both use `scripts/stage.sh` to bundle
`paho-mqtt` into `py_modules/`; a fresh install does not depend on target-side
`pip` or a previously deployed copy. Each deploy downloads runtime wheels
locally, stages the plugin in a temporary directory, and restarts Decky.

Then open the Quick Access Menu on the box and look for "UC SteamOS Agent".
Check the **Home Assistant MQTT** section, save a harmless settings change,
reload the plugin, and verify the change persists. `GET /health` alone proves
only the backend loaded; it does not prove the QAM panel works.

On-device QAM check on Bazzite with Decky 3.2.9: the plugin panel rendered,
saved a disabled-MQTT interval change, and showed the original value again
after saving it back and reloading the plugin. This proves the settings bridge
works; it does not verify a broker connection.

## Backend tests (no Decky runtime needed)

```bash
pip install pytest
pytest tests/
```

`py_modules/uc_steamos_agent/` is testable without the `decky` module; only
`main.py` needs the real Decky runtime. The release bundle vendors the pinned
`paho-mqtt` runtime into `py_modules/` so the target does not need pip or network
access during installation.

## Hardware survey

Run `scripts/hwmon-dump.sh` on the target box (`ssh user@host 'bash -s' < scripts/hwmon-dump.sh`) and paste the output into `../docs/hardware-notes.md` before implementing the Phase 3 sensor collectors.

## Why this plugin needs `_root`

`plugin.json` requests Decky's `_root` flag, and that is a real trust ask worth being upfront about. The backend needs it for three things:

- **`/dev/uinput`** — creating the virtual keyboard that drives Big Picture navigation. Confirmed working on real hardware; the `uinput access` row in the QAM panel (backed by `GET /health`'s `uinput_available`) is the diagnostic if it isn't.
- **`systemctl suspend`/`poweroff`/`reboot`** — running as root avoids the interactive polkit prompt a plain SSH user hits.
- **Reading another user's session env** — `wpctl` needs the desktop user's `XDG_RUNTIME_DIR` to reach PipeWire, which the plugin reconstructs by scanning `/proc` (see `py_modules/uc_steamos_agent/commands/user_session.py`).

The practical consequence: this plugin runs an HTTP server as root that accepts shutdown commands and synthetic keystrokes from anything on your LAN. Authentication is **off** unless you set `auth_token` in `config.json`. See `../docs/protocol.md`'s "Auth posture" section before running it on a network you don't control.
