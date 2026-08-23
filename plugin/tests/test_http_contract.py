import json
import threading
import urllib.error
import urllib.request

from uc_steamos_agent.commands.dispatcher import Dispatcher
from uc_steamos_agent.config import AgentConfig
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


def _get(url):
    with urllib.request.urlopen(url, timeout=2) as resp:
        return resp.status, resp.read()


def _post(url, payload):
    data = json.dumps(payload).encode("utf-8") if payload is not None else b""
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.read()


def _running_server(dispatcher=None, sensors_fn=None, games_fn=None):
    config = AgentConfig(version="0.1.0", host="127.0.0.1", port=0)
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
