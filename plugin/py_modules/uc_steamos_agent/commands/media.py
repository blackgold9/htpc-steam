"""wpctl (WirePlumber) volume/mute wrappers.

@DEFAULT_AUDIO_SINK@ is wpctl's built-in alias for the current default
output, avoiding a separate lookup for a numeric sink ID.
"""

import subprocess

_SINK = "@DEFAULT_AUDIO_SINK@"

SIMPLE_COMMANDS = {
    "volume_up": ["wpctl", "set-volume", _SINK, "5%+"],
    "volume_down": ["wpctl", "set-volume", _SINK, "5%-"],
    "mute": ["wpctl", "set-mute", _SINK, "toggle"],
    "mute_toggle": ["wpctl", "set-mute", _SINK, "toggle"],
}


def set_volume_argv(percent: int) -> list[str]:
    return ["wpctl", "set-volume", _SINK, f"{percent}%"]


def execute(argv: list[str], env: dict | None = None) -> None:
    subprocess.run(argv, check=True, timeout=5, env=env)
