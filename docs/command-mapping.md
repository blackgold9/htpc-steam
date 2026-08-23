# Command Mapping

Windows `HTPC_Agent.exe` command vocabulary → SteamOS/Gamescope mechanism implemented by `plugin/py_modules/uc_steamos_agent/commands/dispatcher.py`. Keep this in sync with the dispatcher's alias table. Confidence levels reflect what's been verified on real Bazzite/Gamescope hardware vs. still assumed.

| Category | Windows command(s) | SteamOS mechanism | Confidence |
|---|---|---|---|
| Nav | `arrow_up/down/left/right`, `enter`, `escape`, `back`(→esc), `tab`, `space`, `delete`, `backspace`, `home`, `end`, `page_up/down` | uinput `KEY_*` | **High** — confirmed Gamescope/Big Picture already navigates via arrows/Enter/Escape/Backspace (Valve's own scheme: A=Enter, B=Escape, X=Backspace) |
| Media | `play_pause`, `play`, `pause`, `stop`, `previous`, `next`, `fast_forward`, `rewind`, `record` | uinput `KEY_PLAYPAUSE` etc. | Research spike — unclear anything listens for evdev media keys in Game Mode |
| Volume | `volume_up/down`, `mute`, `mute_toggle`, `set_volume:N` | `wpctl set-volume`/`set-mute @DEFAULT_AUDIO_SINK@ ...` | **High** — PipeWire/wireplumber confirmed standard on SteamOS/Bazzite |
| Gamescope hotkeys | `windows_key` → `steam_home`; new `steam_qam` | Ctrl+1 (Steam button), Ctrl+2 (Quick Access Menu), Ctrl+6 (L3) via uinput combo | **High** — confirmed Gamescope-native combos; supersedes the Meta-key approach |
| Windows Meta shortcuts | `win_r`, `win_d`, `win_l`, `win_i`, `alt_tab`, `ctrl_shift_esc`, `ctrl_alt_del` | **Dropped**: `win_d`/`win_l`/`ctrl_alt_del` — Gamescope's hotkey handler intercepts and discards Left-Windows/Super combos (`LMOD_GUI`) before apps see them. `win_i` → `steam://open/settings`. `alt_tab` kept for Desktop-Mode-only use. | Drop for Meta combos is confirmed (Gamescope bug-tracker discussion); exact `steam://` sub-URI needs a Valve dev-wiki check at implementation time |
| System apps | `custom_calc`, `custom_notepad`, `custom_cmd`, `custom_powershell` | Folded into the shortcuts mechanism instead of 4 fixed buttons; cmd/powershell → attempt `konsole`/`xterm` launch | Research spike — floating utility windows while remaining in Game Mode is unverified |
| Web URLs | `url_youtube`, `url_netflix`, `url_plex`, `url_jellyfin` | Folded into the shortcuts mechanism, seeded with `xdg-open <url>` fallback files | Research spike — `xdg-open` behavior in Game Mode is unverified |
| Power | `power_sleep`, `power_hibernate`, `power_shutdown`, `power_restart` | `systemctl suspend/hibernate/poweroff/reboot` | High, except hibernate — likely unsupported on a typical Deck/handheld swap config, expect-to-fail |
| Wake-on-LAN | `POWER_ON` (remote-entity special command) | Unchanged — client-side WoL, never touches the agent | Same as upstream |
| Bluetooth | `pair_bluetooth`, `show_pairing_help` | `show_pairing_help` ports verbatim (canned text, no OS dependency); `pair_bluetooth` — research spike, may drop | — |
| Launch | `launch_exe:PATH`, `launch_url:URL` | `subprocess.Popen`, `steam <uri>`, or `xdg-open` | Same Game-Mode floating-window uncertainty as System apps |
| Shortcuts | `shortcuts\*.lnk` bare-filename | Plain files under the plugin's settings dir, keyed by name | **Deviation from upstream**: the wire convention changes to `shortcut:<name>` instead of a bare filename, since a bare name was ambiguous against the fixed vocabulary |
| Function keys | `f1`..`f12` | uinput `KEY_F1`..`KEY_F12` verbatim | Trivial |

Rows marked "Research spike" are expected to be resolved (confirmed, adjusted, or dropped) during Phase 4 on-device testing — see the plan's verification checklist.
