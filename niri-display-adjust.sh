#!/bin/bash
# niri-display-adjust.sh — quick scale/move adjustments for the focused output.
# Persists scale changes to monitors.conf; move is temporary (position is
# normally computed from side/align by the TUI/autoconfig).
set -euo pipefail

CONF="$HOME/.config/niri/monitors.conf"
SOCK=$(ls /run/user/"$(id -u)"/niri.wayland-*.sock 2>/dev/null | head -1)
if [ -z "$SOCK" ]; then
    echo "niri socket not found" >&2
    exit 1
fi
export NIRI_SOCKET="$SOCK"

FOCUSED=$(niri msg -j focused-output | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')
ENTRY=$(grep "^${FOCUSED}|" "$CONF" 2>/dev/null | tail -1 || true)
if [ -z "$ENTRY" ]; then
    echo "$FOCUSED is not in $CONF" >&2
    exit 1
fi

IFS='|' read -r name mode scale vrr side align transform enabled <<<"$ENTRY"
: "${transform:=normal}"
: "${enabled:=on}"

case "${1:-}" in
    scale)
        delta="${2:-}"
        if [[ "$delta" == \+* ]]; then
            new=$(python3 -c "print(f'{$scale+${delta#+}:.2f}')")
        elif [[ "$delta" == -* ]]; then
            new=$(python3 -c "print(f'{$scale${delta}:.2f}')")
        elif [[ "$delta" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
            new="$delta"
        else
            echo "usage: $0 scale +0.25|-0.25|VALUE" >&2
            exit 1
        fi
        niri msg output "$FOCUSED" scale "$new"
        sed -i "s/^${FOCUSED}|.*/${FOCUSED}|${mode}|${new}|${vrr}|${side}|${align}|${transform}|${enabled}/" "$CONF"
        ;;
    move)
        dir="${2:-}"
        step="${3:-10}"
        read -r cx cy <<<"$(niri msg -j focused-output | python3 -c 'import json,sys; d=json.load(sys.stdin)["logical"]; print(d["x"], d["y"])')"
        nx="$cx"; ny="$cy"
        case "$dir" in
            left)  nx=$((cx-step)) ;;
            right) nx=$((cx+step)) ;;
            up)    ny=$((cy-step)) ;;
            down)  ny=$((cy+step)) ;;
            *) echo "usage: $0 move left|right|up|down [step]" >&2; exit 1 ;;
        esac
        niri msg output "$FOCUSED" position set "$nx" "$ny"
        ;;
    reset)
        /usr/local/bin/niri-display-autoconfig.sh
        ;;
    *)
        echo "usage: $0 scale +0.25|-0.25|VALUE | move left|right|up|down [step] | reset" >&2
        exit 1
        ;;
esac
