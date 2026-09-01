#!/bin/bash
# =============================================================================
# niri 显示器热插拔 udev 入口 (root 运行)
# -----------------------------------------------------------------------------
# 由 udev 规则 99-niri-display.rules 触发 (DRM add/remove/change 事件)。
# 一次物理插拔会触发多个 udev 事件 (card/connector), 每个事件都会启动本脚本。
#
# 去重策略 (关键):
#   1. 持锁原子检查: 1s 内已有触发则跳过 (合并同一次插拔的多个事件)
#   2. 检查完立即释放锁 (不阻塞后续触发)
#   3. debounce 1.5s 后后台运行 autoconfig (autoconfig 自带 flock 串行化)
# =============================================================================
LOCK=/tmp/niri-display-hotplug.lock
TRIG=/tmp/niri-display-hotplug.trigger

# 原子去重: 1s 内已有触发则跳过
exec 9>"$LOCK"
flock 9 || exit 0
now=$(date +%s)
if [ -f "$TRIG" ]; then
    last=$(cat "$TRIG" 2>/dev/null || echo 0)
    if [ $((now - last)) -lt 1 ]; then
        exit 0
    fi
fi
date +%s >"$TRIG"
flock -u 9

sleep 1.5
setsid runuser -u Arch -- env \
    HOME=/home/Arch \
    XDG_RUNTIME_DIR=/run/user/1000 \
    WAYLAND_DISPLAY=wayland-1 \
    /home/Arch/Pi工作区/scripts/niri-display-autoconfig.sh >/dev/null 2>&1 &
exit 0
