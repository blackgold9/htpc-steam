"""Wake-on-LAN status (and optional arming) for the NIC the box routes through.

Why this lives in the agent: the useful diagnostic here — whether a magic
packet will actually wake this box — needs root on a stock SteamOS/Bazzite
install (`ethtool -s <iface> wol g`), and Decky runs this plugin with `_root`.
The integration runs on the Remote and can only ever ask; making the agent
report its own arming state is what lets the Remote show "your NIC is not
armed, WoL will not work" instead of a Power On button that silently does
nothing.

Two independent gates have to be open, which is why both are reported:

    enabled      the NIC's magic-packet filter is armed (`Wake-on: g`)
    may_wakeup   the kernel keeps power to the device while suspended
                 (`device/power/wakeup` == "enabled")

`ethtool -s … wol g` sets the first and nothing sets the second on a handheld
that can also wake from lid/power-button, so a box can look armed and still
never wake. Reporting only `enabled` would be the misleading half.

Reading is side-effect-free, so it happens on the sensor tick (cached). Arming
is opt-in: `wol_arm` in config.json defaults to false, because flipping a
NIC-wide power setting the user didn't ask for is not something a monitoring
plugin should do quietly.

Persistence caveat the integration should surface rather than hide: the Wake-on
flag is RAM state on most drivers, so anything that reloads the driver (kernel
update, NetworkManager re-creating the link, firmware update) clears it back to
the driver default. That is why `wol_arm` re-applies at plugin start instead of
being a one-time manual step — but it cannot cover a state lost while the box is
off and the plugin isn't running. Only the firmware setting is durable across
that.
"""

import logging
import os
import re
import subprocess
import threading
import time

from ..sensors.network import default_interface

_LOG = logging.getLogger(__name__)

#: `ethtool <iface>` prints both fields indented under the interface header:
#:     Supports Wake-on: pumbg   (what the driver can do at all; empty = none)
#:     Wake-on: g                (what is armed now; "d" means disabled)
#: Whitespace is matched as `[ \t]`, never `\s`: the two fields are on adjacent
#: lines, so a `\s*` before a value would swallow the newline and capture the
#: *next* line's key — `Supports Wake-on:` with an empty value would read as
#: supported_flags "Wake-on:", and as supported if the flag letter ever matched.
_SUPPORTED_RE = re.compile(r"Supports Wake-on:[ \t]*(\S*)")
_CURRENT_RE = re.compile(r"^[ \t]*Wake-on:[ \t]*(\S*)", re.MULTILINE)

_WOL_FLAG = "g"  # magic packet
_STATUS_CACHE_S = 30.0

#: Cache sentinels, so `None` can keep meaning "unreadable" without also being
#: the "never asked" initial value (which would defeat caching the failure).
_NOT_ASKED = object()

_UNREADABLE = object()


def driver_name(iface: str, sys_root: str = "/sys") -> str:
    """Kernel driver bound to the interface, via the sysfs symlink."""
    try:
        return os.path.basename(
            os.readlink(os.path.join(sys_root, "class", "net", iface, "device", "driver"))
        )
    except OSError:
        return ""


def wakeup_enabled(iface: str, sys_root: str = "/sys") -> bool:
    """Whether the kernel treats this device as a wakeup source. See module doc."""
    path = os.path.join(sys_root, "class", "net", iface, "device", "power", "wakeup")
    try:
        with open(path, encoding="ascii") as f:
            return f.read().strip() == "enabled"
    except OSError:
        return False


def parse_ethtool(output: str) -> dict:
    """Extract the Wake-on fields from `ethtool <iface>` output.

    `reported` distinguishes "the driver says it can't do WoL" from "ethtool
    told us nothing", which matters because they are not the same answer: an
    unprivileged `ethtool` on the live test box (r8169) exits 0 and prints a
    full link dump with neither Wake-on line present — reporting that as
    `supported: false` would tell the user their NIC can't do Wake-on-LAN when
    the real cause is that the caller wasn't privileged."""
    supported = _SUPPORTED_RE.search(output)
    current = _CURRENT_RE.search(output)
    supported_flags = supported.group(1) if supported else ""
    wake_on = current.group(1) if current else ""
    if wake_on == "d":
        # "d" is ethtool's word for disabled, not a flag name.
        wake_on = ""
    return {
        "reported": bool(supported) or bool(current),
        "supported": _WOL_FLAG in supported_flags,
        "enabled": _WOL_FLAG in wake_on,
        "supported_flags": supported_flags,
        "wake_on": wake_on,
    }


