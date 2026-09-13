"""A safe base environment for subprocesses that exec system binaries.

Decky's PyInstaller-frozen loader sets LD_LIBRARY_PATH to its own extraction
temp dir so its bundled shared libraries (libcrypto, libssl, ...) are found
first. Every subprocess this plugin spawns inherits that by default, and a
system binary that dynamically links a library also present in the bundle
(e.g. `systemctl` -> libsystemd-shared -> libcrypto) can pick up the bundled,
version-mismatched copy instead of the system one and fail outright --
confirmed live: `systemctl suspend` errored with
"libcrypto.so.3: version `OPENSSL_3.4.0' not found" until this was stripped.
`ethtool`/`wpctl`/`steam` happen not to hit this today only because they don't
link anything also in the bundle -- that's luck, not a guarantee.
"""

import os


def host_env() -> dict[str, str]:
    """A copy of the current environment safe to hand to a system binary."""
    env = dict(os.environ)
    env.pop("LD_LIBRARY_PATH", None)
    return env
