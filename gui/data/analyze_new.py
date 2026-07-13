# -*- coding: utf-8 -*-
"""离线分析 2026-05-27 录制的 4 个 JSONL：静止 / 向前 / 向左 / 顺时针90°。

目标：
1) 确认 0x03 / 0x04 yaw 在 CW 旋转中的符号方向（NED vs NWU）
2) 静止时 vx/vy 偏置幅度（看 2cm/s 死区是否足够）
3) 向前 / 向左 平移：vx/vy 主导轴 + 符号
4) 多次平移后 yaw 是否回到原值（IMU 陀螺漂移还是 GUI bug）
"""
import json
import math
import statistics
from pathlib import Path

DATA_DIR = Path(__file__).parent
FILES = {
    "static":   "静止20260527_123106.jsonl",
    "forward":  "向前20260527_123244.jsonl",
    "left":     "向左20260527_123311.jsonl",
    "cw90":     "顺时针90°20260527_123356.jsonl",
}


def load(name: str):
    rows = []
    p = DATA_DIR / FILES[name]
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if obj.get("_meta"):
                continue
            rows.append(obj)
    return rows


def by_cmd(rows, cmd_hex):
    return [r for r in rows if r.get("cmd") == cmd_hex]


def analyze_yaw_direction(name):
    rows = load(name)
    a03 = by_cmd(rows, "0x03")
    a04 = by_cmd(rows, "0x04")
    print(f"\n===== {name} =====")
    print(f"  total frames: {len(rows)}, 0x03={len(a03)}, 0x04={len(a04)}")
    if a03:
        y03 = [r["fields"]["yaw_deg"] for r in a03]
        # 解 wrap
        y03_unwrap = [y03[0]]
        for y in y03[1:]:
            prev = y03_unwrap[-1]
            dy = y - prev
            if dy > 180:  dy -= 360
            if dy < -180: dy += 360
            y03_unwrap.append(prev + dy)
        d03 = y03_unwrap[-1] - y03_unwrap[0]
        print(f"  0x03 yaw: start={y03[0]:.2f}  end={y03[-1]:.2f}  unwrap_delta={d03:+.2f}°")
        print(f"           min={min(y03):.2f}  max={max(y03):.2f}  range={max(y03)-min(y03):.2f}°")
    if a04:
        y04 = [r["fields"]["yaw_deg"] for r in a04]
        y04_unwrap = [y04[0]]
        for y in y04[1:]:
            prev = y04_unwrap[-1]
            dy = y - prev
            if dy > 180:  dy -= 360
            if dy < -180: dy += 360
            y04_unwrap.append(prev + dy)
        d04 = y04_unwrap[-1] - y04_unwrap[0]
        print(f"  0x04 yaw: start={y04[0]:.2f}  end={y04[-1]:.2f}  unwrap_delta={d04:+.2f}°")
        print(f"           min={min(y04):.2f}  max={max(y04):.2f}  range={max(y04)-min(y04):.2f}°")


def analyze_velocity(name):
    rows = load(name)
    a07 = by_cmd(rows, "0x07")
    if not a07:
        return
    vx = [r["fields"]["vx_cmps"] for r in a07]
    vy = [r["fields"]["vy_cmps"] for r in a07]
    vz = [r["fields"]["vz_cmps"] for r in a07]
    n = len(a07)
    print(f"  0x07 count={n}")
    print(f"   vx: mean={statistics.mean(vx):+.2f}  abs_max={max(abs(v) for v in vx)}  bias_abs={abs(statistics.mean(vx)):.2f}")
    print(f"   vy: mean={statistics.mean(vy):+.2f}  abs_max={max(abs(v) for v in vy)}  bias_abs={abs(statistics.mean(vy)):.2f}")
    print(f"   vz: mean={statistics.mean(vz):+.2f}  abs_max={max(abs(v) for v in vz)}")
    # 速度 |v|>5 的帧比例（运动帧）
    moving = [(x, y) for x, y in zip(vx, vy) if x*x + y*y > 25]
    if moving:
        mvx = [v[0] for v in moving]
        mvy = [v[1] for v in moving]
        ratio = sum(abs(v) for v in mvx) / max(1, sum(abs(v) for v in mvy))
        print(f"   |v|>5 moving frames: n={len(moving)}  |vx|/|vy|={ratio:.2f}")
        print(f"     mvx mean={statistics.mean(mvx):+.2f}  mvy mean={statistics.mean(mvy):+.2f}")
        print(f"     mvx range=[{min(mvx)},{max(mvx)}]  mvy range=[{min(mvy)},{max(mvy)}]")


def analyze_pos08(name):
    """看 0x08 飞控自带 XY 位置，可作横向真值对照（如果飞控自身有融合位置）。"""
    rows = load(name)
    a08 = by_cmd(rows, "0x08")
    if not a08:
        return
    px = [r["fields"]["pos_x_cm"] for r in a08]
    py = [r["fields"]["pos_y_cm"] for r in a08]
    print(f"  0x08 pos: x start={px[0]} end={px[-1]} delta={px[-1]-px[0]:+d}cm  range=[{min(px)},{max(px)}]")
    print(f"             y start={py[0]} end={py[-1]} delta={py[-1]-py[0]:+d}cm  range=[{min(py)},{max(py)}]")


def analyze_height(name):
    rows = load(name)
    a05 = by_cmd(rows, "0x05")
    if not a05:
        return
    alt = [r["fields"]["alt_fu_cm"] for r in a05]
    print(f"  0x05 alt_fu_cm: start={alt[0]} end={alt[-1]}  range=[{min(alt)},{max(alt)}]")


if __name__ == "__main__":
    for name in FILES:
        rows = load(name)
        dur = rows[-1]["t_mono"] - rows[0]["t_mono"]
        print(f"\n##### {name}: {FILES[name]}  dur={dur:.1f}s  frames={len(rows)} #####")
        analyze_yaw_direction(name)
        analyze_velocity(name)
        analyze_pos08(name)
        analyze_height(name)
