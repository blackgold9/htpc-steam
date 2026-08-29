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

Optional auth: if `auth_token` is configured (non-empty), requests must carry a matching `X-UC-Token` header or receive `401`. Off by default. See "Auth posture" below for what that does and does not buy you.

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

### `GET /games`

```json
{
  "games": [
    {"appid": 1686940, "name": "Bopl Battle", "last_played": 1787507429}
  ]
}
```

Recently-played, currently-installed games, most recent first (`last_played` is a Unix epoch). Built from `localconfig.vdf` cross-referenced with `appmanifest_*.acf` (`plugin/py_modules/uc_steamos_agent/games/library.py`) — see `docs/hardware-notes.md` for why that source was chosen over the appmanifest's own (stale) `LastPlayed` field, and how compat tools (Proton, Steam Linux Runtime) get filtered out. `404` if the desktop user's home directory couldn't be resolved. To launch one, send `launch_game:<appid>` to `POST /command` (`docs/command-mapping.md`). Status: Phase 5, live-verified.

## Auth posture

LAN-trust by default, matching upstream's zero-config model: no token configured means no authentication, and setup stays zero-friction. When `auth_token` is set, every endpoint requires the header — not just `/command` — since `/games` discloses the user's library and `/sensors` their hardware. The check is a constant-time compare and runs before routing, so an unauthenticated caller can't enumerate which endpoints exist.

**This is plaintext HTTP, so the token is an authorization control, not a confidentiality one.** It is worth being precise about the difference, because the token is easy to over-trust:

What it does stop:
- Unauthenticated LAN peers that can reach port 8086 but can't observe traffic — the realistic case, since switched networks don't flood unicast. An IoT gadget, a housemate's laptop, or a compromised smart TV port-scanning the subnet and firing `power_shutdown` at anything that answers.
- Malicious web pages doing DNS rebinding. A browser can send a cross-origin `POST` with `Content-Type: text/plain` and a JSON body as a *simple request* with no preflight, and this server ignores Content-Type — so without a token that request executes. Requiring a custom `X-UC-Token` header forces a CORS preflight, which this server doesn't answer, so the request never fires.

What it does **not** stop:
- A passive sniffer. The token is cleartext in every request — anyone on a shared medium, holding the Wi-Fi PSK, or sitting on a compromised router/ARP-spoofed path can read it and replay it.
- Any tampering or replay in general. There's no integrity or nonce.

TLS was considered and rejected: with no CA story for a LAN appliance, it means self-signed certs plus either cert pinning in the integration or disabled verification — encryption without authentication, at real setup cost, against a threat model (a sniffer already inside your LAN) that this project doesn't claim to defend. The honest posture is a token that raises the bar against the scanning/rebinding class of attack, documented as exactly that.

Known gap: there's no `Host`-header check, so a DNS-rebinding attack still works against a *token-less* agent. If you run without a token, treat port 8086 as fully open to anything that can route to it.
