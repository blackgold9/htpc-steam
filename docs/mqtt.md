# Home Assistant MQTT

The SteamOS agent can expose read-only HTPC and Steam Controller state through
Home Assistant MQTT Discovery. MQTT is disabled by default and does not add any
command topic, button, switch, number, or other writable entity.

## Broker configuration

Open Decky's **UC SteamOS Agent** panel, expand **Home Assistant MQTT**, and set:

- **Enable MQTT**
- broker hostname or LAN address and port
- TLS, username, and password as required by the broker
- state and discovery prefixes (normally `uc-steamos` and `homeassistant`)
- retained-state publication interval

Choose **Save and reconnect**. The plugin validates the values, writes them to
its settings file with mode `0600`, and restarts only its MQTT publisher; Steam
and the HTTP agent remain running. A blank password keeps the saved password.
Use **Clear saved password on Save** to remove it explicitly. The UI reports the
current connection state and last MQTT startup error but never reads the stored
password back from the backend.

For recovery or unattended provisioning, the same values can be edited manually
in `~/homebrew/settings/uc-steamos-agent/config.json` on the tested Bazzite
host. After a QAM save the file is root-owned and mode `0600`, so manual edits
require `sudo`:

```json
{
  "mqtt": {
    "enabled": true,
    "host": "homeassistant.local",
    "port": 1883,
    "username": "uc-steamos-agent",
    "password": "replace-with-the-broker-password",
    "tls": false,
    "topic_prefix": "uc-steamos",
    "discovery_prefix": "homeassistant",
    "publish_interval_s": 5.0
  }
}
```

Restart the plugin after editing the file. The agent stores `config.json` with
mode `0600`. It never logs the broker password. **If `username` or `password` is
set while `tls` is `false`, those credentials cross the network in cleartext.**
Enable TLS (normally on port 8883) whenever the broker is not reached over a
fully trusted, isolated network.

`agent_id` is generated and persisted automatically. It provides stable MQTT
client, discovery, device, and entity identifiers even when the HTPC address
changes. Do not copy one HTPC's `agent_id` to another HTPC.

## Read-only contract

The agent publishes and only subscribes to Home Assistant's discovery birth
topic. It does **not** subscribe to an agent command topic. MQTT cannot invoke
uinput, volume, game launch, process termination, suspend, restart, or shutdown.
The existing authenticated HTTP command API is unchanged.

Suggested Mosquitto ACL, substituting the persisted `agent_id`:

```text
user uc-steamos-agent
topic write uc-steamos/<agent_id>/#
topic write homeassistant/device/uc_steamos_<agent_id>/config
topic write homeassistant/device/uc_steamos_<agent_id>_puck/config
topic read homeassistant/status
```

## Topics and retention

| Topic | QoS | Retained | Purpose |
|---|---:|---:|---|
| `uc-steamos/<agent_id>/availability` | 1 | yes | Agent birth and last will |
| `uc-steamos/<agent_id>/system/state` | 1 | yes | Hardware, WoL, agent, and game-count state |
| `uc-steamos/<agent_id>/games/state` | 1 | yes | Raw recent installed-games list |
| `uc-steamos/<agent_id>/puck/availability` | 1 | yes | Puck connection availability |
| `uc-steamos/<agent_id>/puck/state` | 1 | yes | Dock, battery, charge, and diagnostics |
| `uc-steamos/<agent_id>/puck/event` | 0 | **no** | Immediate and confirmed pickup events |
| `homeassistant/device/.../config` | 1 | yes | MQTT device discovery |

The agent republishes discovery and all retained state after connecting and when
Home Assistant publishes its `online` birth message to
`<discovery_prefix>/status`. It also reconciles optional battery and fan
components as the sensor set changes, without republishing unchanged discovery.

## Devices and entities

Discovery creates two linked devices:

- **SteamOS Agent** — CPU/GPU temperature and utilization, memory, storage,
  network rates, Wake-on-LAN state, optional system battery, fan RPM,
  recent-game count, uinput diagnostics, and version.
- **Steam Controller Puck** — connected, docked, battery, charge state, pickup
  event, and disabled-by-default diagnostic counters.

Fast-changing or niche values such as clocks, power, totals, fan RPM, and puck
counters are diagnostic entities disabled by default. The complete games array
is available on the raw MQTT topic rather than as entity attributes, avoiding
Home Assistant recorder churn.

## Pickup events

`puck/event` carries non-retained, QoS 0 JSON. QoS 0 is intentional: an event
that races with a broker disconnect is dropped rather than retained in the
client's outgoing queue and replayed as a stale physical action after reconnect:

```json
{
  "event_type": "pickup_candidate",
  "boot_id": "<boot-id>",
  "sequence": 1,
  "event_id": "<boot-id>:1",
  "timestamp": 1789831635.981,
  "battery_percent": 54
}
```

`pickup_candidate` is emitted immediately after `0x79=01`, but only when the
controller was already known docked. It provides the lowest-latency automation
trigger. `picked_up` follows after the `0x43=01` charge-state confirmation and
includes `confirmation_delay_ms`. `candidate_expired` records a candidate that
was not confirmed inside three seconds.

Home Assistant receives both an event entity and device automation triggers for
`pickup_candidate` and `picked_up`. Use the candidate for idempotent wake or
pre-warm actions; use the confirmed event where a false activation is costly.

Events are deliberately not replayed after broker reconnect. Retained state is
republished, but stale physical actions must not fire later.
