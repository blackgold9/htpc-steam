"""
Off-box reachability probe: is the HTPC awake, or is only the agent gone?

Wake-on-LAN creates a state this integration has never had to model before:
the box exists, has an IP, and simply isn't answering anything. Telling
"powered off" apart from "awake but the agent isn't running" decides whether
Power On should send a magic packet or restart Decky — and neither `/health`'s
status code nor an aiohttp exception carries that distinction (both collapse to
`None`).

A bare TCP connect to the agent's port does, and needs no root. Measured on the
live box rather than assumed — the middle case is not the textbook one:

    connect succeeds   -> AGENT_UP     agent is listening
    ECONNREFUSED       -> HOST_UP      the host itself answered with a RST
    EHOSTUNREACH       -> HOST_UP      a firewall REJECT came back in
                                       ~1ms — from the box's own firewalld
                                       here, from a middlebox elsewhere. NOT
                                       silence: the test box rejects its closed
                                       ports (7, 9) this way while it is awake, so
                                       filing this under "nothing answered"
                                       would call a live box asleep and fire a
                                       pointless wake. It does mean the probe
                                       cannot discriminate on those ports, so
                                       only the agent's own port is probed.
    timeout            -> NO_ANSWER    silence. This is the asleep/powered-off/
                                       unplugged case: an absent host on the
                                       same LAN (measured: 192.168.6.201) and a
                                       reserved address both stay silent until
                                       the deadline rather than replying.
    ENETUNREACH /
    EHOSTDOWN /
    bad hostname       -> NO_ANSWER    no path at all — a misconfigured host
                                       field, a link-down interface. Nothing was
                                       contacted, so nothing can be concluded.

HOST_UP therefore means "something answered and the agent isn't on the port",
which is the actionable half: don't wake, look at Decky. When a network rejects
every closed port, that reading can be over-optimistic about a box that is
actually off — but that is the safe direction of error (no bogus wake, and the
user is pointed at the agent rather than at a power button).

:license: MIT
"""

import asyncio
import errno
import logging
import socket

_LOG = logging.getLogger(__name__)

#: Something answered on the far end; the agent just isn't listening.
HOST_UP = "host_up"
#: A socket was actually accepted on the agent's port.
AGENT_UP = "agent_up"
#: Nothing answered — asleep, powered off, unplugged, or no route to it.
NO_ANSWER = "no_answer"

#: Errors meaning something answered. ECONNREFUSED is the host's own RST and
#: ECONNRESET a peer that hung up; EHOSTUNREACH/EACCES are normally an ICMP
#: "prohibited"/"admin prohibited" coming back from a firewall — from a middlebox
#: rather than the host, but still proof the network path is live and something
#: is actively refusing rather than sitting silent.
_ANSWERING_ERRORS = frozenset(
    {errno.ECONNREFUSED, errno.ECONNRESET, errno.EHOSTUNREACH, errno.EACCES, errno.EPERM}
)

def classify_error(err: OSError) -> str:
    """One probe outcome, factored out so the errno table is directly testable.

    gaierror (a name that won't resolve) carries no meaningful errno, so it
    falls through to NO_ANSWER with the rest of the "never got anywhere" family.
    """
    return HOST_UP if err.errno in _ANSWERING_ERRORS else NO_ANSWER


async def probe(host: str, port: int, timeout: float = 1.5) -> str:
    """Classify `host` as AGENT_UP / HOST_UP / NO_ANSWER.

    Never raises: every failure mode is a legitimate answer about a box we
    expect to be switched off half the time. A raised exception here would
    escape establish_connection() and cost the device its poll task.
    """
    try:
        _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except asyncio.TimeoutError:
        return NO_ANSWER
    except (ConnectionRefusedError, ConnectionResetError):
        return HOST_UP
    except OSError as err:
        result = classify_error(err)
        _LOG.debug("Probe of %s:%s -> %s (%s)", host, port, result, err)
        return result
    except (ValueError, UnicodeError) as err:
        # Empty/unparseable host. Not an answer about the box at all.
        _LOG.debug("Probe of %r:%s failed before connecting: %s", host, port, err)
        return NO_ANSWER

    writer.close()
    try:
        await writer.wait_closed()
    except (OSError, asyncio.TimeoutError):  # pragma: no cover - best effort
        pass
    return AGENT_UP
