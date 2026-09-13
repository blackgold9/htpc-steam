"""
Magic-packet sender (Wake-on-LAN), integration side.

The asymmetry that puts this file here and not in `plugin/`: the magic packet
has to be sent by something that is *on*, and the whole point of WoL is that
the HTPC — and therefore the agent running on it — is off. The Remote (or the
Docker host, which runs with `network_mode: host`, so a broadcast frame
egresses onto the LAN normally) is the only always-on participant.

The agent's job is the opposite half: arming the NIC to accept a wake while it
is still awake (`plugin/py_modules/uc_steamos_agent/commands/wol.py`).

stdlib only — the packet is 102 bytes and a datagram socket, so the old
`wakeonlan` PyPI dependency is not coming back.

Packet layout (AMD Magic Packet, as dissected by Wireshark and built by
net-tools' `ether-wake`): six 0xFF bytes, then the 6-byte target MAC repeated
16 times. We send it as a UDP payload rather than a raw Ethernet frame
(EtherType 0x0842), which needs no root and is what every consumer tool does;
the NIC scans for the byte pattern and doesn't care about the encapsulation.

:license: MIT
"""

import asyncio
import binascii
import logging
import re
import socket
import time

_LOG = logging.getLogger(__name__)

MAC_RE = re.compile(r"^([0-9a-fA-F]{2}[:.-]?){5}[0-9a-fA-F]{2}$")

#: Sync stream + 16 copies of the target MAC.
PACKET_SIZE = 6 + 6 * 16

#: UDP port conventionally used (Discard); Echo/7 is the other common choice.
DEFAULT_WOL_PORT = 9

#: Limited broadcast — reaches every host on the local segment.
LIMITED_BROADCAST = "255.255.255.255"


def normalize_mac(mac: str) -> str:
    """`aa:bb:cc:dd:ee:ff` / `aa-bb-cc-dd-ee-ff` / `aabbccddeeff` -> lowercase canonical."""
    return binascii.hexlify(mac_bytes(mac)).decode()


def mac_bytes(mac: str) -> bytes:
    """Parse a MAC in any common separator form into 6 raw bytes. Raises ValueError."""
    if not validate_mac(mac):
        raise ValueError(f"not a MAC address: {mac!r}")
    return binascii.unhexlify(re.sub(r"[:.\-]", "", mac.strip()).lower().encode())


def validate_mac(mac: str) -> bool:
    """Accept colon/dot/dash-separated or bare hex, any case. Reject everything else."""
    if not isinstance(mac, str):
        return False
    return bool(MAC_RE.match(mac.strip()))


def build_magic_packet(mac: str) -> bytes:
    """6 x 0xFF followed by the target MAC 16 times (102 bytes)."""
    return b"\xff" * 6 + mac_bytes(mac) * 16


def create_datagram_socket() -> socket.socket:
    """Broadcast-capable UDP socket. Its own function so tests can hand
    `send_wol` a recording fake instead of monkeypatching the socket module."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(2.0)
    return sock


def send_wol(
    mac: str,
    *,
    broadcast: str = LIMITED_BROADCAST,
    port: int = DEFAULT_WOL_PORT,
    unicast: str | None = None,
    repeats: int = 3,
    delay_s: float = 0.4,
    sock_factory=create_datagram_socket,
) -> bool:
    """Fire the magic packet. Blocking — call through asyncio.to_thread().

    Sends to `broadcast`, and additionally to `unicast` (the box's last-known
    address) when given. The unicast copy matters: a NIC with its WoL Rx filter
    armed accepts the magic pattern from a unicast frame too, which is the path
    that survives the managed/segmented networks that quietly drop broadcasts.

    `repeats` exists because a NIC in a low-power bus state is reported to drop
    the first frame; three over ~1s is the usual practice.

    Returns True if at least one datagram left the socket without error. The
    packet being sent is NOT evidence the box woke up — nothing on this side
    can observe that; only the agent answering again is.
    """
    packet = build_magic_packet(mac)
    targets = [broadcast] + ([unicast] if unicast and unicast != broadcast else [])
    sent_any = False

    try:
        sock = sock_factory()
    except OSError as err:
        _LOG.warning("Wake-on-LAN: could not open a UDP socket for %s: %s", mac, err)
        return False

    try:
        for attempt in range(max(1, repeats)):
            for target in targets:
                try:
                    sock.sendto(packet, (target, port))
                    sent_any = True
                except OSError as err:
                    # A missing/unconfigured broadcast route is common and not
                    # fatal: the unicast copy may still land.
                    _LOG.debug("WoL send to %s:%s failed: %s", target, port, err)
            if attempt < repeats - 1 and delay_s > 0:
                time.sleep(delay_s)
    finally:
        sock.close()

    if not sent_any:
        _LOG.warning("Wake-on-LAN: no magic packet could be sent for %s", mac)
    else:
        _LOG.info("Wake-on-LAN: magic packet sent to %s via %s", mac, ", ".join(targets))
    return sent_any


async def wake_on_lan(mac: str, **kwargs) -> bool:
    """Async wrapper: the send is a few blocking syscalls plus sleeps."""
    if not validate_mac(mac):
        _LOG.warning("Wake-on-LAN refused: %r is not a MAC address", mac)
        return False
    return await asyncio.to_thread(send_wol, mac, **kwargs)
