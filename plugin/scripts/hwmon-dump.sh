#!/usr/bin/env bash
# Dumps hwmon/power_supply/amdgpu sysfs ground truth for docs/hardware-notes.md.
# Run over SSH on the target box: ssh deck@host 'bash -s' < scripts/hwmon-dump.sh
set -euo pipefail

echo "## hwmon-dump: $(date -u +%FT%TZ)"
echo "## host: $(hostname), kernel: $(uname -r)"
echo

for hw in /sys/class/hwmon/hwmon*; do
  [ -d "$hw" ] || continue
  name="(unnamed)"
  [ -r "$hw/name" ] && name="$(cat "$hw/name")"
  echo "=== $hw  [name: $name] ==="
  for entry in "$hw"/*; do
    base="$(basename "$entry")"
    case "$base" in
      *_input|*_label|*_max|*_crit)
        if [ -r "$entry" ]; then
          printf '  %-24s %s\n' "$base" "$(cat "$entry" 2>/dev/null || echo '?')"
        fi
        ;;
    esac
  done
  echo
done

echo "## power_supply (battery):"
for ps in /sys/class/power_supply/*; do
  [ -d "$ps" ] || continue
  echo "=== $ps ==="
  for f in type status capacity power_now energy_now; do
    [ -r "$ps/$f" ] && printf '  %-12s %s\n' "$f" "$(cat "$ps/$f")"
  done
done
echo

echo "## amdgpu busy percent (if present):"
for card in /sys/class/drm/card*/device; do
  [ -r "$card/gpu_busy_percent" ] && echo "$card/gpu_busy_percent = $(cat "$card/gpu_busy_percent")"
done

echo
echo "## default route interface (for network sensor auto-detect):"
ip route show default 2>/dev/null || route -n 2>/dev/null || true
