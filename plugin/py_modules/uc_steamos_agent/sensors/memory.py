"""Memory sensors via /proc/meminfo, using MemAvailable (not MemFree) for
the "used" calculation — MemFree undercounts usable memory since it
excludes reclaimable cache/buffers.
"""


def _parse_meminfo(proc_root: str = "/proc") -> dict[str, float]:
    values = {}
    try:
        with open(f"{proc_root}/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                rest = rest.strip()
                if rest.endswith("kB"):
                    try:
                        values[key] = float(rest[:-2].strip())
                    except ValueError:
                        pass
    except OSError:
        pass
    return values


def read_used_total_gb(proc_root: str = "/proc") -> tuple[float | None, float | None]:
    values = _parse_meminfo(proc_root)
    total_kb = values.get("MemTotal")
    available_kb = values.get("MemAvailable")
    if total_kb is None:
        return None, None
    total_gb = total_kb / (1024 * 1024)
    if available_kb is None:
        return None, total_gb
    used_gb = (total_kb - available_kb) / (1024 * 1024)
    return used_gb, total_gb
