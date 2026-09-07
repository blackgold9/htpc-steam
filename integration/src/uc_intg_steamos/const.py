"""
Constants for the SteamOS HTPC Remote integration.

:license: MIT
"""

POLL_INTERVAL = 5
AGENT_PORT = 8086

MONITORING_VIEWS = [
    "System Overview",
    "CPU Performance",
    "GPU Performance",
    "Memory Usage",
    "Storage Activity",
    "Network Activity",
    "Temperature Overview",
    "Fan Monitoring",
    "Power Consumption",
    "Battery",
    # WoL arming state, straight from the agent (root can read what the user
    # can't: `ethtool` refuses Wake-on info to unprivileged callers).
    "Wake-on-LAN",
]
