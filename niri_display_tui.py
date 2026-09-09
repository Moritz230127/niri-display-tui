#!/usr/bin/env python3
"""niri-display-tui — Textual-based Niri display manager.

Single-page, real-time monitor manager.

Design:
  * Left: live list of connected screens.  Up/Down moves the highlight,
    Enter selects the screen for editing.
  * Right top: vertical parameter list.  Up/Down switches parameters,
    Left/Right changes the value.
  * Right bottom: always-visible ASCII layout preview.
  * Connected screens are refreshed automatically; disconnected/known-only
    screens are not shown or recorded.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, Input, Static

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
try:
    import niri_display_geometry as geom
except Exception:
    sys.path.insert(0, "/usr/local/bin")
    import niri_display_geometry as geom  # type: ignore

SIDES = ("left", "right", "top", "bottom")
ALIGNS = ("top", "bottom", "left", "right")
TRANSFORMS = ("normal", "90", "180", "270", "flipped", "flipped-90", "flipped-180", "flipped-270")
VRRS = ("off", "on")
COMMON_SCALES = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0)
FIELD_NAMES = ("分辨率", "缩放", "VRR", "位置", "对齐", "变换", "电源")


def _niri(args: List[str]) -> Optional[subprocess.CompletedProcess[str]]:
    return geom.niri_msg(args)


def _run_autoconfig() -> bool:
    candidates = (
        "/usr/local/bin/niri-display-autoconfig.sh",
        os.path.expanduser("~/.config/niri/scripts/niri-display-autoconfig"),
        os.path.expanduser("~/Pi工作区/scripts/niri-display-autoconfig.sh"),
    )
    for path in candidates:
        if os.path.exists(path):
            try:
                subprocess.run([path], check=False, timeout=30)
                return True
            except Exception:
                return False
    return False


class NiriDisplayApp(App[None]):
    TITLE = "niri-display-tui"
    SUB_TITLE = "Niri 显示器管理"
    CSS = """
    Screen {
        layout: vertical;
    }

    #main {
        height: 1fr;
    }

    #left {
        width: 40%;
        border: round $primary;
        padding: 0 1;
    }

    #right {
        width: 60%;
        border: round $secondary;
        padding: 0 1;
    }

    #detail {
        height: auto;
        border: round $accent;
        padding: 1 2;
        margin-bottom: 1;
    }

    #preview-area {
        height: 1fr;
        border: round $success;
        padding: 0 1;
    }

    #preview {
        height: 1fr;
        padding: 0 1;
    }

    #cmd {
        height: auto;
        display: none;
        background: $panel;
        color: $text;
        border: round $accent;
        padding: 0 1;
    }

    #cmd.visible {
        display: block;
    }

    #help {
        height: auto;
        background: $boost;
        color: $text;
        padding: 0 1;
    }

    #status {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }

    DataTable {
        height: 1fr;
    }

    .dim {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("up", "cursor_up", "上", show=False),
        Binding("down", "cursor_down", "下", show=False),
        Binding("j", "cursor_down", "下", show=False),
        Binding("k", "cursor_up", "上", show=False),
        Binding("left", "cycle_left", "左", show=False),
        Binding("right", "cycle_right", "右", show=False),
        Binding("h", "cycle_left", "左", show=False),
        Binding("l", "cycle_right", "右", show=False),
        Binding(":", "enter_command", "命令", show=False),
        Binding("enter", "select_screen", "选中", show=False),
        Binding("escape", "cancel_command", "返回", show=False),
        Binding("f2", "apply_persistent", "保存应用"),
        Binding("f3", "reset_draft", "放弃重载"),
        Binding("f4", "apply_temporary", "临时应用"),
        Binding("?", "show_help", "帮助"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.connected: Dict[str, Dict[str, Any]] = {}
        self.work: Dict[str, Dict[str, Any]] = {}
        self.selected: Optional[str] = None
        self.active_screen: Optional[str] = None
        self.field_index = 0
        self.mode = "screens"  # "screens" or "params"
        self.command_mode = False
        self.dirty = False
        self.status_text = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static("已连接屏幕  [dim]↑/↓ 选择 · Enter 选中[/]", classes="dim")
                yield DataTable(id="monitors")
            with Vertical(id="right"):
                yield Static("参数  [dim]↑/↓ 切换参数 · ←/→ 修改值[/]", classes="dim")
                yield Static("", id="detail")
                yield Static("布局预览", classes="dim")
                yield Static("", id="preview")
        yield Input(id="cmd", placeholder=":命令，如 :分辨率 2560x1440@60", classes="cmd")
        yield Static(
            "j/k 选择  |  Enter 选中  |  h/l 修改值  |  : 打开命令  |  "
            "F2 保存+应用  |  F3 放弃  |  F4 临时应用  |  Q 退出",
            id="help",
        )
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#monitors", DataTable)
        table.cursor_type = "row"
        table.can_focus = False
        table.add_columns("名称", "状态", "模式", "缩放", "位置", "变换", "VRR")
        cmd = self.query_one("#cmd", Input)
        cmd.can_focus = False
        self.set_focus(None)
        self.reload_all()
        self.update_all()
        # Real-time monitor hotplug/connectivity refresh.
        self.set_interval(2, self.refresh_connected)

    # ------------------------------------------------------------------
    # Data loading / real-time refresh
    # ------------------------------------------------------------------
    def reload_all(self) -> None:
        self.connected = {m["name"]: m for m in geom.get_connected()}
        self.work = self._build_work()
        self.dirty = False
        if self.selected not in self.work:
            self.selected = next(iter(self.work), None)
        if self.active_screen not in self.work:
            self.active_screen = None
            if self.mode == "params":
                self.mode = "screens"
        self.status_text = "已刷新已连接屏幕"

    def refresh_connected(self) -> None:
        new_connected = {m["name"]: m for m in geom.get_connected()}
        if set(new_connected) == set(self.connected):
            return
        old_work = self.work
        self.connected = new_connected
        # Preserve any unsaved draft for screens that are still connected.
        known = geom.load_config()
        work: Dict[str, Dict[str, Any]] = {}
        for name, info in new_connected.items():
            if name in old_work:
                entry = copy.deepcopy(old_work[name])
                if info.get("modes") and entry["mode"] not in info["modes"]:
                    entry["mode"] = info["modes"][0]
            elif name in known:
                entry = copy.deepcopy(known[name])
                entry.setdefault("transform", "normal")
                entry.setdefault("enabled", "on")
                if info.get("modes") and entry["mode"] not in info["modes"]:
                    entry["mode"] = info["modes"][0]
            else:
                entry = {
                    "mode": info.get("modes", [""])[0] if info.get("modes") else "auto",
                    "scale": float(info.get("scale", 1.0)),
                    "vrr": "off",
                    "side": "left",
                    "align": "top",
                    "transform": "normal",
                    "enabled": "on",
                }
            work[name] = entry
        self.work = work
        if self.selected not in self.work:
            self.selected = next(iter(self.work), None)
        if self.active_screen not in self.work:
            self.active_screen = None
            if self.mode == "params":
                self.mode = "screens"
        self.status_text = "检测到显示器变化，已自动更新"
        self.update_all()

    def _build_work(self) -> Dict[str, Dict[str, Any]]:
        known = geom.load_config()
        work: Dict[str, Dict[str, Any]] = {}
        for name, info in self.connected.items():
            if name in known:
                entry = copy.deepcopy(known[name])
                entry.setdefault("transform", "normal")
                entry.setdefault("enabled", "on")
                # Keep persisted mode if still available, otherwise use current.
                if info.get("modes") and entry["mode"] not in info["modes"]:
                    entry["mode"] = info["modes"][0]
            else:
                entry = {
                    "mode": info.get("modes", [""])[0] if info.get("modes") else "auto",
                    "scale": float(info.get("scale", 1.0)),
                    "vrr": "off",
                    "side": "left",
                    "align": "top",
                    "transform": "normal",
                    "enabled": "on",
                }
            work[name] = entry
        return work

    def save_persistent(self) -> bool:
        # Only connected screens are saved; disconnected/known-only screens are not recorded.
        if geom.save_config(self.work):
            self.dirty = False
            return True
        return False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def update_all(self) -> None:
        self._update_table()
        self._update_detail()
        self._update_preview()
        self._update_status()

    def _update_table(self) -> None:
        table = self.query_one("#monitors", DataTable)
        table.clear()
        for name, entry in self.work.items():
            info = self.connected.get(name)
            status = "已连接" if info else "未连接"
            if entry.get("enabled", "on") == "off":
                status = "已关闭"
            mode = entry.get("mode", "auto")
            scale = f"{entry.get('scale', 1.0):g}"
            side = entry.get("side", "-")
            transform = entry.get("transform", "normal")
            vrr = entry.get("vrr", "off")
            marker = "> " if name == self.selected else "  "
            if name == self.active_screen:
                marker = "▶ " if name != self.selected else "> "
            table.add_row(f"{marker}{name}", status, mode, scale, side, transform, vrr, key=name)
        if self.selected is not None:
            try:
                table.move_cursor(row=list(self.work.keys()).index(self.selected))
            except ValueError:
                pass

    def _update_detail(self) -> None:
        detail = self.query_one("#detail", Static)
        if self.mode == "screens" or self.active_screen is None:
            detail.update(
                "[dim]尚未选中屏幕。[/]\n\n"
                "在左侧列表用 ↑/↓ 移动，按 Enter 选中后编辑参数。"
            )
            return
        entry = self.work[self.active_screen]
        info = self.connected.get(self.active_screen)
        lines = [f"[b]{self.active_screen}[/]  [dim]{'已连接' if info else '未连接'}[/]"]
        if info:
            make = info.get("make", "")
            model = info.get("model", "")
            if make or model:
                lines.append(f"[dim]{make} {model}[/]".strip())
        lines.append("")
        values = [
            entry.get("mode", "auto"),
            f"{entry.get('scale', 1.0):g}",
            entry.get("vrr", "off"),
            entry.get("side", "-"),
            entry.get("align", "-"),
            entry.get("transform", "normal"),
            entry.get("enabled", "on"),
        ]
        for i, (label, value) in enumerate(zip(FIELD_NAMES, values)):
            marker = ">" if i == self.field_index else " "
            if i == self.field_index:
                lines.append(f"[reverse]{marker} {label} : {value}[/]")
            else:
                lines.append(f"{marker} {label} : {value}")
        detail.update("\n".join(lines))

    def _update_preview(self) -> None:
        preview = self.query_one("#preview", Static)
        if not self.work:
            preview.update("无已连接显示器")
            return
        preview.update(self._render_preview_ascii())

    def _render_preview_ascii(self) -> str:
        try:
            layout = geom.compute_layout(self.work)
        except Exception:
            layout = {}
        if not layout:
            return "（无已启用显示器）"

        boxes: Dict[str, tuple[float, float, float, float]] = {}
        max_x = max_y = 0.0
        for name, (x, y) in layout.items():
            w, h = geom.logical_size(self.work.get(name, {}))
            if w <= 0 or h <= 0:
                continue
            boxes[name] = (x, y, w, h)
            max_x = max(max_x, x + w)
            max_y = max(max_y, y + h)
        if not boxes:
            return "（无已启用显示器）"

        tw, th = 56, 12
        scale = min(tw / max_x, th / max_y)
        grid = [[" "] * tw for _ in range(th)]

        def put(px: int, py: int, ch: str) -> None:
            if 0 <= px < tw and 0 <= py < th:
                grid[py][px] = ch

        for name, (x, y, w, h) in boxes.items():
            sx = int(x * scale)
            sy = int(y * scale)
            sw = max(1, int(w * scale))
            sh = max(1, int(h * scale))
            if sx >= tw or sy >= th:
                continue
            sw = min(sw, tw - sx - 1)
            sh = min(sh, th - sy - 1)
            if sw < 1 or sh < 1:
                continue
            for i in range(sw + 1):
                put(sx + i, sy, "-")
                put(sx + i, sy + sh, "-")
            for j in range(sh + 1):
                put(sx, sy + j, "|")
                put(sx + sw, sy + j, "|")
            put(sx, sy, "+")
            put(sx + sw, sy, "+")
            put(sx, sy + sh, "+")
            put(sx + sw, sy + sh, "+")
            if sw >= len(name) + 2:
                nx = sx + 1
                ny = sy + sh // 2
                for i, ch in enumerate(name):
                    if nx + i <= sx + sw - 1:
                        put(nx + i, ny, ch)

        return "\n".join("".join(row).rstrip() for row in grid)

    def _update_status(self) -> None:
        status = self.query_one("#status", Static)
        dirty = "● 有未保存修改" if self.dirty else "○ 已同步"
        mode = "选择屏幕" if self.mode == "screens" else f"编辑 {self.active_screen or '-'}"
        field = FIELD_NAMES[self.field_index] if self.field_index < len(FIELD_NAMES) else "-"
        status.update(f" {dirty}  |  模式: {mode}  |  字段: {field}  |  {self.status_text}")

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------
    def _select(self, name: Optional[str]) -> None:
        if name is not None and name in self.work:
            self.selected = name
            self.update_all()

    def action_cursor_up(self) -> None:
        if self.mode == "screens":
            names = list(self.work.keys())
            if not names:
                return
            idx = names.index(self.selected) if self.selected in names else 0
            self._select(names[(idx - 1) % len(names)])
        else:
            if self.active_screen is None:
                return
            self.field_index = (self.field_index - 1) % len(FIELD_NAMES)
            self.update_all()

    def action_cursor_down(self) -> None:
        if self.mode == "screens":
            names = list(self.work.keys())
            if not names:
                return
            idx = names.index(self.selected) if self.selected in names else -1
            self._select(names[(idx + 1) % len(names)])
        else:
            if self.active_screen is None:
                return
            self.field_index = (self.field_index + 1) % len(FIELD_NAMES)
            self.update_all()

    def action_select_screen(self) -> None:
        if self.mode == "screens":
            if self.selected is None:
                return
            self.active_screen = self.selected
            self.field_index = 0
            self.mode = "params"
            self.status_text = f"已选中 {self.active_screen}，↑/↓ 切换参数"
            self.update_all()
        else:
            # Enter in params mode is intentionally a no-op: selection is done
            # in the screen list, not here.
            self.status_text = "已在参数模式，按 Esc 返回屏幕列表"
            self._update_status()

    def action_back_to_screens(self) -> None:
        self.mode = "screens"
        self.status_text = "↑/↓ 选择屏幕，Enter 选中"
        self.update_all()

    def action_cycle_left(self) -> None:
        self._cycle_current(-1)

    def action_cycle_right(self) -> None:
        self._cycle_current(1)

    def _cycle_current(self, delta: int) -> None:
        if self.mode != "params" or self.active_screen is None:
            return
        entry = self.work[self.active_screen]
        if self.field_index == 0:
            self._cycle_mode(entry, delta)
        elif self.field_index == 1:
            self._cycle_scale(entry, delta)
        elif self.field_index == 2:
            self._cycle_vrr(entry, delta)
        elif self.field_index == 3:
            self._cycle_side(entry, delta)
        elif self.field_index == 4:
            self._cycle_align(entry, delta)
        elif self.field_index == 5:
            self._cycle_transform(entry, delta)
        elif self.field_index == 6:
            self._cycle_enabled(entry, delta)
        self.dirty = True
        self.status_text = "草稿已修改（F2 保存+应用 / F4 临时应用）"
        self.update_all()

    @staticmethod
    def _cycle_in_tuple(value: str, options: tuple[str, ...], delta: int) -> str:
        if value not in options:
            return options[0]
        return options[(options.index(value) + delta) % len(options)]

    def _cycle_mode(self, entry: Dict[str, Any], delta: int) -> None:
        info = self.connected.get(self.active_screen or "")
        modes = info.get("modes") if info else None
        if not modes:
            return
        current = entry.get("mode", "auto")
        if current not in modes:
            entry["mode"] = modes[0]
            return
        entry["mode"] = modes[(modes.index(current) + delta) % len(modes)]

    def _cycle_scale(self, entry: Dict[str, Any], delta: int) -> None:
        current = float(entry.get("scale", 1.0))
        scales = list(COMMON_SCALES)
        if current not in scales:
            scales.append(current)
            scales.sort()
        idx = scales.index(current)
        entry["scale"] = scales[(idx + delta) % len(scales)]

    def _cycle_vrr(self, entry: Dict[str, Any], delta: int) -> None:
        entry["vrr"] = self._cycle_in_tuple(entry.get("vrr", "off"), VRRS, delta)

    def _cycle_side(self, entry: Dict[str, Any], delta: int) -> None:
        entry["side"] = self._cycle_in_tuple(entry.get("side", "left"), SIDES, delta)

    def _cycle_align(self, entry: Dict[str, Any], delta: int) -> None:
        entry["align"] = self._cycle_in_tuple(entry.get("align", "top"), ALIGNS, delta)

    def _cycle_transform(self, entry: Dict[str, Any], delta: int) -> None:
        entry["transform"] = self._cycle_in_tuple(entry.get("transform", "normal"), TRANSFORMS, delta)

    def _cycle_enabled(self, entry: Dict[str, Any], delta: int) -> None:
        entry["enabled"] = "on" if entry.get("enabled", "on") == "off" else "off"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_apply_temporary(self) -> None:
        if not self.connected:
            self.status_text = "niri 未运行，无法临时应用"
            self._update_status()
            return
        self._apply_temporary_all()
        self.status_text = "已临时应用到当前 niri 会话"
        self._update_status()

    def _apply_temporary_all(self) -> None:
        for name, entry in self.work.items():
            if name not in self.connected:
                continue
            if entry.get("enabled", "on") == "off":
                _niri(["output", name, "off"])
                continue
            _niri(["output", name, "on"])
            mode = entry.get("mode")
            if mode and mode != "auto":
                _niri(["output", name, "mode", mode])
            scale = entry.get("scale")
            if scale:
                _niri(["output", name, "scale", f"{float(scale):g}"])
            vrr = entry.get("vrr", "off")
            if vrr == "on":
                _niri(["output", name, "vrr", "on"])
            else:
                _niri(["output", name, "vrr", "off"])
            transform = entry.get("transform", "normal")
            _niri(["output", name, "transform", transform])
        try:
            layout = geom.compute_layout(self.work)
        except Exception:
            layout = {}
        for name, (x, y) in layout.items():
            if name in self.connected and self.work.get(name, {}).get("enabled", "on") != "off":
                _niri(["output", name, "position", "set", str(int(x)), str(int(y))])

    def action_apply_persistent(self) -> None:
        if not self.save_persistent():
            self.status_text = "保存 monitors.conf 失败"
            self._update_status()
            return
        ok = _run_autoconfig()
        self.status_text = "已保存并运行 autoconfig" if ok else "已保存，但 autoconfig 未找到/执行失败"
        self.update_all()

    def action_reset_draft(self) -> None:
        self.reload_all()
        self.update_all()

    # ------------------------------------------------------------------
    # Vim-style command mode
    # ------------------------------------------------------------------
    def action_enter_command(self) -> None:
        if self.command_mode:
            return
        self.command_mode = True
        cmd = self.query_one("#cmd", Input)
        cmd.add_class("visible")
        cmd.value = ":"
        cmd.can_focus = True
        cmd.focus()
        self._update_status()

    def action_cancel_command(self) -> None:
        if not self.command_mode:
            self.action_back_to_screens()
            return
        self._hide_command()
        self.status_text = "已取消命令"
        self._update_status()

    def _hide_command(self) -> None:
        self.command_mode = False
        cmd = self.query_one("#cmd", Input)
        cmd.remove_class("visible")
        cmd.value = ""
        cmd.can_focus = False
        # Return focus to the app so normal-mode bindings work again.
        self.set_focus(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.command_mode:
            return
        raw = event.value.strip()
        self._hide_command()
        if raw.startswith(":"):
            raw = raw[1:]
        self.run_command(raw.strip())

    def run_command(self, raw: str) -> None:
        if not raw:
            self.status_text = "空命令"
            self._update_status()
            return
        parts = raw.split(None, 1)
        cmd = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        # Chinese and English aliases.
        aliases = {
            "分辨率": "mode", "mode": "mode",
            "缩放": "scale", "scale": "scale",
            "vrr": "vrr", "vr": "vrr",
            "位置": "side", "side": "side",
            "对齐": "align", "align": "align",
            "变换": "transform", "transform": "transform",
            "电源": "power", "power": "power",
            "应用": "apply", "临时应用": "apply",
            "保存": "save", "保存应用": "save",
            "放弃": "reset", "reset": "reset",
            "退出": "quit", "quit": "quit", "q": "quit",
            "帮助": "help", "help": "help",
        }
        action = aliases.get(cmd)
        if action is None:
            self.status_text = f"未知命令: {cmd}（:帮助 查看）"
            self._update_status()
            return

        if action == "mode":
            self._command_mode_value(arg, 0)
        elif action == "scale":
            self._command_scale(arg)
        elif action == "vrr":
            self._command_vrr(arg)
        elif action == "side":
            self._command_side(arg)
        elif action == "align":
            self._command_align(arg)
        elif action == "transform":
            self._command_transform(arg)
        elif action == "power":
            self._command_power(arg)
        elif action == "apply":
            self.action_apply_temporary()
        elif action == "save":
            self.action_apply_persistent()
        elif action == "reset":
            self.action_reset_draft()
        elif action == "quit":
            self.exit()
        elif action == "help":
            self.action_show_help()

    def _require_active(self) -> bool:
        if self.mode != "params" or self.active_screen is None:
            self.status_text = "请先用 Enter 选中一个屏幕"
            self._update_status()
            return False
        return True

    def _command_mode_value(self, arg: str, field_index: int) -> None:
        if not self._require_active():
            return
        self.field_index = field_index
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        if field_index == 0:
            info = self.connected.get(self.active_screen or "")
            modes = info.get("modes") if info else None
            if modes and arg not in modes:
                self.status_text = f"无效分辨率: {arg}"
                self._update_status()
                return
            entry["mode"] = arg
        self.dirty = True
        self.status_text = f"已设置 {FIELD_NAMES[field_index]}: {arg}"
        self.update_all()

    def _command_scale(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 1
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        try:
            value = float(arg)
        except ValueError:
            self.status_text = f"无效缩放: {arg}"
            self._update_status()
            return
        entry["scale"] = value
        self.dirty = True
        self.status_text = f"已设置 缩放: {value:g}"
        self.update_all()

    def _command_vrr(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 2
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        val = arg.lower()
        if val not in ("on", "off"):
            self.status_text = "VRR 参数应为 on 或 off"
            self._update_status()
            return
        entry["vrr"] = val
        self.dirty = True
        self.status_text = f"已设置 VRR: {val}"
        self.update_all()

    def _command_side(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 3
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        if arg not in SIDES:
            self.status_text = f"位置应为 {'/'.join(SIDES)}"
            self._update_status()
            return
        entry["side"] = arg
        self.dirty = True
        self.status_text = f"已设置 位置: {arg}"
        self.update_all()

    def _command_align(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 4
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        if arg not in ALIGNS:
            self.status_text = f"对齐应为 {'/'.join(ALIGNS)}"
            self._update_status()
            return
        entry["align"] = arg
        self.dirty = True
        self.status_text = f"已设置 对齐: {arg}"
        self.update_all()

    def _command_transform(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 5
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        if arg not in TRANSFORMS:
            self.status_text = f"变换应为 {'/'.join(TRANSFORMS)}"
            self._update_status()
            return
        entry["transform"] = arg
        self.dirty = True
        self.status_text = f"已设置 变换: {arg}"
        self.update_all()

    def _command_power(self, arg: str) -> None:
        if not self._require_active():
            return
        self.field_index = 6
        entry = self.work[self.active_screen]
        if not arg:
            self._cycle_current(1)
            return
        val = arg.lower()
        if val not in ("on", "off"):
            self.status_text = "电源参数应为 on 或 off"
            self._update_status()
            return
        entry["enabled"] = val
        self.dirty = True
        self.status_text = f"已设置 电源: {val}"
        self.update_all()

    def action_show_help(self) -> None:
        self.status_text = (
            "↑/↓ 选择屏幕或切换参数  |  Enter 选中屏幕  |  ←/→ 修改值  |  "
            "Esc 返回屏幕列表  |  F2 保存+应用  |  F3 放弃  |  F4 临时应用  |  Q 退出"
        )
        self._update_status()


def main() -> None:
    app = NiriDisplayApp()
    app.run()


if __name__ == "__main__":
    main()
