"""Decky Loader 3.2.9's frozen Python has no http.server / socketserver.

The agent must still start there. These tests emulate that interpreter by
hiding both stdlib modules and driving the real `build_server`, so a future
edit that breaks the fallback fails here instead of bricking a Decky install.
"""

import hashlib
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PY_MODULES = PLUGIN_ROOT / "py_modules"
FALLBACK = PY_MODULES / "uc_steamos_agent" / "_stdlib_fallback"

# Installed in the child before our package is imported: claims the blocked
# stdlib names so nothing else can satisfy them, exactly as a PyInstaller
# bundle that omitted them would.
_HIDE_STDLIB = """
import sys

BLOCKED = {"http.server", "socketserver"}


class _Hider:
    def find_spec(self, name, path=None, target=None):
        if name in BLOCKED:
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None


for _mod in [n for n in sys.modules if n in BLOCKED or n.startswith("http.server")]:
    del sys.modules[_mod]
sys.meta_path.insert(0, _Hider())
"""


def _run_hidden(child_body: str) -> str:
    # PYTHONPATH mirrors main.py on the device, which prepends py_modules.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PY_MODULES))
    result = subprocess.run(
        [sys.executable, "-c", _HIDE_STDLIB + textwrap.dedent(child_body)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PLUGIN_ROOT),
        timeout=90,
    )
    assert result.returncode == 0, f"child failed:\n{result.stdout}\n{result.stderr}"
    return result.stdout


def test_hiding_stdlib_actually_breaks_plain_http_server_import():
    """Guard: if this fails the emulation is inert and the tests below prove nothing."""
    body = """
    try:
        import http.server
    except ModuleNotFoundError as exc:
        print("hidden:", exc.name)
    else:
        print("VISIBLE", http.server.__file__)
    """
    assert _run_hidden(body).strip() == "hidden: http.server"


def test_agent_server_starts_and_serves_without_stdlib_http_server():
    """The shipped path: no http.server, no socketserver, agent still answers."""
    body = """
    import json
    import threading
    import urllib.error
    import urllib.request

    import uc_steamos_agent.http.server as server_mod
    from uc_steamos_agent.config import AgentConfig

    assert "http.server" not in __import__("sys").modules
    origin = server_mod.ThreadingHTTPServer.__module__
    print("handler_origin:", origin)

    config = AgentConfig(host="127.0.0.1", port=0, auth_token="s3cret")
    httpd = server_mod.build_server(
        config, lambda: True, lambda command, payload: (400, "text/plain", b"unused")
    )
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def get(token=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
        if token:
            req.add_header("X-UC-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as err:
            return err.code, None

    print("no_token:", get()[0])
    print("bad_token:", get("nope")[0])
    status, payload = get("s3cret")
    print("with_token:", status)
    print("health_ok:", payload["status"] if payload else None)
    httpd.shutdown()
    httpd.server_close()
    """
    out = dict(
        line.split(": ", 1) for line in _run_hidden(body).strip().splitlines() if ": " in line
    )
    assert out["handler_origin"].startswith("uc_steamos_agent._stdlib_fallback")
    assert out["no_token"] == "401", "auth must still be enforced via the fallback"
    assert out["bad_token"] == "401"
    assert out["with_token"] == "200"
    assert out["health_ok"] == "ok"


def test_fallback_is_inert_when_the_runtime_has_http_server():
    """On a healthy interpreter nothing under _stdlib_fallback may load."""
    body = """
    import sys
    import uc_steamos_agent.http.server  # noqa: F401
    loaded = sorted(m for m in sys.modules if "_stdlib_fallback" in m)
    print("loaded:", loaded)
    print("stdlib:", sys.modules["http.server"].__file__)
    """
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        capture_output=True,
        text=True,
        cwd=str(PLUGIN_ROOT),
        timeout=90,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(PY_MODULES)),
    )
    assert result.returncode == 0, result.stderr
    assert "loaded: []" in result.stdout
    assert "_stdlib_fallback" not in result.stdout


@pytest.mark.parametrize(
    "name",
    ["__init__.py", "http_server.py", "socketserver.py", "PYTHON-3.11-LICENSE.txt"],
)
def test_fallback_ships_every_file_it_needs(name: str) -> None:
    path = FALLBACK / name
    assert path.is_file() and path.stat().st_size > 0


def test_no_stdlib_named_files_at_py_modules_root():
    """`main.py` prepends py_modules to sys.path, so a top-level
    `socketserver.py` or `http/` here would shadow the real stdlib inside our own
    plugin process and pin us to the vendored patch level forever. (Decky forks a
    process per plugin, so other plugins would be unaffected -- this guards us.)"""
    names = {p.name for p in PY_MODULES.iterdir()}
    assert "http" not in names
    assert "socketserver.py" not in names


def test_vendored_copies_are_verbatim_cpython_3_11_7():
    """Provenance, not a tautology: undoing the single documented deviation in
    `http_server.py` must reproduce upstream's published sha256, and
    `socketserver.py` must be untouched. Catches silent edits to 2100+ lines of
    code we don't normally read."""
    shipped = (FALLBACK / "http_server.py").read_text(encoding="utf-8")
    patched = (
        "import socket # For gethostbyaddr()\n"
        "# Vendored deviation (the only one): our socketserver copy is a sibling in this\n"
        "# package, not the stdlib module (which Decky 3.2.9's bundle omits anyway).\n"
        "from . import socketserver\n"
    )
    assert shipped.count(patched) == 1, "the one documented deviation changed shape"
    pristine = shipped.replace(patched, "import socket # For gethostbyaddr()\nimport socketserver\n")
    assert hashlib.sha256(pristine.encode("utf-8")).hexdigest() == (
        "d471860df3a8e1264c410d0a7fc092024b2f8ada109f378da50119b81513114e"
    ), "http_server.py is no longer byte-exact CPython 3.11.7 plus one line"
    socketserver_bytes = (FALLBACK / "socketserver.py").read_bytes()
    assert hashlib.sha256(socketserver_bytes).hexdigest() == (
        "a1402df8627949d0b72591e742795fcd48f911172610d4e3c2f16bd7dcae8128"
    ), "socketserver.py is no longer byte-exact CPython 3.11.7"

