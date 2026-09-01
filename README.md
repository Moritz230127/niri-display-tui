# niri-display-tui

A pure-curses TUI for configuring **niri** multi-monitor layouts: per-screen scale, placement order (left/right/top/bottom), and alignment (top/bottom for horizontal, left/right for vertical). Zero third-party dependencies — stdlib `curses` only.

![interface](https://img.shields.io/badge/interface-curses%20TUI-blue)
![deps](https://img.shields.io/badge/dependencies-none-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

## Features

- **Per-screen scale** — cycle 1.0 / 1.25 / 1.5 / 1.75 / 2.0 with `+` / `-`
- **Placement order** — each screen's position relative to the other: left / right / top / bottom (2-screen model; the other screen auto-syncs to the opposite side)
- **Alignment** — top / bottom for horizontal rows, left / right for vertical columns (auto-synced across screens)
- **Live ASCII preview** — box-drawing layout preview with proper junctions, only connected screens shown
- **Persistent** — writes `monitors.conf` (single source of truth); survives hotplug and config reloads
- **udev hotplug chain** — automatic layout application on monitor connect/disconnect
- **Quick scale keys** — `Mod+Ctrl+Plus/Minus` adjust the focused screen's scale at runtime

## Files

| File | Role |
| --- | --- |
| `niri_display_tui.py` | the TUI (pure curses) |
| `niri_display_geometry.py` | shared geometry: `side/align + logical size → coordinates` (used by TUI and autoconfig) |
| `niri-display-autoconfig.sh` | hotplug auto-config: generates `outputs.kdl` from `monitors.conf` |
| `niri-display-adjust.sh` | quick scale adjustment (keybinding helper) |
| `niri-display-hotplug.sh` | udev entry (root): detach + debounce + runuser |
| `99-niri-display.rules` | udev DRM hotplug rule |
| `monitors.conf.example` | example known-monitor data file |

## Install

```bash
# 1. Copy scripts (adjust paths to your setup)
mkdir -p ~/.config/niri/scripts
cp niri_display_tui.py niri_display_geometry.py ~/.config/niri/scripts/
cp niri-display-autoconfig.sh niri-display-adjust.sh ~/.config/niri/scripts/
chmod +x ~/.config/niri/scripts/niri_display_*.py ~/.config/niri/scripts/niri-display-*.sh

# 2. Known-monitor data file (edit for your monitors)
cp monitors.conf.example ~/.config/niri/monitors.conf

# 3. udev hotplug (optional but recommended)
sudo cp 99-niri-display.rules /etc/udev/rules.d/
sudo cp niri-display-hotplug.sh /usr/local/bin/
sudo udevadm control --reload-rules

# 4. fish alias (launch in the current terminal)
echo 'alias niri-display-tui "~/.config/niri/scripts/niri_display_tui.py"' >> ~/.config/fish/config.fish
```

## Usage

```fish
niri-display-tui          # open the TUI in the current terminal
```

| Key | Action |
| --- | --- |
| `↑` / `↓` | move cursor between fields |
| `←` / `→` | cycle side / align value |
| `+` / `-` | adjust scale |
| `F2` / `a` | apply (write `monitors.conf` + reload niri/noctalia) |
| `F3` / `r` | reset (re-read `monitors.conf`) |
| `q` / `Esc` | quit |

Optional niri keybindings (`~/.config/niri/config.kdl`):

```kdl
binds {
    Mod+Ctrl+Plus  { spawn "~/.config/niri/scripts/niri-display-adjust" "scale" "+0.25"; }
    Mod+Ctrl+Minus { spawn "~/.config/niri/scripts/niri-display-adjust" "scale" "-0.25"; }
}
```

## Configuration

`monitors.conf` — one line per known monitor:

```text
# name|mode|scale|vrr|side|align
eDP-1|2560x1600@165.040|1.5|on|left|top
DP-1|2560x1440@60.000|1.25||right|top
```

- `side`: `left` / `right` / `top` / `bottom` — this screen's position relative to the other
- `align`: `top` / `bottom` (horizontal), `left` / `right` (vertical) — alignment
- Positions are **computed** from side/align + logical sizes (physical ÷ scale), never stored — no overlap when scale changes

Unknown (new) screens are auto-enabled with `mode auto / scale auto / position auto`; add them to `monitors.conf` via the TUI for custom settings.

## How it works

```
DRM hotplug event
  → udev rule (99-niri-display.rules)
  → niri-display-hotplug.sh (root, detach + 1.5s debounce + runuser)
  → niri-display-autoconfig.sh
      → niri_display_geometry.py --positions (side/align → coordinates)
      → generate outputs.kdl (atomic write + backup)
      → niri msg action load-config-file
      → noctalia msg config-reload
```

## Requirements

- niri (Wayland compositor) — tested on 26.04
- Python 3 (stdlib only)
- `jq` (for the shell scripts)
- Optional: noctalia (for wallpaper/lockscreen sync)

## License

MIT
