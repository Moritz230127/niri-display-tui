#!/usr/bin/env python3
"""niri 显示器布局几何计算 (共享模块, TUI 与 autoconfig 共用)

数据模型 (monitors.conf, 每行一条):
    name|mode|scale|vrr|side|align
    side:  left/right/top/bottom — 该屏相对另一屏的位置 (放置顺序)
    align: 横排 top/bottom, 竖排 left/right — 对齐方式

CLI:
    --positions   输出 "name x y" (逻辑坐标, 供 autoconfig 生成 outputs.kdl)
"""
import json
import os
import subprocess
import sys

RUNTIME_DIR = f"/run/user/{os.getuid()}"
MONITORS_CONF = os.path.expanduser("~/.config/niri/monitors.conf")

SIDES = ("left", "right", "top", "bottom")
ALIGNS = ("top", "bottom", "left", "right")


def find_socket():
    try:
        for f in os.listdir(RUNTIME_DIR):
            if f.startswith("niri.wayland-") and f.endswith(".sock"):
                return os.path.join(RUNTIME_DIR, f)
    except FileNotFoundError:
        pass
    return None


def niri_msg(args):
    sock = find_socket()
    if not sock:
        return None
    env = dict(os.environ, NIRI_SOCKET=sock)
    return subprocess.run(["niri", "msg"] + args, capture_output=True, text=True, env=env)


def get_connected():
    """返回已连接显示器列表 [{name, make, model, width, height, scale}]"""
    r = niri_msg(["-j", "outputs"])
    if not r or r.returncode != 0:
        return []
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return []
    out = []
    for name, info in data.items():
        mode = info["modes"][info["current_mode"]]
        out.append({
            "name": name,
            "make": info.get("make", ""),
            "model": info.get("model", ""),
            "width": mode["width"],
            "height": mode["height"],
            "scale": info["logical"]["scale"],
        })
    return out


def load_config():
    """读取 monitors.conf -> {name: {mode, scale, vrr, side, align}}"""
    cfg = {}
    if not os.path.exists(MONITORS_CONF):
        return cfg
    try:
        with open(MONITORS_CONF) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("|")
                if len(parts) >= 6:
                    name, mode, scale, vrr, side, align = parts[:6]
                    try:
                        cfg[name] = {
                            "mode": mode,
                            "scale": float(scale),
                            "vrr": vrr,
                            "side": side,
                            "align": align,
                        }
                    except ValueError:
                        continue
    except OSError:
        return {}
    return cfg


def save_config(cfg):
    """写回 monitors.conf (v2 格式)"""
    lines = [
        "# niri 已知显示器配置 (niri-display-tui 生成)",
        "# 格式: name|mode|scale|vrr|side|align",
        "#   side: left/right/top/bottom (该屏相对另一屏的位置)",
        "#   align: 横排 top/bottom, 竖排 left/right (对齐方式)",
    ]
    for name, c in cfg.items():
        lines.append(f"{name}|{c['mode']}|{c['scale']:.2f}|{c['vrr']}|{c['side']}|{c['align']}")
    try:
        with open(MONITORS_CONF, "w") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        return False
    return True


def logical_size(entry):
    """从 mode 解析物理分辨率, 除以 scale 得逻辑尺寸 (w, h)"""
    try:
        wh = entry["mode"].split("@")[0]
        w, h = wh.split("x")
        scale = entry["scale"]
        return int(w) / scale, int(h) / scale
    except (ValueError, KeyError, ZeroDivisionError):
        return 0.0, 0.0


def compute_layout(cfg):
    """根据 side/align 计算每个显示器的逻辑坐标 {name: (x, y)}

    横排 (side 为 left/right): 左屏 x=0, 右屏 x=左屏宽;
        align=top 两屏 y=0; align=bottom 两屏底边对齐于 max 高
    竖排 (side 为 top/bottom): 上屏 y=0, 下屏 y=上屏高;
        align=left 两屏 x=0; align=right 两屏右边对齐于 max 宽
    """
    names = list(cfg.keys())
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: (0, 0)}

    a, b = names[0], names[1]
    sa, sb = cfg[a]["side"], cfg[b]["side"]
    wa, ha = logical_size(cfg[a])
    wb, hb = logical_size(cfg[b])

    # 横排
    if sa in ("left", "right") and sb in ("left", "right"):
        if sa == "left":
            anchor, other = a, b
            ax, ox = 0, wa
        else:
            anchor, other = b, a
            ax, ox = 0, wb
        align = cfg[anchor]["align"]
        max_h = max(ha, hb)
        if align == "bottom":
            ay = max_h - logical_size(cfg[anchor])[1]
            oy = max_h - logical_size(cfg[other])[1]
        else:  # top
            ay = oy = 0
        return {anchor: (ax, ay), other: (ox, oy)}

    # 竖排
    if sa == "top":
        anchor, other = a, b
        ay, oy = 0, ha
    else:
        anchor, other = b, a
        ay, oy = 0, hb
    align = cfg[anchor]["align"]
    max_w = max(wa, wb)
    if align == "right":
        ax = max_w - logical_size(cfg[anchor])[0]
        ox = max_w - logical_size(cfg[other])[0]
    else:  # left
        ax = ox = 0
    return {anchor: (ax, ay), other: (ox, oy)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--positions":
        cfg = load_config()
        # 仅保留已连接的显示器 (未连接的不参与布局)
        connected = {m["name"] for m in get_connected()}
        cfg = {k: v for k, v in cfg.items() if k in connected}
        layout = compute_layout(cfg)
        for name, (x, y) in layout.items():
            try:
                print(f"{name} {int(x)} {int(y)}")
            except BrokenPipeError:
                return 0
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
