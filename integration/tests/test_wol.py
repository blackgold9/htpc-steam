"""Magic-packet construction and sending.

`send_wol` takes a socket factory rather than having the socket module patched,
so the assertions here are about what would actually go on the wire: the exact
bytes, the exact destinations, and how many times.
"""

import pytest

from uc_intg_steamos import wol


class RecordingSocket:
    def __init__(self, fail_for=()):
        self.sent = []
        self.closed = False
        self._fail_for = set(fail_for)

    def sendto(self, data, addr):
        if addr[0] in self._fail_for:
            raise OSError(101, "Network is unreachable")
        self.sent.append((data, addr))

    def close(self):
        self.closed = True


def _factory(**kwargs):
    made = []

    def create():
        sock = RecordingSocket(**kwargs)
        made.append(sock)
        return sock

    create.made = made
    return create


def test_build_magic_packet_is_sync_stream_plus_sixteen_mac_copies():
    packet = wol.build_magic_packet("aa:bb:cc:dd:ee:ff")
    assert packet == b"\xff" * 6 + bytes.fromhex("aabbccddeeff") * 16
    assert len(packet) == wol.PACKET_SIZE


@pytest.mark.parametrize(
    "raw",
    ["aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aa.bb.cc.dd.ee.ff", "aabbccddeeff"],
)
def test_every_common_mac_spelling_builds_the_same_packet(raw):
    assert wol.build_magic_packet(raw) == wol.build_magic_packet("aa:bb:cc:dd:ee:ff")


@pytest.mark.parametrize("raw", ["aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "not a mac", "", "gg:bb:cc:dd:ee:ff"])
def test_invalid_macs_are_rejected(raw):
    assert wol.validate_mac(raw) is False


def test_mac_bytes_rejects_what_validate_mac_rejects():
    with pytest.raises(ValueError):
        wol.mac_bytes("nope")


def test_send_fires_three_times_at_the_broadcast_by_default():
    """A NIC in a low-power bus state is reported to drop the first frame, so the
    packet is repeated rather than sent once."""
    factory = _factory()
    assert wol.send_wol("aa:bb:cc:dd:ee:ff", delay_s=0, sock_factory=factory) is True
    assert [addr for _, addr in factory.made[0].sent] == [("255.255.255.255", 9)] * 3


def test_send_also_unicasts_to_the_last_known_address():
    """The path that survives networks which drop broadcasts."""
    factory = _factory()
    wol.send_wol("aa:bb:cc:dd:ee:ff", unicast="192.168.1.50", repeats=1, delay_s=0, sock_factory=factory)
    assert [addr for _, addr in factory.made[0].sent] == [("255.255.255.255", 9), ("192.168.1.50", 9)]


def test_broadcast_is_not_sent_twice_when_unicast_is_the_broadcast():
    factory = _factory()
    wol.send_wol("aa:bb:cc:dd:ee:ff", broadcast="255.255.255.255", unicast="255.255.255.255", repeats=1, delay_s=0, sock_factory=factory)
    assert len(factory.made[0].sent) == 1


def test_subnet_broadcast_and_custom_port_are_honoured():
    factory = _factory()
    wol.send_wol(
        "aa:bb:cc:dd:ee:ff",
        broadcast="192.168.1.255",
        port=7,
        repeats=1,
        delay_s=0,
        sock_factory=factory,
    )
    assert [addr for _, addr in factory.made[0].sent] == [("192.168.1.255", 7)]


def test_a_failing_broadcast_does_not_lose_the_unicast_copy():
    factory = _factory(fail_for=["255.255.255.255"])
    assert (
        wol.send_wol("aa:bb:cc:dd:ee:ff", unicast="192.168.1.50", repeats=1, delay_s=0, sock_factory=factory)
        is True
    )
    assert [addr for _, addr in factory.made[0].sent] == [("192.168.1.50", 9)]


def test_no_target_working_reports_failure():
    factory = _factory(fail_for=["255.255.255.255"])
    assert wol.send_wol("aa:bb:cc:dd:ee:ff", repeats=1, delay_s=0, sock_factory=factory) is False


def test_socket_is_closed_even_after_send_errors():
    factory = _factory(fail_for=["255.255.255.255"])
    wol.send_wol("aa:bb:cc:dd:ee:ff", repeats=1, delay_s=0, sock_factory=factory)
    assert factory.made[0].closed is True


def test_unopenable_socket_is_a_clean_failure():
    """Must not raise into the command handler."""

    def boom():
        raise OSError(13, "Permission denied")

    assert wol.send_wol("aa:bb:cc:dd:ee:ff", repeats=1, delay_s=0, sock_factory=boom) is False


async def test_async_wrapper_refuses_a_non_mac_before_touching_the_network():
    assert await wol.wake_on_lan("garbage") is False
