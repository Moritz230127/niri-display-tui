#!/bin/bash
# =============================================================================
# niri + noctalia 显示器热插拔自动配置 (v2 - 持久化版)
# -----------------------------------------------------------------------------
# 触发链: udev DRM 热插拔事件
#   -> /usr/local/bin/niri-display-hotplug.sh (root, detach+debounce+runuser)
#   -> 本脚本 (以用户 Arch 身份, 图形会话环境)
#
# 职责:
#   1. 动态发现 niri IPC socket (socket 名含 PID, 每次会话变化)
#   2. 读取当前已连接显示器集合 (niri msg -j outputs)
#   3. 按"连接集合"生成 outputs.kdl (原子写入 + 备份) 并触发 niri 重载
#      -> 布局持久化, 配置 reload 后不丢失
#   4. 通用兜底: 未记录的"新屏幕"自动 mode auto / scale auto / position auto
#   5. 同步 noctalia (壁纸/锁屏 widget 按显示器) -> noctalia msg config-reload
#
# 日志: /tmp/niri-display-autoconfig.log
# =============================================================================
set -u

LOG=/tmp/niri-display-autoconfig.log
RUNTIME_DIR=/run/user/1000
OUTPUTS_KDL="$HOME/.config/niri/outputs.kdl"

# 串行化: 防止 udev 多事件并发运行 (wrapper 已去重, 此处双保险)
exec 9>"/tmp/niri-display-autoconfig.lock"
flock 9 2>/dev/null || exit 0

log() { echo "$(date '+%F %T') $*" >>"$LOG"; }

log "=== hotplug triggered ==="

# --- 1. 发现 niri socket -----------------------------------------------------
# shellcheck disable=SC2012  # 单 socket 场景, 取第一个即可
SOCK=$(ls "$RUNTIME_DIR"/niri.wayland-*.sock 2>/dev/null | head -1)
if [ -z "$SOCK" ]; then
    log "  [skip] niri socket not found under $RUNTIME_DIR"
    exit 0
fi
export NIRI_SOCKET="$SOCK"

# --- 2. 读取当前连接集合 ------------------------------------------------------
OUT=$(/usr/bin/niri msg -j outputs 2>>"$LOG") || {
    log "  [skip] niri msg outputs failed"
    exit 0
}

# 提取所有已连接输出的 connector 名 (JSON 顶层 key)
CONNECTED=$(printf '%s' "$OUT" | jq -r 'keys[]' 2>>"$LOG")
log "  connected: $(printf '%s' "$CONNECTED" | tr '\n' ' ')"

has() { printf '%s\n' "$CONNECTED" | grep -qx "$1"; }

# --- 3. 已知显示器预设 --------------------------------------------------------
# 从数据文件读取 (name|mode|scale|vrr|side|align|transform|enabled), 每行一个显示器
#   side: left/right/top/bottom (相对另一屏的位置)
#   align: 横排 top/bottom, 竖排 left/right (对齐方式)
#   transform: normal/90/180/270/flipped/...
#   enabled: on/off
# 自由调节: niri-display-tui (TUI) 或 niri-display-adjust.sh 实时调整并回写此文件
MONITORS_CONF="$HOME/.config/niri/monitors.conf"
mapfile -t KNOWN_MONITORS < <(grep -vE '^\s*#|^\s*$' "$MONITORS_CONF" 2>/dev/null)

# 计算布局: 调用共享几何模块 (side/align + 逻辑尺寸 -> 坐标), 仅输出已连接屏
layout_positions() {
    python3 /usr/local/bin/niri_display_geometry.py --positions 2>>"$LOG"
}

# --- 4. 生成 outputs.kdl ------------------------------------------------------
gen_kdl() {
    local ts
    ts=$(date '+%F %T')
    {
        printf '// outputs.kdl —— 显示器配置 (由 niri-display-autoconfig.sh 热插拔自动生成)\n'
        printf '// 上次更新: %s\n\n' "$ts"

        # 已知屏: 按布局位置输出 (几何模块输出 "name x y" 空格分隔)
        local name x y mode scale vrr
        while read -r name x y; do
            [ -z "$name" ] && continue
            # 从 KNOWN_MONITORS 查该屏的 mode/scale/vrr
            mode=""
            scale=""
            vrr=""
            local entry
            for entry in "${KNOWN_MONITORS[@]}"; do
                if [ "${entry%%|*}" = "$name" ]; then
                    IFS='|' read -r _ mode scale vrr _ _ <<<"$entry"
                    break
                fi
            done
            printf 'output "%s" {\n' "$name"
            [ -n "$mode" ] && printf '    mode "%s"\n' "$mode"
            [ -n "$scale" ] && printf '    scale %s\n' "$scale"
            printf '    position x=%s y=%s\n' "$x" "$y"
            [ "$vrr" = on ] && printf '    variable-refresh-rate\n'
            printf '    focus-at-startup\n'
            printf '}\n\n'
        done <<<"$(layout_positions)"

        # 未知屏 (新屏幕) 兜底: 启用 + auto
        local c entry known
        for c in $CONNECTED; do
            known=false
            for entry in "${KNOWN_MONITORS[@]}"; do
                [ "${entry%%|*}" = "$c" ] && known=true
            done
            if ! $known; then
                printf 'output "%s" {\n' "$c"
                printf '    mode auto\n'
                printf '    scale auto\n'
                printf '    position auto\n'
                printf '}\n\n'
            fi
        done
    }
}

NEW_KDL=$(gen_kdl)

# --- 5. 与当前 outputs.kdl 比较, 变化才写入 (原子 + 备份) ----------------------
# 排除头部时间戳行, 保证幂等 (内容不变则不重写)
CUR=$(grep -v '上次更新' "$OUTPUTS_KDL" 2>/dev/null)
NEW=$(printf '%s' "$NEW_KDL" | grep -v '上次更新')
if [ -n "$CUR" ] && [ "$CUR" = "$NEW" ]; then
    log "  outputs.kdl unchanged, skip write"
else
    if [ -f "$OUTPUTS_KDL" ]; then
        cp "$OUTPUTS_KDL" "$OUTPUTS_KDL.bak-hotplug-$(date +%Y%m%d-%H%M%S)"
        log "  backed up previous outputs.kdl"
    fi
    TMP="$OUTPUTS_KDL.tmp.$$"
    printf '%s' "$NEW_KDL" >"$TMP"
    mv "$TMP" "$OUTPUTS_KDL"
    log "  wrote outputs.kdl"
fi

# --- 6. 触发 niri 重载 (原子 mv 可能不触发 inotify, 显式 reload 更可靠) ---------
/usr/bin/niri msg action load-config-file >>"$LOG" 2>&1
log "  niri config reloaded"

# --- 7. 同步 noctalia (仅当其运行时) -----------------------------------------
if pgrep -x noctalia >/dev/null 2>&1; then
    /usr/bin/noctalia msg config-reload >>"$LOG" 2>&1
else
    log "  [skip] noctalia not running"
fi
log "  done"
