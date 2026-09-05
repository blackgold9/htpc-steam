import json
import socket
import subprocess
import threading
import urllib.error
import urllib.request

from uc_steamos_agent.commands.dispatcher import CommandExecutionError, Dispatcher
from uc_steamos_agent.config import AgentConfig
from uc_steamos_agent.http import handlers
from uc_steamos_agent.http.server import build_server


class _FakeKeyboard:
    def __init__(self, keycodes):
        self.keycodes = keycodes
        self.presses = []
        self.combos = []

    def press(self, code, hold_s=0.02):
        self.presses.append(code)

    def press_combo(self, *codes, hold_s=0.02):
        self.combos.append(codes)

    def close(self):
        pass


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.status, resp.read()


def _post(url, payload, headers=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    all_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, method="POST", headers=all_headers)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def _running_server(dispatcher=None, sensors_fn=None, games_fn=None, auth_token=""):
    config = AgentConfig(version="0.1.0", host="127.0.0.1", port=0, auth_token=auth_token)
    server = build_server(
        config,
        uinput_available_fn=lambda: True,
        dispatcher=dispatcher or Dispatcher(),
        sensors_fn=sensors_fn,
        games_fn=games_fn,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def test_health_and_status_endpoints():
    server, _ = _running_server()
    port = server.server_address[1]
    try:
        status, body = _get(f"http://127.0.0.1:{port}/health")
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["version"] == "0.1.0"
        assert payload["uinput_available"] is True

        status, body = _get(f"http://127.0.0.1:{port}/status")
        assert status == 200
        assert b"0.1.0" in body

        try:
            _get(f"http://127.0.0.1:{port}/unknown")
            assert False, "expected HTTPError for unknown route"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_command_endpoint_dispatches_to_keyboard():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    server, _ = _running_server(dispatcher)
    port = server.server_address[1]
    try:
        status, body = _post(f"http://127.0.0.1:{port}/command", {"command": "arrow_up"})
        assert status == 200
        assert json.loads(body) == {"status": "ok"}
        assert dispatcher._keyboard.presses == [103]  # KEY_UP

        status, body = _post(f"http://127.0.0.1:{port}/command", {"command": "not_a_real_command"})
        assert status == 400

        status, body = _post(f"http://127.0.0.1:{port}/command", {"nope": "missing command field"})
        assert status == 400

        status, body = _post(f"http://127.0.0.1:{port}/command", None)
        assert status == 400
    finally:
        server.shutdown()
        server.server_close()


def test_sensors_endpoint_serves_the_provided_snapshot():
    fake_snapshot = {"schema_version": 1, "timestamp": 123.4, "cpu": {"temp_c": 39.1}}
    server, _ = _running_server(sensors_fn=lambda: fake_snapshot)
    port = server.server_address[1]
    try:
        status, body = _get(f"http://127.0.0.1:{port}/sensors")
        assert status == 200
        assert json.loads(body) == fake_snapshot
    finally:
        server.shutdown()
        server.server_close()


def test_sensors_endpoint_404s_when_not_wired_up():
    server, _ = _running_server()  # no sensors_fn
    port = server.server_address[1]
    try:
        try:
            _get(f"http://127.0.0.1:{port}/sensors")
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_games_endpoint_serves_the_provided_list():
    fake_games = [{"appid": 1686940, "name": "Bopl Battle", "last_played": 1787507429}]
    server, _ = _running_server(games_fn=lambda: fake_games)
    port = server.server_address[1]
    try:
        status, body = _get(f"http://127.0.0.1:{port}/games")
        assert status == 200
        assert json.loads(body) == {"games": fake_games}
    finally:
        server.shutdown()
        server.server_close()


def test_games_endpoint_404s_when_not_wired_up():
    server, _ = _running_server()  # no games_fn
    port = server.server_address[1]
    try:
        try:
            _get(f"http://127.0.0.1:{port}/games")
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_no_token_configured_means_no_auth_required():
    """The default posture (docs/protocol.md): LAN-trust, zero-friction setup."""
    server, _ = _running_server(games_fn=lambda: [])
    port = server.server_address[1]
    try:
        assert _get(f"http://127.0.0.1:{port}/health")[0] == 200
        assert _get(f"http://127.0.0.1:{port}/games")[0] == 200
        # a bogus token is ignored rather than rejected when none is configured
        assert _get(f"http://127.0.0.1:{port}/health", {"X-UC-Token": "whatever"})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_configured_token_is_required_on_every_endpoint():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    server, _ = _running_server(
        dispatcher, sensors_fn=lambda: {}, games_fn=lambda: [], auth_token="s3cret"
    )
    port = server.server_address[1]
    try:
        for path in ("/health", "/status", "/sensors", "/games"):
            try:
                _get(f"http://127.0.0.1:{port}{path}")
                assert False, f"expected 401 for unauthenticated {path}"
            except urllib.error.HTTPError as err:
                assert err.code == 401, path
                assert json.loads(err.read())["message"] == "unauthorized"

        status, body = _post(f"http://127.0.0.1:{port}/command", {"command": "arrow_up"})
        assert status == 401
        # the command must not have reached the dispatcher
        assert dispatcher._keyboard is None
    finally:
        server.shutdown()
        server.server_close()


def test_wrong_token_is_rejected_and_correct_token_is_accepted():
    dispatcher = Dispatcher(keyboard_factory=_FakeKeyboard)
    server, _ = _running_server(dispatcher, auth_token="s3cret")
    port = server.server_address[1]
    try:
        assert _post(f"http://127.0.0.1:{port}/command", {"command": "arrow_up"},
                     {"X-UC-Token": "wrong"})[0] == 401
        assert dispatcher._keyboard is None

        status, body = _post(f"http://127.0.0.1:{port}/command", {"command": "arrow_up"},
                             {"X-UC-Token": "s3cret"})
        assert status == 200
        assert json.loads(body) == {"status": "ok"}
        assert dispatcher._keyboard.presses == [103]  # KEY_UP

        assert _get(f"http://127.0.0.1:{port}/health", {"X-UC-Token": "s3cret"})[0] == 200
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_route_still_401s_before_404_when_token_configured():
    """Auth runs before routing, so an unauthenticated probe can't enumerate
    which endpoints exist."""
    server, _ = _running_server(auth_token="s3cret")
    port = server.server_address[1]
    try:
        try:
            _get(f"http://127.0.0.1:{port}/unknown")
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as err:
            assert err.code == 401
    finally:
        server.shutdown()
        server.server_close()


class _RaisingDispatcher:
    def __init__(self, exc):
        self._exc = exc

    def dispatch(self, command):
        raise self._exc


def test_handle_command_maps_execution_error_to_409():
    status, _, body = handlers.handle_command(_RaisingDispatcher(CommandExecutionError("no game")), "x")
    assert status == 409
    assert json.loads(body)["message"] == "no game"


def test_handle_command_maps_subprocess_error_to_500():
    """A wpctl/wpctl-adjacent helper exiting non-zero under check=True raises
    subprocess.CalledProcessError, which is NOT an OSError -- it must still be
    caught and returned as a clean 500, not escape and reset the connection."""
    err = subprocess.CalledProcessError(1, ["wpctl"])
    status, _, body = handlers.handle_command(_RaisingDispatcher(err), "volume_up")
    assert status == 500
    assert "status" in json.loads(body)


def test_handle_command_maps_oserror_to_500():
    status, _, _ = handlers.handle_command(_RaisingDispatcher(OSError("no uinput")), "x")
    assert status == 500


def _raw_post(port: int, content_length_header: str, body: bytes = b"") -> int:
    request = (
        b"POST /command HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
        + content_length_header.encode()
        + b"\r\n\r\n"
        + body
    )
    with socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.sendall(request)
        response = sock.recv(4096)
    return int(response.split(b" ", 2)[1])


def test_negative_content_length_is_rejected_without_reading_body():
    server, _ = _running_server()
    port = server.server_address[1]
    try:
        assert _raw_post(port, "Content-Length: -1") == 400
    finally:
        server.shutdown()
        server.server_close()


def test_oversized_content_length_is_rejected_without_buffering():
    """A huge declared length must be refused before rfile.read() so it can't
    drive memory exhaustion on this otherwise-unauthenticated-by-default box."""
    server, _ = _running_server()
    port = server.server_address[1]
    try:
        assert _raw_post(port, "Content-Length: 999999999999") == 413
    finally:
        server.shutdown()
        server.server_close()


def test_malformed_content_length_is_rejected():
    server, _ = _running_server()
    port = server.server_address[1]
    try:
        assert _raw_post(port, "Content-Length: notanumber") == 400
    finally:
        server.shutdown()
        server.server_close()
