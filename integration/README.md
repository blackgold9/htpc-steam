# integration/ — uc_intg_steamos

Fork of [`uc_intg_htpc`](https://github.com/mase1981/uc-intg-htpc) rebranded and rewired to talk to `../plugin/`'s protocol (see `../docs/protocol.md`) instead of Windows' `HTPC_Agent.exe` + LibreHardwareMonitor.

Not yet implemented — this is Phase 3 of the project plan, after the agent's command and sensor collection is working end-to-end. See the file-by-file change list in the plan (or `../docs/protocol.md` + `../docs/command-mapping.md`) for what's ported near-verbatim from upstream (`device.py`, `media_player.py`, `sensor.py`) vs. rewritten (`client.py`, `remote.py`, `driver.json`).
