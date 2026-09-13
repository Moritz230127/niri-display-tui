#!/usr/bin/env bash
# niri-display-adjust —— 调整聚焦显示器的缩放
# 2026-09-13 重建:原脚本随 ~/Pi工作区/scripts/ 消失,而 Mod+Ctrl+Plus/Minus 仍绑定本路径。
#
# 用法:
#   niri-display-adjust scale +0.25      # 放大一档(相对)
#   niri-display-adjust scale -0.25      # 缩小一档(相对)
#   niri-display-adjust scale 1.5        # 绝对设置
#   niri-display-adjust scale auto       # 交回 niri 自动选择
#   niri-display-adjust list             # 列出全部输出及其缩放
#   niri-display-adjust --dry-run scale +0.25   # 只打印将要执行的命令
#
# 说明:niri msg 的 output 改动是**运行时临时**的,不写入 outputs.kdl;
#      重启 niri 或 outputs.kdl 变化后会回到配置值。
set -uo pipefail

STEP_MIN=0.50
STEP_MAX=3.00

# --dry-run 允许出现在任意位置
DRY=0
_args=()
for _a in "$@"; do
    if [ "$_a" = "--dry-run" ]; then DRY=1; continue; fi
    _args+=("$_a")
done
if [ "${#_args[@]}" -gt 0 ]; then set -- "${_args[@]}"; else set --; fi

ACTION="${1:-list}"
shift || true

NIRI_MSG=(niri msg)

die() { echo "niri-display-adjust: $*" >&2; exit 1; }

command -v niri >/dev/null 2>&1 || die "找不到 niri 命令"
command -v jq   >/dev/null 2>&1 || die "找不到 jq(用于解析 niri IPC JSON)"

list_outputs() {
    "${NIRI_MSG[@]}" --json outputs 2>/dev/null | jq -r '
        to_entries[] | "\(.key)\t\(.value.logical.scale // "?")\t\(.value.logical.width // "?")x\(.value.logical.height // "?")"'
}

focused_output() {
    "${NIRI_MSG[@]}" --json focused-output 2>/dev/null | jq -r '.name // empty'
}

current_scale() {
    "${NIRI_MSG[@]}" --json outputs 2>/dev/null | jq -r --arg o "$1" '.[$o].logical.scale // empty'
}

case "$ACTION" in
    list|ls)
        printf '%-14s %-8s %s\n' "输出" "缩放" "逻辑分辨率"
        while IFS=$'\t' read -r name scale size; do
            printf '%-14s %-8s %s\n' "$name" "$scale" "$size"
        done < <(list_outputs)
        out=$(focused_output)
        [ -n "$out" ] && echo && echo "当前聚焦: $out"
        ;;

    scale)
        target="${1:-}"
        [ -n "$target" ] || die "用法: niri-display-adjust scale [+0.25|-0.25|1.5|auto]"

        out=$(focused_output)
        [ -n "$out" ] || die "没有聚焦的输出"

        if [ "$target" = "auto" ]; then
            new="auto"
        else
            cur=$(current_scale "$out")
            [ -n "$cur" ] || die "读不到 $out 的当前缩放"
            if [[ "$target" =~ ^[+-] ]]; then
                new=$(awk -v c="$cur" -v d="$target" -v lo="$STEP_MIN" -v hi="$STEP_MAX" 'BEGIN{
                    v = c + d;
                    if (v < lo) v = lo;
                    if (v > hi) v = hi;
                    printf "%.2f", v
                }')
                # 已在边界时不做无意义的写入
                if awk -v a="$cur" -v b="$new" 'BEGIN{exit !(a==b)}'; then
                    echo "$out 缩放已是 ${cur}(边界 ${STEP_MIN}–${STEP_MAX})"
                    exit 0
                fi
            else
                new="$target"
            fi
        fi

        if [ "$DRY" = 1 ]; then
            echo "将执行: niri msg output $out scale $new"
            exit 0
        fi

        "${NIRI_MSG[@]}" output "$out" scale "$new" || die "设置失败"
        echo "$out 缩放: ${cur:-?} → $new"
        command -v notify-send >/dev/null 2>&1 && \
            notify-send -t 1500 -h string:x-canonical-private-synchronous:display-scale \
                "显示器缩放" "$out: $new" 2>/dev/null
        ;;

    -h|--help|help)
        sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
        ;;

    *)
        die "未知动作: $ACTION(可用: scale | list | help)"
        ;;
esac
