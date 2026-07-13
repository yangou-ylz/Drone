# -*- coding: utf-8 -*-
"""确认：直接用体系速度（不旋转）的效果，加速度死区"""
import json, math, pathlib

DATA = pathlib.Path(__file__).parent

FILES = {
    "x移动": "x移动_20260527_110221.jsonl",
    "y移动": "y移动_20260527_105859.jsonl",
    "z移动": "z移动_20260527_110412.jsonl",
    "静止":  "静止_20260527_105513.jsonl",
}

def load(fn):
    return [json.loads(l) for l in (DATA / fn).open(encoding="utf-8") if "_meta" not in l]

def normalize_yaw_diff(diff_deg):
    """把角度差归一化到 [-180, +180]"""
    while diff_deg > 180:
        diff_deg -= 360
    while diff_deg < -180:
        diff_deg += 360
    return diff_deg

def simulate_body_frame(fn, label, deadband=2.0):
    rows = load(fn)
    by_cmd = {}
    for r in rows:
        by_cmd.setdefault(r["cmd"], []).append(r)

    # 修复后：0x04 yaw 符号取反，与0x03对齐
    att03 = by_cmd.get("0x03", [])
    att04 = [{**r, "fields": {**r["fields"], "yaw_deg": -r["fields"]["yaw_deg"]}}
             for r in by_cmd.get("0x04", [])]
    att = sorted(att03 + att04, key=lambda r: r["t_mono"])

    yaw0 = att[0]["fields"]["yaw_deg"] if att else 0.0
    z0 = by_cmd.get("0x05", [{}])[0].get("fields", {}).get("alt_fu_cm", 0)

    # 建立时间→yaw 的查找表（归一化差值）
    att_ts = [(r["t_mono"], r["fields"]["yaw_deg"]) for r in att]

    def get_yaw(ts):
        if not att_ts:
            return yaw0
        closest = min(att_ts, key=lambda x: abs(x[0]-ts))
        return closest[1]

    x, y, z = 0.0, 0.0, 0.0
    last_ts = None
    path = [(0.0, x, y, z)]

    events = []
    for r in by_cmd.get("0x07", []):
        events.append((r["t_mono"], "vel",
                       r["fields"].get("vx_cmps", 0),
                       r["fields"].get("vy_cmps", 0),
                       r["fields"].get("vz_cmps", 0)))
    for r in by_cmd.get("0x05", []):
        events.append((r["t_mono"], "hgt", r["fields"].get("alt_fu_cm", 0)))
    events.sort(key=lambda e: e[0])
    t0 = events[0][0] if events else 0.0

    for e in events:
        ts = e[0]
        if e[1] == "hgt":
            z = e[2] - z0
            path.append((ts - t0, x, y, z))
        else:
            vx_b, vy_b = float(e[2]), float(e[3])

            # 方案A: 直接使用体系（完全不旋转）
            # 激活时 body = local，yaw不变时一直成立
            if abs(vx_b) + abs(vy_b) < deadband:
                last_ts = ts
                continue

            # 应用 delta_yaw（归一化！）
            yaw_now = get_yaw(ts)
            delta_deg = normalize_yaw_diff(yaw_now - yaw0)
            delta_rad = math.radians(delta_deg)
            c, s = math.cos(delta_rad), math.sin(delta_rad)
            vx_l = vx_b * c - vy_b * s
            vy_l = vx_b * s + vy_b * c

            if last_ts is not None:
                dt = ts - last_ts
                if 0 < dt < 1.0:
                    x += vx_l * dt
                    y += vy_l * dt
            last_ts = ts

    xs = [p[1] for p in path]
    ys = [p[2] for p in path]
    zs = [p[3] for p in path]
    rx = max(xs) - min(xs)
    ry = max(ys) - min(ys)
    rz = max(zs) - min(zs)
    dom = "X" if rx >= ry and rx >= rz else ("Y" if ry >= rz else "Z")
    dur = events[-1][0] - t0 if events else 0

    print(f"  {label}: Xrange={rx:.0f}cm  Yrange={ry:.0f}cm  Zrange={rz:.0f}cm"
          f"  主轴={dom}  主/次={max(rx,ry,rz)/(sorted([rx,ry,rz])[1]+0.1):.1f}x"
          f"  最终(x={xs[-1]:.1f}, y={ys[-1]:.1f})  时长={dur:.0f}s")
    return rx, ry, rz

print("=== 修复方案：体系速度 + delta_yaw(归一化) + 死区 2cm/s ===\n")
for label, fn in FILES.items():
    simulate_body_frame(fn, label)

print("\n=== 对比：不同死区阈值下的静止漂移 ===")
for db in [0.0, 1.0, 2.0, 3.0]:
    rx, ry, _ = simulate_body_frame("静止_20260527_105513.jsonl", f"静止(dead={db}cm/s)", deadband=db)
    print(f"    deadband={db}: 漂移 X={rx:.1f}cm  Y={ry:.1f}cm")
