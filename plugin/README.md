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
enter the same token during integration setup. The file lives in Decky's
per-plugin settings directory (`DECKY_PLUGIN_SETTINGS_DIR`, derived from
`plugin.json`'s `name` — so `~/homebrew/settings/UC SteamOS Agent/config.json`);
`find ~/homebrew/settings -name config.json` will locate it if that's moved.
See `../docs/protocol.md`'s "Auth posture" for what the token does and doesn't
protect against.

## Prerequisites

- [Decky Loader](https://decky.xyz/) already installed on the target box (`ujust setup-decky` on Bazzite).
- Node.js + `pnpm` locally, for building the QAM frontend panel.
- SSH access to the target box.

## Dev loop

```bash
pnpm install
pnpm build                 # builds src/index.tsx -> dist/index.js
DECK_HOST=my-box.local ./scripts/deploy.sh   # rsyncs into ~/homebrew/plugins/ and restarts plugin_loader
```

Then open the Quick Access Menu on the box and look for "UC SteamOS Agent".

## Backend tests (no Decky runtime needed)

```bash
pip install pytest
pytest tests/
```

`py_modules/uc_steamos_agent/` is plain-stdlib Python with no dependency on the `decky` module, so it's fully testable on a dev machine — only `main.py` needs the real Decky runtime.

## Hardware survey

Run `scripts/hwmon-dump.sh` on the target box (`ssh user@host 'bash -s' < scripts/hwmon-dump.sh`) and paste the output into `../docs/hardware-notes.md` before implementing the Phase 3 sensor collectors.

## Why this plugin needs `_root`

`plugin.json` requests Decky's `_root` flag, and that is a real trust ask worth being upfront about. The backend needs it for three things:

- **`/dev/uinput`** — creating the virtual keyboard that drives Big Picture navigation. Confirmed working on real hardware; the `uinput access` row in the QAM panel (backed by `GET /health`'s `uinput_available`) is the diagnostic if it isn't.
- **`systemctl suspend`/`poweroff`/`reboot`** — running as root avoids the interactive polkit prompt a plain SSH user hits.
- **Reading another user's session env** — `wpctl` needs the desktop user's `XDG_RUNTIME_DIR` to reach PipeWire, which the plugin reconstructs by scanning `/proc` (see `py_modules/uc_steamos_agent/commands/user_session.py`).

The practical consequence: this plugin runs an HTTP server as root that accepts shutdown commands and synthetic keystrokes from anything on your LAN. Authentication is **off** unless you set `auth_token` in `config.json`. See `../docs/protocol.md`'s "Auth posture" section before running it on a network you don't control.
