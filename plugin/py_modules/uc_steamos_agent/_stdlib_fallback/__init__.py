"""Byte-exact CPython 3.11.7 copies of `http.server` and `socketserver`.

Decky Loader 3.2.9 freezes CPython 3.11.7 with a 398-module stdlib subset
that omits both of these, so `from http.server import ...` fails inside
plugin_loader and the agent never binds its port. `uc_steamos_agent.http.server`
imports from here only when the running interpreter genuinely lacks
`http.server`, so on a dev box, in CI, and on any Decky that ships the module
again, nothing in this package is imported at all.

Kept inside our own package on purpose. `main.py` prepends `py_modules/` to
`sys.path`, so a file named `socketserver.py` out there would shadow the real
stdlib module inside this plugin's own process; and `py_modules/http/server.py`
would never be found, because the bundle's `http` package has a `__path__` that
points only at the frozen archive. Decky forks one process per plugin, so this is
about being correct for us rather than about protecting other plugins.

See PYTHON-3.11-LICENSE.txt (PSF) and ../README.md for provenance and hashes.
"""
