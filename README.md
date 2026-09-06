# htpc-steam

A SteamOS/Bazzite-native equivalent of [`mase1981/uc-intg-htpc`](https://github.com/mase1981/uc-intg-htpc)'s Windows agent, for controlling and monitoring a **gaming-focused** Gamescope-mode HTPC from an Unfolded Circle Remote. Not a media-center/movie-box integration — see `docs/command-mapping.md` for what that distinction changed vs. upstream (e.g. no media transport controls).

Two independently-deployed pieces:

- **`plugin/`** — a [Decky Loader](https://decky.xyz/) plugin that runs on the HTPC itself (SteamOS or Bazzite, in Game Mode). It exposes an HTTP API on the LAN for command execution (key injection, volume, power, fixed Steam URI shortcuts) and system sensor readings (CPU/GPU/memory/storage/network/fan/battery), read natively from `/sys` and `/proc` — no LibreHardwareMonitor equivalent needed.
- **`integration/`** — `uc_intg_steamos`, a fork of the upstream integration rebranded and rewired to talk to the new agent's protocol instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor. Runs on the UC Remote itself or in Docker, same as upstream.

See [`docs/protocol.md`](docs/protocol.md) for the wire protocol both sides implement, and [`docs/command-mapping.md`](docs/command-mapping.md) for how each remote-control command maps to a SteamOS/Gamescope mechanism (including what was deliberately left out and why).

## Status

Working end-to-end on real hardware. Both halves are built, unit-tested (135 + 23 tests), and verified live against a Bazzite/Gamescope box and a physical UC Remote 3 — see `docs/hardware-notes.md` for the raw findings.

Confirmed on real hardware: uinput navigation of Big Picture, volume via PipeWire, native sensor collection, Steam URI shortcuts, the three-tier game-exit escalation (`steam_overlay` / `alt_f4` / `force_quit_game`), launching a game by appid from the recently-played list, and the full Remote pairing/setup flow with all entities coming up `ACTIVE`/`CONNECTED`.

Not yet verified: the power commands (`power_sleep`/`hibernate`/`shutdown`/`restart`) are implemented and unit-tested but never fired live, since doing so takes the test box down; and how the Remote's on-device UI actually renders the custom pages, which needs a human to add the entities to a page first.

Deliberately out of scope: virtual gamepad input and general-purpose app/URL launching — see `docs/command-mapping.md`'s "Deliberately not implemented" section for the reasoning on each. Wake-on-LAN is implemented on this branch in its original upstream form (client-side `wakeonlan` magic packet, gated on a configured `mac_address`), inherited from upstream's Windows integration and **never verified live on SteamOS** — firing it needs the box powered off first.

## Security

The agent is an HTTP server running as root on your gaming box, and its command vocabulary includes shutdown and synthetic keystroke injection. It is off by default to the extent that it only listens on your LAN, but **there is no authentication unless you configure one.** Set `auth_token` in the agent's `config.json` and enter the same value during integration setup. Read [`docs/protocol.md`](docs/protocol.md)'s "Auth posture" section before exposing this on a network you don't control — it is explicit about what the token does and does not protect against.

## License

MIT — see [LICENSE](LICENSE).
