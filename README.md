# niri-display-tui

A **Textual**-based TUI for configuring **niri** multi-monitor layouts.  
It supports vim-style navigation and Chinese/English commands, live connected-screen monitoring, and an always-visible ASCII layout preview.

![interface](https://img.shields.io/badge/interface-Textual%20TUI-blue)
![deps](https://img.shields.io/badge/dependencies-textual-brightgreen)
![license](https://img.shields.io/badge/license-MIT-green)

## Features

- **Live connected screens only** — automatically detects monitor hotplug/connect changes; does not show or record disconnected screens
- **Vim-style interaction** — `j/k` move, `Enter` select, `h/l` change value, `:` opens command mode
- **Chinese/English commands** — e.g. `:分辨率 2560x1440@60`, `:缩放 1.25`, `:位置 left`, `:保存`
- **Per-screen settings** — mode / scale / VRR / side / align / transform / power
- **Always-visible ASCII preview** — shows the current connected layout
- **Persistent** — writes `monitors.conf` (single source of truth); survives hotplug and config reloads
- **udev hotplug chain** — automatic layout application on monitor connect/disconnect
- **Quick scale keys** — `Mod+Ctrl+Plus/Minus` adjust the focused screen's scale at runtime

## Files

| File | Role |
| --- | --- |
| `niri_display_tui.py` | the TUI (Textual, vim-style + Chinese command mode) |
| `niri_display_geometry.py` | shared geometry: `side/align + logical size → coordinates` (used by TUI and autoconfig) |
| `niri-display-autoconfig.sh` | hotplug auto-config: generates `outputs.kdl` from `monitors.conf` |
| `niri-display-adjust.sh` | quick scale adjustment (keybinding helper) |
| `niri-display-hotplug.sh` | udev entry (root): detach + debounce + runuser |
| `99-niri-display.rules` | udev DRM hotplug rule |
| `monitors.conf.example` | example known-monitor data file |

## Install

```bash
# 1. Install Textual (Python dependency)
pip install --user textual

# 2. Copy scripts (adjust paths to your setup)
mkdir -p ~/.config/niri/scripts
cp niri_display_tui.py niri_display_geometry.py ~/.config/niri/scripts/
cp niri-display-autoconfig.sh niri-display-adjust.sh ~/.config/niri/scripts/
chmod +x ~/.config/niri/scripts/niri_display_*.py ~/.config/niri/scripts/niri-display-*.sh

# 3. Known-monitor data file (edit for your monitors)
cp monitors.conf.example ~/.config/niri/monitors.conf

# 4. udev hotplug (optional but recommended)
sudo cp 99-niri-display.rules /etc/udev/rules.d/
sudo cp niri-display-hotplug.sh /usr/local/bin/
sudo udevadm control --reload-rules

# 5. fish alias (launch in the current terminal)
echo 'alias niri-display-tui "~/.config/niri/scripts/niri_display_tui.py"' >> ~/.config/fish/config.fish
```

## Usage

```fish
niri-display-tui          # open the TUI in the current terminal
```

### Normal mode

| Key | Action |
| --- | --- |
| `j` / `k` | move in screen list / switch parameter |
| `Enter` | select the highlighted screen |
| `h` / `l` | change current parameter value |
| `:` | open command mode |
| `Esc` | return to screen list / cancel command |
| `F2` | save + apply (write `monitors.conf` + run autoconfig) |
| `F3` | discard draft and reload |
| `F4` | apply temporarily to the running niri session |
| `Q` | quit |

### Command mode

Press `:` and type a command, for example:

```text
:分辨率 2560x1440@60
:分辨率
:缩放 1.25
:位置 left
:对齐 top
:变换 normal
:电源 on
:应用
:保存
:放弃
:退出
:帮助
```

English aliases are also accepted: `:mode`, `:scale`, `:side`, `:align`, `:transform`, `:power`, `:apply`, `:save`, `:quit`.

## Configuration

`monitors.conf` — one line per known monitor:

```text
# name|mode|scale|vrr|side|align|transform|enabled
eDP-1|2560x1600@165.040|1.5|on|left|top|normal|on
DP-1|2560x1440@60.000|1.25||right|top|normal|on
```

- `side`: `left` / `right` / `top` / `bottom` — this screen's position relative to the other
- `align`: `top` / `bottom` (horizontal), `left` / `right` (vertical) — alignment
- `transform`: `normal` / `90` / `180` / `270` / `flipped` / `flipped-90` / `flipped-180` / `flipped-270`
- `enabled`: `on` / `off`
- Positions are **computed** from side/align + logical sizes (physical ÷ scale), never stored — no overlap when scale changes

Unknown (new) screens are auto-enabled with `mode auto / scale auto / position auto`; the TUI only manages currently connected screens.

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
- Python 3
- [Textual](https://github.com/Textualize/textual)
- `jq` (for the shell scripts)
- Optional: noctalia (for wallpaper/lockscreen sync)

## License

MIT
