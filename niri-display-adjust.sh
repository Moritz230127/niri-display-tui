#!/bin/bash
# =============================================================================
# niri 显示器快速缩放调节 (快捷键用)
# -----------------------------------------------------------------------------
# 用法:
#   niri-display-adjust.sh scale +0.25|-0.25   调整聚焦显示器缩放
#
# 实时应用 (niri msg output) 并回写 ~/.config/niri/monitors.conf (持久化).
# 位置/对齐请用 niri-display-tui (TUI) 设置.
# =============================================================================
set -u

RUNTIME_DIR=/run/user/1000
MONITORS_CONF="$HOME/.config/niri/monitors.conf"

# --- 发现 niri socket --------------------------------------------------------
# shellcheck disable=SC2012
SOCK=$(ls "$RUNTIME_DIR"/niri.wayland-*.sock 2>/dev/null | head -1)
if [ -z "$SOCK" ]; then
  echo "niri socket not found under $RUNTIME_DIR" >&2
  exit 1
fi
export NIRI_SOCKET="$SOCK"

# --- 聚焦显示器 --------------------------------------------------------------
NAME=$(niri msg -j focused-output 2>/dev/null | jq -r '.name')
if [ -z "$NAME" ]; then
  echo "no focused output" >&2
  exit 1
fi

# --- 回写 monitors.conf 中 NAME 行的 scale 字段 (field 3) ---------------------
update_scale() {
  local val="$1"
  awk -v name="$NAME" -v val="$val" '
        $0 ~ /\|/ && $0 !~ /^[[:space:]]*#/ {
            n = split($0, f, "|")
            if (f[1] == name) {
                f[3] = val
                out = f[1]
                for (i = 2; i <= n; i++) out = out "|" f[i]
                print out
                next
            }
        }
        { print }
    ' "$MONITORS_CONF" >"$MONITORS_CONF.tmp" && mv "$MONITORS_CONF.tmp" "$MONITORS_CONF"
}

case "${1:-}" in
scale)
  DELTA="${2:-}"
  CUR=$(niri msg -j outputs | jq -r ".[\"$NAME\"].logical.scale")
  NEW=$(awk -v c="$CUR" -v d="$DELTA" 'BEGIN { printf "%.2f", c + d }')
  NEW=$(awk -v n="$NEW" 'BEGIN { if (n < 1) n = 1; if (n > 3) n = 3; printf "%.2f", n }')
  niri msg output "$NAME" scale "$NEW"
  update_scale "$NEW"
  echo "scale $NAME: $CUR -> $NEW"
  ;;
*)
  echo "usage: $0 scale +0.25|-0.25" >&2
  exit 1
  ;;
esac
