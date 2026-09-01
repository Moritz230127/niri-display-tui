#!/bin/bash
# =============================================================================
# niri 显示器热插拔 udev 入口 (root 运行)
# -----------------------------------------------------------------------------
# 由 udev 规则 99-niri-display.rules 触发 (DRM add/remove/change 事件)。
# 职责:
#   1. 立即 detach 返回, 不阻塞 udev 事件处理
#   2. 后台 debounce 1.5s (等 DRM 状态稳定)
#   3. 以用户 Arch 身份 + 图形会话环境, 调用核心配置脚本
# =============================================================================
setsid bash -c '
    sleep 1.5
    exec runuser -u Arch -- env \
        HOME=/home/Arch \
        XDG_RUNTIME_DIR=/run/user/1000 \
        WAYLAND_DISPLAY=wayland-1 \
        /home/Arch/Pi工作区/scripts/niri-display-autoconfig.sh
' >/dev/null 2>&1 &
exit 0
