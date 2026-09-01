#!/usr/bin/env python3
"""niri 显示器配置 TUI — 自由设置缩放 / 放置顺序 / 对齐方式

纯 curses, 无第三方依赖. Unicode 线条 + 配色面板界面.

按键:
    ↑↓ / jk    移动光标
    ←→ / hl    切换 位置(side) / 对齐(align) 值
    +/-         调整缩放 (scale)
    F2 / a      应用 (写 monitors.conf + 重载 niri/noctalia)
    F3 / r      重置 (重新读取 monitors.conf)
    q / Esc     退出
"""
import curses
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from niri_display_geometry import (  # noqa: E402
    ALIGNS,
    SIDES,
    compute_layout,
    get_connected,
    load_config,
    logical_size,
    save_config,
)

AUTOCONFIG = os.path.expanduser("~/.config/niri/scripts/niri-display-autoconfig")
SCALES = [1.0, 1.25, 1.5, 1.75, 2.0]
OPPOSITE = {"left": "right", "right": "left", "top": "bottom", "bottom": "top"}

# 配色对
C_TITLE = 1    # 标题 (青)
C_VALUE = 2    # 值 (绿)
C_SELECT = 3   # 选中 (黑底青)
C_BORDER = 4   # 边框 (黄)


def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(C_TITLE, curses.COLOR_CYAN, -1)
    curses.init_pair(C_VALUE, curses.COLOR_GREEN, -1)
    curses.init_pair(C_SELECT, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(C_BORDER, curses.COLOR_YELLOW, -1)


class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.connected = get_connected()
        self.cfg = load_config()
        # 确保每个已连接显示器都有配置项 (新屏用当前模式 + 默认值)
        for m in self.connected:
            if m["name"] not in self.cfg:
                self.cfg[m["name"]] = {
                    "mode": f"{m['width']}x{m['height']}@60.000",
                    "scale": m["scale"],
                    "vrr": "",
                    "side": "left",
                    "align": "top",
                }
        # 字段导航: [(monitor_index, field), ...]
        self.fields = []
        for i in range(len(self.connected)):
            self.fields.append((i, "scale"))
            self.fields.append((i, "side"))
            self.fields.append((i, "align"))
        self.cursor = 0
        self.status = ""

    # ---- 交互 ----
    def run(self):
        curses.curs_set(0)
        while True:
            self.draw()
            key = self.stdscr.getch()
            if key in (ord("q"), 27):
                break
            elif key in (curses.KEY_UP, ord("k")):
                self.cursor = (self.cursor - 1) % len(self.fields)
            elif key in (curses.KEY_DOWN, ord("j")):
                self.cursor = (self.cursor + 1) % len(self.fields)
            elif key in (curses.KEY_LEFT, ord("h")):
                self.cycle(-1)
            elif key in (curses.KEY_RIGHT, ord("l")):
                self.cycle(1)
            elif key in (ord("+"), ord("=")):
                self.change_scale(1)
            elif key in (ord("-"), ord("_")):
                self.change_scale(-1)
            elif key in (curses.KEY_F2, ord("a")):
                self.apply()
            elif key in (curses.KEY_F3, ord("r")):
                self.reset()

    def cycle(self, delta):
        mi, field = self.fields[self.cursor]
        name = self.connected[mi]["name"]
        if field == "side":
            vals = SIDES
        elif field == "align":
            vals = ALIGNS
        else:
            return
        cur = self.cfg[name][field]
        idx = vals.index(cur) if cur in vals else 0
        new = vals[(idx + delta) % len(vals)]
        self.cfg[name][field] = new
        if field == "side":
            # 2 屏场景: 另一屏自动取相反位置
            for m in self.connected:
                if m["name"] != name:
                    self.cfg[m["name"]]["side"] = OPPOSITE[new]
        elif field == "align":
            # 对齐是两屏间关系, 同步所有屏
            for m in self.connected:
                self.cfg[m["name"]]["align"] = new

    def change_scale(self, delta):
        mi, field = self.fields[self.cursor]
        if field != "scale":
            return
        name = self.connected[mi]["name"]
        cur = self.cfg[name]["scale"]
        idx = SCALES.index(cur) if cur in SCALES else 0
        new = SCALES[(idx + delta) % len(SCALES)]
        self.cfg[name]["scale"] = new

    def apply(self):
        if not save_config(self.cfg):
            self.status = "写入 monitors.conf 失败"
            return
        r = subprocess.run([AUTOCONFIG], capture_output=True, text=True)
        self.status = f"已应用 (exit {r.returncode})"

    def reset(self):
        self.cfg = load_config()
        self.status = "已重置 (重新读取 monitors.conf)"

    # ---- 绘制 ----
    def box(self, y, x, height, width, title="", attr=0):
        """画 Unicode 线条边框盒子"""
        if height < 2 or width < 4:
            return
        try:
            self.stdscr.addstr(y, x, "┌" + "─" * (width - 2) + "┐", attr)
            for i in range(1, height - 1):
                self.stdscr.addstr(y + i, x, "│", attr)
                self.stdscr.addstr(y + i, x + width - 1, "│", attr)
            self.stdscr.addstr(y + height - 1, x, "└" + "─" * (width - 2) + "┘", attr)
            if title:
                self.stdscr.addstr(y, x + 2, title, attr | curses.A_BOLD)
        except curses.error:
            pass

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 16 or w < 60:
            self.stdscr.addstr(0, 0, "终端太小: 请放大到至少 60x16")
            self.stdscr.refresh()
            return

        # 外边框
        self.box(0, 0, h - 1, w, " niri 显示器配置 ", curses.color_pair(C_BORDER))

        y = 2
        # 显示器卡片
        for i, m in enumerate(self.connected):
            name = m["name"]
            c = self.cfg[name]
            header = f"  {i + 1}. {name}  ·  {m['make']} {m['model']}  ·  {m['width']}x{m['height']}"
            try:
                self.stdscr.addstr(y, 2, header[: w - 4], curses.color_pair(C_TITLE) | curses.A_BOLD)
            except curses.error:
                pass
            y += 1
            y = self.draw_fields(y, 4, i)
            y += 1

        # 预览面板
        preview_h = max(8, min(12, h - y - 4))
        self.box(y, 2, preview_h, w - 4, " 布局预览 ", curses.color_pair(C_BORDER))
        self.draw_preview(y + 1, 4, w - 8, preview_h - 2)
        y += preview_h + 1

        # 状态行
        if self.status:
            try:
                self.stdscr.addstr(h - 3, 2, self.status[: w - 4], curses.color_pair(C_VALUE))
            except curses.error:
                pass

        # 底部提示 (左对齐, 避免中文双宽换行)
        hint = "↑↓ 移动 · ←→ 切换 · +/- 缩放 · F2 应用 · F3 重置 · q 退出"
        try:
            self.stdscr.addstr(h - 2, 2, hint[: w - 4], curses.color_pair(C_TITLE))
        except curses.error:
            pass
        self.stdscr.refresh()

    def draw_fields(self, y, x, mi):
        """绘制某显示器的三个字段 (缩放/位置/对齐), 每个一行, 选中项高亮"""
        name = self.connected[mi]["name"]
        c = self.cfg[name]
        for field in ("scale", "side", "align"):
            if self.fields.index((mi, field)) == self.cursor:
                attr = curses.A_REVERSE | curses.color_pair(C_SELECT)
            else:
                attr = curses.color_pair(C_VALUE)
            if field == "scale":
                label = f"缩放 [{c['scale']:.2f}]"
            elif field == "side":
                label = f"位置 [{c['side']}]"
            else:
                label = f"对齐 [{c['align']}]"
            try:
                self.stdscr.addstr(y, x, label, attr)
            except curses.error:
                pass
            y += 1
        return y

    def draw_preview(self, y, x, width, height):
        """布局预览: 按逻辑尺寸归一化到网格, Unicode 线条 (仅已连接屏)"""
        connected_names = {m["name"] for m in self.connected}
        cfg = {k: v for k, v in self.cfg.items() if k in connected_names}
        layout = compute_layout(cfg)
        if not layout:
            return
        boxes = {}
        max_x = max_y = 0.0
        for name, (x0, y0) in layout.items():
            lw, lh = logical_size(cfg[name])
            boxes[name] = (x0, y0, x0 + lw, y0 + lh)
            max_x = max(max_x, x0 + lw)
            max_y = max(max_y, y0 + lh)
        if max_x <= 0 or max_y <= 0:
            return
        gw = max(10, width - 2)
        gh = max(4, min(height - 2, round(gw * max_y / max_x)))
        sx, sy = gw / max_x, gh / max_y
        grid = [[" " for _ in range(gw + 1)] for _ in range(gh + 1)]
        for name, (x1, y1, x2, y2) in boxes.items():
            try:
                gx1 = round(x1 * sx)
                gy1 = round(y1 * sy)
                gx2 = round(x2 * sx)
                gy2 = round(y2 * sy)
            except (ValueError, TypeError):
                continue
            gx1 = max(0, min(gw - 1, gx1))
            gy1 = max(0, min(gh - 1, gy1))
            gx2 = max(gx1 + 1, min(gw, gx2))
            gy2 = max(gy1 + 1, min(gh, gy2))
            for gx in range(gx1, gx2 + 1):
                grid[gy1][gx] = "─"
                grid[gy2][gx] = "─"
            for gy in range(gy1, gy2 + 1):
                grid[gy][gx1] = "│"
                grid[gy][gx2] = "│"
            grid[gy1][gx1] = "┌"
            grid[gy1][gx2] = "┐"
            grid[gy2][gx1] = "└"
            grid[gy2][gx2] = "┘"
            label = name
            lx = gx1 + 1
            for ch in label[: max(0, gx2 - gx1 - 1)]:
                if lx < gx2:
                    grid[gy1 + 1][lx] = ch
                    lx += 1
        # 修复共享边界的连接符 (两屏相邻时 ┌┐ 重叠处改为 ├ ┬ ┼ 等)
        for gy in range(gh + 1):
            for gx in range(gw + 1):
                ch = grid[gy][gx]
                if ch not in "─│┌┐└┘":
                    continue
                left = grid[gy][gx - 1] if gx > 0 else " "
                right = grid[gy][gx + 1] if gx < gw else " "
                up = grid[gy - 1][gx] if gy > 0 else " "
                down = grid[gy + 1][gx] if gy < gh else " "
                hset = "─┌┐└┘"
                vset = "│┌┐└┘"
                has_h = left in hset or right in hset
                has_v = up in vset or down in vset
                if has_h and has_v:
                    if left in hset and right in hset and up in vset and down in vset:
                        grid[gy][gx] = "┼"
                    elif left in hset and right in hset:
                        grid[gy][gx] = "┬" if down in vset else "┴"
                    elif up in vset and down in vset:
                        grid[gy][gx] = "├" if right in hset else "┤"
        for i, row in enumerate(grid):
            line = "  " + "".join(row)
            try:
                self.stdscr.addstr(y + i, x, line[:width], curses.color_pair(C_VALUE))
            except curses.error:
                pass


def main():
    try:
        curses.wrapper(lambda stdscr: (init_colors(), App(stdscr).run()))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
