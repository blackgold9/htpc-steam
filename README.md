# htpc-steam

A SteamOS/Bazzite-native equivalent of [`mase1981/uc-intg-htpc`](https://github.com/mase1981/uc-intg-htpc)'s Windows agent, for controlling and monitoring a Gamescope-mode HTPC from an Unfolded Circle Remote.

Two independently-deployed pieces:

- **`plugin/`** — a [Decky Loader](https://decky.xyz/) plugin that runs on the HTPC itself (SteamOS or Bazzite, in Game Mode). It exposes an HTTP API on the LAN for command execution (key injection, volume, power, app launching) and system sensor readings (CPU/GPU/memory/storage/network/fan/battery), read natively from `/sys` and `/proc` — no LibreHardwareMonitor equivalent needed.
- **`integration/`** — `uc_intg_steamos`, a fork of the upstream integration rebranded and rewired to talk to the new agent's protocol instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor. Runs on the UC Remote itself or in Docker, same as upstream.

See [`docs/protocol.md`](docs/protocol.md) for the wire protocol both sides implement, and [`docs/command-mapping.md`](docs/command-mapping.md) for how each remote-control command maps to a SteamOS/Gamescope mechanism.

## Status

Early scaffold (Phase 0). Development/testing target is a Bazzite HTPC box over SSH — see `docs/hardware-notes.md` once populated.

## License

MIT — see [LICENSE](LICENSE).
