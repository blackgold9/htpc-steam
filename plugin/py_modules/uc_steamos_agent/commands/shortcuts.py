"""Named shortcuts: plain files under the settings dir, each containing one
command line (a steam:// URI, a web URL, or an executable path) to run.

Wire convention is `shortcut:<name>` (see docs/command-mapping.md) -- this
differs from upstream's bare-filename convention, which was ambiguous
against the fixed command vocabulary.
"""

import os


class ShortcutError(Exception):
    pass


def list_shortcuts(shortcuts_dir: str) -> list[str]:
    try:
        return sorted(f for f in os.listdir(shortcuts_dir) if os.path.isfile(os.path.join(shortcuts_dir, f)))
    except OSError:
        return []


def read_shortcut(shortcuts_dir: str, name: str) -> str:
    if not name or os.sep in name or name in ("..", "."):
        raise ShortcutError(f"invalid shortcut name: {name!r}")
    path = os.path.join(shortcuts_dir, name)
    try:
        with open(path) as f:
            content = f.read().strip()
    except OSError:
        raise ShortcutError(f"no such shortcut: {name!r}") from None
    if not content:
        raise ShortcutError(f"shortcut {name!r} is empty")
    return content


def is_url(content: str) -> bool:
    return content.startswith(("steam://", "http://", "https://"))