def read_status(iface: str | None = None, sys_root: str = "/sys") -> dict | None:
    """Current WoL state of the routing interface, or None if unreadable.

    A dict is also returned when the NIC genuinely doesn't support WoL — "not
    supported" is a fact worth showing. None means nothing to go on: no route,
    ethtool failed, or ethtool answered without any Wake-on fields (unprivileged;
    see parse_ethtool). The integration renders None as unknown, never as
    "unsupported".
    """
    iface = iface or default_interface()
    if not iface:
        return None
    try:
        proc = subprocess.run(
            ["ethtool", iface], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as err:
        _LOG.debug("ethtool %s failed: %s", iface, err)
        return None
    if proc.returncode != 0:
        _LOG.debug("ethtool %s exited %s: %s", iface, proc.returncode, proc.stderr.strip())
        return None
    status = parse_ethtool(proc.stdout)
    if not status["reported"]:
        # Exit 0 with no Wake-on lines: ethtool answered about the link but not
        # about wake. That is unknown, and the caller must not render it as
        # "this NIC cannot do Wake-on-LAN".
        _LOG.debug("ethtool %s reported no Wake-on fields (not privileged?)", iface)
        return None
    status["interface"] = iface
    status["driver"] = driver_name(iface, sys_root)
    status["may_wakeup"] = wakeup_enabled(iface, sys_root)
    return status


class WakeOnLanMonitor:
    """Cached `read_status` for the sensor tick, plus opt-in arming.

    The cache exists because the value only changes on a driver reload or an
    explicit arm — not every 2 seconds — and every miss costs a subprocess."""

    def __init__(self, arm: bool = False, cache_s: float = _STATUS_CACHE_S, clock=time.monotonic):
        self._arm = arm
        self._cache_s = cache_s
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: dict | object = _NOT_ASKED
        self._cached_at: float = 0.0

    @property
    def arm_enabled(self) -> bool:
        return self._arm

    def status(self, force: bool = False) -> dict | None:
        now = self._clock()
        with self._lock:
            fresh = self._cached is not _NOT_ASKED and now - self._cached_at < self._cache_s
            cached = self._cached
        if fresh and not force:
            return dict(cached) if isinstance(cached, dict) else None
        status = read_status()
        with self._lock:
            # A failed read is cached too: without ethtool (or with a NIC that
            # isn't up yet) an uncached None means a doomed subprocess on every
            # 2s sensor tick, forever. It is retried once the TTL expires.
            self._cached = status if status else _UNREADABLE
            self._cached_at = now
        return dict(status) if status else None

    def arm(self) -> bool:
        """Set `wol g` on the routing interface. True if the flag took effect.
        Verified by re-reading instead of trusting the exit status: ethtool can
        exit 0 while silently ignoring a flag the driver won't apply."""
        iface = default_interface()
        if not iface:
            _LOG.warning("WoL arm requested but no routing interface exists")
            return False
        try:
            subprocess.run(["ethtool", "-s", iface, "wol", _WOL_FLAG], check=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as err:
            _LOG.warning("Failed to arm Wake-on-LAN on %s: %s", iface, err)
            return False

        status = self.status(force=True)
        if not status or not status.get("enabled"):
            _LOG.warning("Armed Wake-on-LAN on %s but the flag did not take", iface)
            return False
        if not status.get("may_wakeup"):
            # Arming the NIC filter isn't enough on its own; say which half failed
            # rather than reporting success and having the wake not happen.
            _LOG.warning(
                "Wake-on-LAN armed on %s, but the device is not a wakeup source "
                "(/sys/class/net/%s/device/power/wakeup) — it may still not wake",
                iface,
                iface,
            )
        _LOG.info("Wake-on-LAN armed on %s (driver %s)", iface, status.get("driver", "?"))
        return True

    def start(self) -> None:
        """Re-apply the flag if armed, then prime the cache.

        Runs at plugin start, which is exactly when it matters: the plugin
        starts after every boot, so this covers the flag being cleared by the
        reboot itself. Called from a separate thread — arming spawns a
        subprocess and Decky's plugin start must not block on it."""
        if self._arm:
            self.arm()
        self.status()
