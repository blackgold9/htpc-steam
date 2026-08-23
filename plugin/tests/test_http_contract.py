import json
import threading
import urllib.error
import urllib.request

from uc_steamos_agent.config import AgentConfig
from uc_steamos_agent.http.server import build_server


def _get(url):
    with urllib.request.urlopen(url, timeout=2) as resp:
        return resp.status, resp.read()


def test_health_and_status_endpoints():
    config = AgentConfig(version="0.1.0", host="127.0.0.1", port=0)
    server = build_server(config, uinput_available_fn=lambda: True)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, body = _get(f"http://127.0.0.1:{actual_port}/health")
        assert status == 200
        payload = json.loads(body)
        assert payload["status"] == "ok"
        assert payload["version"] == "0.1.0"
        assert payload["uinput_available"] is True

        status, body = _get(f"http://127.0.0.1:{actual_port}/status")
        assert status == 200
        assert b"0.1.0" in body

        try:
            _get(f"http://127.0.0.1:{actual_port}/unknown")
            assert False, "expected HTTPError for unknown route"
        except urllib.error.HTTPError as err:
            assert err.code == 404
    finally:
        server.shutdown()
        server.server_close()
