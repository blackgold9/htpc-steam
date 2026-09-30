import {
  PanelSection,
  PanelSectionRow,
  Field,
  staticClasses,
} from "@decky/ui";
import { callable, definePlugin } from "@decky/api";
import { useEffect, useState } from "react";
import { FaNetworkWired } from "react-icons/fa";

interface HealthStatus {
  status: string;
  version: string;
  host: string;
  port: number;
  uinput_available: boolean;
}

const getHealth = callable<[], HealthStatus>("get_health");

function Content() {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
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
