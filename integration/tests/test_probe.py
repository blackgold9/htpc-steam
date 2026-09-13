"""Reachability probe classification.

Exercised with real loopback sockets rather than a faked `open_connection`: the
whole point of the module is the difference between the kernel-level outcomes
(accepted / refused / rejected / silent), and mocking the connect would only
prove the code agrees with itself. The errno table is asserted separately
because the "rejected" case can't be produced on loopback.
"""

import errno
import os
import socket

from uc_intg_steamos import probe


def _listen() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    return sock


async def test_open_port_is_agent_up():
    sock = _listen()
    try:
        assert await probe.probe("127.0.0.1", sock.getsockname()[1]) == probe.AGENT_UP
    finally:
        sock.close()


async def test_closed_port_on_a_live_host_is_host_up():
    """A RST means the machine is awake and only the agent is missing — exactly
    the case a magic packet must NOT be sent for."""
    sock = _listen()
    port = sock.getsockname()[1]
    sock.close()
    assert await probe.probe("127.0.0.1", port) == probe.HOST_UP


async def test_unroutable_host_is_no_answer():
    """240.0.0.0/4 is reserved: nothing will answer, the same observable outcome
    as a powered-off box."""
    assert await probe.probe("240.0.0.1", 8086, timeout=0.5) == probe.NO_ANSWER


async def test_unresolvable_host_is_no_answer_not_an_exception():
    """A blank or mistyped host must degrade to an answer. Letting gaierror
    escape is what would strand the box: the exception propagates out of
    establish_connection(), PollingDevice.connect() reads it as "no connection",
    and no poll task is ever created to notice the box coming back."""
    assert await probe.probe("", 8086) == probe.NO_ANSWER
    assert await probe.probe("no.such.host.invalid.", 8086) == probe.NO_ANSWER


def test_errno_table_matches_what_the_live_box_actually_returns():
    """Measured on the live box, whose firewalld answers closed privileged ports
    with EHOSTUNREACH in ~1ms instead of a RST. Silence — the only thing that
    may be read as "asleep" — is a timeout."""
    for code, expected in (
        (errno.ECONNREFUSED, probe.HOST_UP),
        (errno.EHOSTUNREACH, probe.HOST_UP),
        (errno.EACCES, probe.HOST_UP),
        (errno.EHOSTDOWN, probe.NO_ANSWER),
        (errno.ENETUNREACH, probe.NO_ANSWER),
        (errno.ECONNRESET, probe.HOST_UP),
    ):
        err = OSError(code, os.strerror(code))
        err.errno = code
        assert probe.classify_error(err) == expected, errno.errorcode[code]