# htpc-steam

A SteamOS/Bazzite-native equivalent of [`mase1981/uc-intg-htpc`](https://github.com/mase1981/uc-intg-htpc)'s Windows agent, for controlling and monitoring a **gaming-focused** Gamescope-mode HTPC from an Unfolded Circle Remote. Not a media-center/movie-box integration — see `docs/command-mapping.md` for what that distinction changed vs. upstream (e.g. no media transport controls).

Two independently-deployed pieces:

- **`plugin/`** — a [Decky Loader](https://decky.xyz/) plugin that runs on the HTPC itself (SteamOS or Bazzite, in Game Mode). It exposes an HTTP API on the LAN for command execution (key injection, volume, power, fixed Steam URI shortcuts) and system sensor readings (CPU/GPU/memory/storage/network/fan/battery), read natively from `/sys` and `/proc` — no LibreHardwareMonitor equivalent needed.
- **`integration/`** — `uc_intg_steamos`, a fork of the upstream integration rebranded and rewired to talk to the new agent's protocol instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor. Runs on the UC Remote itself or in Docker, same as upstream.

See [`docs/protocol.md`](docs/protocol.md) for the wire protocol both sides implement, and [`docs/command-mapping.md`](docs/command-mapping.md) for how each remote-control command maps to a SteamOS/Gamescope mechanism (including what was deliberately left out and why).

## Status

Phases 0-4 built and verified live against a real Bazzite/Gamescope box (`docs/hardware-notes.md`): Decky plugin scaffold, uinput navigation, power/volume, native sensor collection, and Steam URI shortcuts (`steam_settings`/`steam_library`) all confirmed working on real hardware. The `uc_intg_steamos` integration is built and verified as far as possible without a physical UC Remote (see `integration/README.md`) — pairing against a real Remote is the next milestone once one's available.

Not yet done: Phase 5 packaging/docs polish, and a couple of deliberately-deferred items (virtual gamepad input, general-purpose app/URL launching — see `docs/command-mapping.md`'s "Deliberately not implemented" section for why).

## License

MIT — see [LICENSE](LICENSE).
