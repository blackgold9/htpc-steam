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
`DECKY_PLUGIN_SETTINGS_DIR`). New config files are written atomically with mode
`0600`; they are root-owned when written by the plugin, so manual edits may
require `sudo`. If Decky's settings layout changes,
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

## Prerequisites

- [Decky Loader](https://decky.xyz/) already installed on the target box (`ujust setup-decky` on Bazzite).
- Node.js + `pnpm` locally, for building the QAM frontend panel.
- Python 3.11+ locally, for staging and testing the backend. The backend uses
  only the standard library, so staging needs no package downloads. Set
  `PYTHON=/path/to/python` to choose a staging interpreter.
- SSH access to the target box.

## Dev loop

```bash
pnpm install
pnpm build                 # builds src/index.tsx -> dist/index.js
DECK_HOST=my-box.local DECK_USER=my-user ./scripts/deploy.sh
```

`deploy.sh` and the release workflow both use `scripts/stage.sh` to assemble
the same self-contained plugin directory. Each deploy stages the plugin in a
temporary directory, syncs it to the target, and restarts Decky. The sync removes
obsolete plugin files while preserving Decky's `py_modules/.lock`; settings live
outside the plugin directory and are not replaced.

Then open the Quick Access Menu on the box and look for "UC SteamOS Agent".
Verify its status, listening address, and uinput access rows. `GET /health`
alone proves only the backend loaded; it does not prove the QAM panel works.

## Backend tests (no Decky runtime needed)

```bash
pip install pytest
PYTHONPATH=py_modules pytest tests/
```

`py_modules/uc_steamos_agent/` is testable without the `decky` module; only
`main.py` needs the real Decky runtime. CI also imports the HTTP server and sensor
collector from a staged package in an isolated Python process, verifying that
the shipped files work without relying on the developer's environment.

## Hardware survey

Run `scripts/hwmon-dump.sh` on the target box (`ssh user@host 'bash -s' < scripts/hwmon-dump.sh`) and paste the output into `../docs/hardware-notes.md` before implementing the Phase 3 sensor collectors.

## Why this plugin needs `_root`

`plugin.json` requests Decky's `_root` flag, and that is a real trust ask worth being upfront about. The backend needs it for three things:

- **`/dev/uinput`** — creating the virtual keyboard that drives Big Picture navigation. Confirmed working on real hardware; the `uinput access` row in the QAM panel (backed by `GET /health`'s `uinput_available`) is the diagnostic if it isn't.
- **`systemctl suspend`/`poweroff`/`reboot`** — running as root avoids the interactive polkit prompt a plain SSH user hits.
- **Reading another user's session env** — `wpctl` needs the desktop user's `XDG_RUNTIME_DIR` to reach PipeWire, which the plugin reconstructs by scanning `/proc` (see `py_modules/uc_steamos_agent/commands/user_session.py`).

The practical consequence: this plugin runs an HTTP server as root that accepts shutdown commands and synthetic keystrokes from anything on your LAN. Authentication is **off** unless you set `auth_token` in `config.json`. See `../docs/protocol.md`'s "Auth posture" section before running it on a network you don't control.
