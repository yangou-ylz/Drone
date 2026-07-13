# -*- coding: utf-8 -*-
"""
验证0x07坐标系：体系 vs 世界系
关键判据：如果是体系，x移动时 vx 应主导且几乎不含 vy；如果是世界系，两个分量都有
"""
import json, math, pathlib

DATA = pathlib.Path(__file__).parent

def load(fn):
    return [json.loads(l) for l in (DATA / fn).open(encoding="utf-8") if "_meta" not in l]

def analyze_velocity_frame(fn, label, yaw0_deg):
    rows = load(fn)
    r07 = [r for r in rows if r["cmd"] == "0x07"]
    vxs = [r["fields"].get("vx_cmps", 0) for r in r07]
    vys = [r["fields"].get("vy_cmps", 0) for r in r07]

    # 只取速度绝对值>5cm/s的运动帧（排除静止噪声）
    moving = [(vx, vy) for vx, vy in zip(vxs, vys) if abs(vx)+abs(vy) > 5]
    if not moving:
        print(f"  {label}: 无明显运动帧")
        return
    
    vx_m = [abs(v[0]) for v in moving]
    vy_m = [abs(v[1]) for v in moving]
    vx_mean = sum(vx_m)/len(vx_m)
    vy_mean = sum(vy_m)/len(vy_m)

    # 体坐标系判断：主导分量与次分量比值
    ratio = vx_mean / (vy_mean + 0.01)
    
    print(f"\n  [{label}] yaw0={yaw0_deg:.1f}°  运动帧={len(moving)}个")
    print(f"    |vx|均={vx_mean:.1f}  |vy|均={vy_mean:.1f}  比值={ratio:.1f}x")
    
    if ratio > 3.0:
        print(f"    → vx 强主导 → 与 体系+x轴(前后) 飞行一致")
        # 如果是世界系，预期的 vx/vy 比值
        yaw_r = math.radians(yaw0_deg)
        expected_world_ratio = abs(math.cos(yaw_r)) / (abs(math.sin(yaw_r)) + 0.01)
        print(f"    → 若是世界系+X飞行: 预期|vx/vy|={expected_world_ratio:.2f}  (实际{ratio:.1f}) "
              + ("≈匹配" if abs(ratio-expected_world_ratio)<1.0 else "?不匹配"))
        print(f"    → 若是体系+X飞行: 预期|vx/vy|>>1 ?")
    elif ratio < 0.3:
        print(f"    → vy 强主导 → 与 体系+y轴(左右) 飞行一致")

print("=== 0x07 坐标系判断 ===")

files = [
    ("x移动_20260527_110221.jsonl", "x移动(预期:vx主导)", 142.8),
    ("y移动_20260527_105859.jsonl", "y移动(预期:vy主导)", 133.9),
]
for fn, label, yaw0 in files:
    analyze_velocity_frame(fn, label, yaw0)

print("\n\n=== 世界系 vs 体系：两种修复方案的轨迹预测 ===")

def integrate_body(fn, yaw0_deg, use_delta_yaw=True):
    """用体坐标系假设积分轨迹（delta_yaw 旋转 or 直接使用）"""
    rows = load(fn)
    by_cmd = {}
    for r in rows:
        by_cmd.setdefault(r["cmd"], []).append(r)
    
    att = {r["t_mono"]: r["fields"] for r in by_cmd.get("0x03", []) + by_cmd.get("0x04", [])}
    
    x, y = 0.0, 0.0
    last_ts = None
    peaks_x, peaks_y = [0.0], [0.0]
    
    for r in by_cmd.get("0x07", []):
        ts = r["t_mono"]
        vx_b = r["fields"].get("vx_cmps", 0)
        vy_b = r["fields"].get("vy_cmps", 0)
        
        # 死区
        if abs(vx_b) + abs(vy_b) < 2:
            last_ts = ts
            continue
        
        if use_delta_yaw:
            # 找最近姿态帧
            if att:
                closest = min(att.keys(), key=lambda t: abs(t-ts))
                yaw_now = att[closest].get("yaw_deg", yaw0_deg)
            else:
                yaw_now = yaw0_deg
            delta = math.radians(yaw_now - yaw0_deg)
            c, s = math.cos(delta), math.sin(delta)
            vx_l = vx_b * c - vy_b * s
            vy_l = vx_b * s + vy_b * c
        else:
            vx_l, vy_l = float(vx_b), float(vy_b)
        
        if last_ts is not None:
            dt = ts - last_ts
            if 0 < dt < 1.0:
                x += vx_l * dt
                y += vy_l * dt
        last_ts = ts
        peaks_x.append(x)
        peaks_y.append(y)
    
    rx = max(peaks_x)-min(peaks_x)
    ry = max(peaks_y)-min(peaks_y)
    return rx, ry, x, y

for fn, label, yaw0 in files:
    rx_b, ry_b, fx_b, fy_b = integrate_body(fn, yaw0, use_delta_yaw=True)
    print(f"\n  {label} [体系+delta_yaw修复]:")
    print(f"    X range={rx_b:.0f}cm  Y range={ry_b:.0f}cm  → 主轴={'X' if rx_b>ry_b else 'Y'}")
    dom_ratio = max(rx_b,ry_b)/(min(rx_b,ry_b)+0.1)
    print(f"    主/次比={dom_ratio:.1f}x  最终(x={fx_b:.1f}, y={fy_b:.1f})")

print()
