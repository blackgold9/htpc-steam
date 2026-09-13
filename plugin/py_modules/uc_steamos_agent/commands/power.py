"""systemctl power-management wrappers.

The plugin runs as root (Decky's `root` plugin.json flag), so these calls need no
polkit interactive authentication — root is inherently authorized for
systemd-managed power actions, unlike an unprivileged SSH session.
"""

import subprocess

from ..subprocess_env import host_env

POWER_COMMANDS = {
    "power_sleep": ["systemctl", "suspend"],
    "power_hibernate": ["systemctl", "hibernate"],
    "power_shutdown": ["systemctl", "poweroff"],
    "power_restart": ["systemctl", "reboot"],
}


def execute(command: str) -> None:
    """Run the systemctl action for `command`. Raises on failure."""
    subprocess.run(POWER_COMMANDS[command], check=True, timeout=10, env=host_env())
