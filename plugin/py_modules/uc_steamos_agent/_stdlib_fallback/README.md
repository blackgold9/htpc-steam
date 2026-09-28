# CPython `http.server` / `socketserver` fallback

Decky Loader 3.2.9 is a PyInstaller one-file binary embedding CPython 3.11.7.
Its frozen stdlib has 398 modules: `http`, `http.client`, `http.cookies`,
`http.cookiejar`, `html`, `email`, `urllib` are all present, but
`http.server` and `socketserver` are not, because nothing in Decky itself
imports them. Older Decky builds did bundle them; 3.2.9 dropped them. Our
agent's HTTP API needs both, so on that runtime `from http.server import ...`
raises `ModuleNotFoundError` inside `plugin_loader` and the agent never binds
its port.

`../http/server.py` imports from here only when the running interpreter
genuinely lacks `http.server`, so on a dev box, in CI, and on any Decky that
ships the module again, nothing in this package is imported at all.

## Why these two files, and no others

Only the two names above are missing from the bundle. The 3.11.7
`http/server.py` additionally needs `binascii` and `select` (present in the
bundle's `python3.11/lib-dynload`), `pwd` (a CPython builtin), and
`argparse`, `base64`, `contextlib`, `copy`, `datetime`, `email`, `html`,
`mimetypes`, `shutil`, `socket`, `subprocess`, `urllib`, `selectors`,
`threading`, `quopri` (all in the bundle). Copying `http/client.py`,
`http/cookies.py`, `http/cookiejar.py` or `http/__init__.py` as well would
duplicate code the runtime already has, without fixing anything.

## Why verbatim 3.11.7

Copied unmodified from the matching interpreter (upstream tag `v3.11.7`), so
these bind against the `http.client` / `http.cookies` already inside Decky's
bundle instead of a mismatched patch level. Exactly one deviation exists, in
`http_server.py`: `import socketserver` became `from . import socketserver`,
so the copy resolves to its sibling here rather than a stdlib name.

- `http_server.py` (upstream `Lib/http/server.py`)
  sha256 `d471860df3a8e1264c410d0a7fc092024b2f8ada109f378da50119b81513114e`
  before that one-line deviation; `6d597cbf6b1860fa6d1ecd4dcc2a3e314ce71b8dd66dc0774cefd76dc0985375` as shipped.
- `socketserver.py` (upstream `Lib/socketserver.py`)
  sha256 `a1402df8627949d0b72591e742795fcd48f911172610d4e3c2f16bd7dcae8128`, unmodified.

## Why inside this package instead of `py_modules/`

Two reasons, both about our own correctness. `main.py` prepends `py_modules/` to
`sys.path`, so a top-level `socketserver.py` would shadow the real stdlib module
inside our own plugin process and pin us to this patch level forever, even after
Decky ships a newer CPython. And `py_modules/http/server.py` simply would not
work: the bundle's `http` package resolves from inside the frozen archive with
`__path__` limited to the bundle directory, so a file placed next to it is never
found and `import http.server` keeps failing. Appending to `http.__path__` does
make it resolvable, but that mutates a stdlib package globally to supply one
missing submodule.

Other plugins would be unaffected either way: Decky forks one process per plugin
(`PluginWrapper.start` spawns `Process(target=sandboxed_plugin.initialize, ...)`
and nothing sets a different start method). Keeping the copies private and the
import guarded bounds the blast radius to this plugin and makes the whole thing
self-disabling if upstream restores the modules.

License: Python Software Foundation, see `PYTHON-3.11-LICENSE.txt`.
