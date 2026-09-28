import {
  ButtonItem,
  Field,
  PanelSection,
  PanelSectionRow,
  TextField,
  ToggleField,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { FaNetworkWired } from "react-icons/fa";

interface HealthStatus {
  status: string;
  version: string;
  host: string;
  port: number;
  uinput_available: boolean;
}

interface MqttStatus {
  enabled: boolean;
  connected: boolean;
  broker_online: boolean;
  last_error: string | null;
}

interface MqttSettings {
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  password_set: boolean;
  tls: boolean;
  topic_prefix: string;
  discovery_prefix: string;
  publish_interval_s: number;
  status: MqttStatus;
}

interface MqttUpdate {
  enabled: boolean;
  host: string;
  port: number;
  username: string;
  password: string;
  clear_password: boolean;
  tls: boolean;
  topic_prefix: string;
  discovery_prefix: string;
  publish_interval_s: number;
}

interface MqttSaveResult {
  ok: boolean;
  error?: string;
  settings?: MqttSettings;
}

const getHealth = callable<[], HealthStatus>("get_health");
const getMqttSettings = callable<[], MqttSettings>("get_mqtt_settings");
const setMqttSettings = callable<[MqttUpdate], MqttSaveResult>(
  "set_mqtt_settings",
);

function mqttStatusLabel(settings: MqttSettings): string {
  if (!settings.enabled) return "disabled";
  if (settings.status.connected) return "connected";
  return "configured, disconnected";
}

function Content() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [mqtt, setMqtt] = useState<MqttSettings | null>(null);
  const [password, setPassword] = useState("");
  const [clearPassword, setClearPassword] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const statusRequest = useRef(0);
  const pollingPaused = useRef(false);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));

    let active = true;
    const refreshMqttStatus = () => {
      if (pollingPaused.current) return;
      const request = ++statusRequest.current;
      getMqttSettings()
        .then((latest) => {
          if (!active || request !== statusRequest.current) return;
          setMqtt((current) =>
            current
              ? {
                  ...current,
                  password_set: latest.password_set,
                  status: latest.status,
                }
              : latest,
          );
          setError((current) =>
            current === "Could not load MQTT settings." ? "" : current,
          );
        })
        .catch(() => {
          if (active && request === statusRequest.current)
            setError("Could not load MQTT settings.");
        });
    };
    refreshMqttStatus();
    const statusTimer = window.setInterval(refreshMqttStatus, 2000);
    return () => {
      active = false;
      window.clearInterval(statusTimer);
    };
  }, []);

  const updateMqtt = (change: Partial<MqttSettings>) => {
    setMqtt((current) => (current ? { ...current, ...change } : current));
    setMessage("");
    setError("");
  };

  const saveMqtt = async () => {
    if (!mqtt || saving) return;
    pollingPaused.current = true;
    statusRequest.current += 1;
    setSaving(true);
    setMessage("");
    setError("");
    try {
      const result = await setMqttSettings({
        enabled: mqtt.enabled,
        host: mqtt.host.trim(),
        port: mqtt.port,
        username: mqtt.username,
        password,
        clear_password: clearPassword,
        tls: mqtt.tls,
        topic_prefix: mqtt.topic_prefix.trim(),
        discovery_prefix: mqtt.discovery_prefix.trim(),
        publish_interval_s: mqtt.publish_interval_s,
      });
      if (!result.ok || !result.settings) {
        setError(result.error || "Could not save MQTT settings.");
        return;
      }
      setMqtt(result.settings);
      setPassword("");
      setClearPassword(false);
      setMessage(
        result.settings.enabled && !result.settings.status.connected
          ? "Saved; connecting to broker..."
          : "Saved and applied.",
      );
    } catch {
      setError("Could not save MQTT settings.");
    } finally {
      pollingPaused.current = false;
      setSaving(false);
    }
  };

  const credentialsWithoutTls =
    mqtt !== null &&
    !mqtt.tls &&
    (mqtt.username.length > 0 || mqtt.password_set || password.length > 0);

  return (
    <>
      <PanelSection title="UC SteamOS Agent">
        <PanelSectionRow>
          <Field label="Status">{health ? health.status : "loading..."}</Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="Listening on">
            {health ? `${health.host}:${health.port}` : "-"}
          </Field>
        </PanelSectionRow>
        <PanelSectionRow>
          <Field label="uinput access">
            {health ? (health.uinput_available ? "yes" : "no") : "-"}
          </Field>
        </PanelSectionRow>
      </PanelSection>

      <PanelSection title="Home Assistant MQTT">
        {!mqtt ? (
          <PanelSectionRow>
            <Field label="Settings">{error || "loading..."}</Field>
          </PanelSectionRow>
        ) : (
          <>
            <PanelSectionRow>
              <Field label="Connection">{mqttStatusLabel(mqtt)}</Field>
            </PanelSectionRow>
            {mqtt.status.last_error && (
              <PanelSectionRow>
                <Field label="Last error">{mqtt.status.last_error}</Field>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ToggleField
                label="Enable MQTT"
                description="Publishes read-only state and Home Assistant discovery."
                checked={mqtt.enabled}
                onChange={(enabled) => updateMqtt({ enabled })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Broker host"
                description="Hostname or LAN address of the MQTT broker."
                value={mqtt.host}
                onChange={(event) => updateMqtt({ host: event.target.value })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Broker port"
                mustBeNumeric
                value={String(mqtt.port)}
                onChange={(event) =>
                  updateMqtt({ port: Number(event.target.value) })
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Use TLS"
                description="Normally uses port 8883 and the system CA store."
                checked={mqtt.tls}
                onChange={(tls) => updateMqtt({ tls })}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Username"
                value={mqtt.username}
                onChange={(event) =>
                  updateMqtt({ username: event.target.value })
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Password"
                description={
                  clearPassword
                    ? "Saved password will be cleared."
                    : mqtt.password_set
                      ? "A password is saved. Leave blank to keep it."
                      : "No password is saved."
                }
                bIsPassword
                value={password}
                onChange={(event) => {
                  setPassword(event.target.value);
                  setClearPassword(false);
                }}
              />
            </PanelSectionRow>
            {mqtt.password_set && !clearPassword && (
              <PanelSectionRow>
                <ButtonItem
                  layout="below"
                  onClick={() => {
                    setPassword("");
                    setClearPassword(true);
                    setMessage("");
                  }}
                >
                  Clear saved password on Save
                </ButtonItem>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <TextField
                label="State topic prefix"
                value={mqtt.topic_prefix}
                onChange={(event) =>
                  updateMqtt({ topic_prefix: event.target.value })
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Discovery prefix"
                value={mqtt.discovery_prefix}
                onChange={(event) =>
                  updateMqtt({ discovery_prefix: event.target.value })
                }
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <TextField
                label="Publish interval (seconds)"
                mustBeNumeric
                value={String(mqtt.publish_interval_s)}
                onChange={(event) =>
                  updateMqtt({
                    publish_interval_s: Number(event.target.value),
                  })
                }
              />
            </PanelSectionRow>
            {credentialsWithoutTls && (
              <PanelSectionRow>
                <Field label="Security warning">
                  Credentials cross the network in cleartext while TLS is off.
                </Field>
              </PanelSectionRow>
            )}
            {error && (
              <PanelSectionRow>
                <Field label="Error">{error}</Field>
              </PanelSectionRow>
            )}
            {message && (
              <PanelSectionRow>
                <Field label="Result">{message}</Field>
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <ButtonItem
                layout="below"
                disabled={saving}
                onClick={saveMqtt}
              >
                {saving ? "Saving..." : "Save and reconnect"}
              </ButtonItem>
            </PanelSectionRow>
          </>
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  return {
    name: "UC SteamOS Agent",
    titleView: <div className={staticClasses.Title}>UC SteamOS Agent</div>,
    content: <Content />,
    icon: <FaNetworkWired />,
  };
});
