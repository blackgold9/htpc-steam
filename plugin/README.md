# plugin/ — UC SteamOS Agent (Decky Loader plugin)

Runs on the HTPC (SteamOS or Bazzite, Game Mode) as a Decky Loader plugin. Exposes the HTTP API documented in `../docs/protocol.md` on the LAN for the `integration/` side to talk to.

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

## Open question: `_root` flag

`plugin.json` requests the `_root` flag so this plugin's `main.py` runs with the same privilege Decky's own backend traditionally has, which should give it `/dev/uinput` and `systemctl`/`loginctl` access without extra udev rules. This needs on-device confirmation once Decky is installed on the target box — the `uinput access` row in the QAM panel (backed by `GET /health`'s `uinput_available` field) is the diagnostic for that.
