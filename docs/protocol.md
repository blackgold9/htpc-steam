# Wire Protocol

Source of truth for the HTTP contract between `plugin/` (runs on the HTPC) and `integration/` (runs on the UC Remote or in Docker). Keep this in sync with `plugin/py_modules/uc_steamos_agent/http/handlers.py` and `integration/src/uc_intg_steamos/client.py`.

One port, default **8086** (configurable), single HTTP server — unlike upstream's split between the Windows agent (8086) and LibreHardwareMonitor (8085), since one process now owns both commands and sensors.

## Endpoints

### `GET /health`

```json
{"status": "ok", "version": "0.1.0", "uptime_s": 123.4, "uinput_available": true}
```

`uinput_available` lets the integration surface degraded key-injection mode without waiting for a failed `/command` call. Status implemented: Phase 0.

### `GET /status`

Human-readable plain text page, for browser/SSH debugging. Not consumed by the integration. Status: Phase 0.

### `POST /command`

Request: `{"command": "<string>"}`. Response: `200 {"status": "ok"}` or `4xx {"status": "error", "message": "..."}`.

For `power_*` commands, the server responds `200` first and executes the `systemctl`/`loginctl` call ~150-300ms later on a background thread, since the host may go offline before a synchronous response could be sent. Status: Phase 1-2 (command vocabulary), see `docs/command-mapping.md`.

Optional auth: if `auth_token` is configured (non-empty), requests must carry a matching `X-UC-Token` header or receive `401`. Off by default.

### `GET /sensors`

```json
{
  "schema_version": 1,
  "timestamp": 0,
  "cpu": {"name": "", "temp_c": null, "load_pct": null, "clock_mhz": null, "power_w": null},
  "gpu": {"name": "", "temp_c": null, "load_pct": null, "has_dedicated_gpu": false},
  "memory": {"used_gb": 0, "total_gb": 0},
  "storage": {"used_gb": 0, "total_gb": 0, "used_pct": 0, "temp_c": null},
  "network": {"up_kbps": 0, "down_kbps": 0},
  "motherboard": {"temp_avg_c": null, "temp_max_c": null},
  "fans": [{"label": "", "rpm": 0}],
  "battery": {"present": false, "percent": null, "charging": null, "power_w": null}
}
```

Unavailable sensors are `null`, not `0`, so the integration can mark an entity unavailable instead of showing a false zero. Temperature is Celsius on the wire; unit conversion (°C/°F) is a display-layer concern in the integration. `battery` has no upstream (Windows) equivalent — desktop HTPCs have no battery. Status: Phase 3.

### `GET /shortcuts`

Lists configured shortcut names (see `docs/command-mapping.md` for the `shortcut:<name>` command convention). Optional, cheap. Status: Phase 4.

## Auth posture

LAN-trust by default, matching upstream's zero-config model. The optional `X-UC-Token` header exists because a portable HTPC is more likely to join untrusted networks than a stationary Windows box, and the command vocabulary includes shutdown/reboot/exec — but it must stay strictly optional so setup stays zero-friction for users who don't want it.
