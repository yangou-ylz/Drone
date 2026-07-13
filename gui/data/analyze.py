# -*- coding: utf-8 -*-
"""
分析 JSONL 传感器帧，诊断：
  bug 4 静止漂移（vx/vy/vz bias）
  bug 5 水平移动方向错 + XYZ 比例不一致
"""
import json, math, os, sys, pathlib

DATA = pathlib.Path(__file__).parent

FILES = {
    "jingzhi":  "静止_20260527_105513.jsonl",
    "x_move":   "x移动_20260527_110221.jsonl",
    "y_move":   "y移动_20260527_105859.jsonl",
    "z_move":   "z移动_20260527_110412.jsonl",
}

def load(fn):
    rows = []
    for line in (DATA / fn).open(encoding="utf-8"):
        j = json.loads(line)
        if "_meta" not in j:
            rows.append(j)
    return rows

def get_field(row, key, default=None):
    return row.get("fields", {}).get(key, default)

def print_sep(title=""):
    print("\n" + "="*60)
    if title:
        print("  " + title)
        print("="*60)

# ─────────────────────────────────────────────
# 0x07 速度帧 字段 → vx_cm_s / vy_cm_s / vz_cm_s
# 0x03 姿态帧 字段 → roll_deg / pitch_deg / yaw_deg
# 0x05 高度帧 字段 → alt_fu_cm
# 0x08 位置帧 字段 → pos_x_cm / pos_y_cm
# ─────────────────────────────────────────────

def analyze(rows, label):
    print_sep(label)
    by_cmd = {}
    for r in rows:
        by_cmd.setdefault(r["cmd"], []).append(r)
    ts0 = rows[0]["t_mono"]
    ts1 = rows[-1]["t_mono"]
    print(f"  总帧数: {len(rows)}   时长: {ts1-ts0:.2f}s")
    for cmd, lst in sorted(by_cmd.items()):
        print(f"  {cmd}: {len(lst)} 帧")

    # 速度
    vel_rows = by_cmd.get("0x07", [])
    if vel_rows:
        vxs = [get_field(r, "vx_cm_s", 0) for r in vel_rows]
        vys = [get_field(r, "vy_cm_s", 0) for r in vel_rows]
        vzs = [get_field(r, "vz_cm_s", 0) for r in vel_rows]
        print(f"\n  [0x07 速度]")
        print(f"    vx  均值={sum(vxs)/len(vxs):+.2f}  min={min(vxs):+.1f}  max={max(vxs):+.1f}  std={stdev(vxs):.2f}")
        print(f"    vy  均值={sum(vys)/len(vys):+.2f}  min={min(vys):+.1f}  max={max(vys):+.1f}  std={stdev(vys):.2f}")
        print(f"    vz  均值={sum(vzs)/len(vzs):+.2f}  min={min(vzs):+.1f}  max={max(vzs):+.1f}  std={stdev(vzs):.2f}")

    # 高度
    hgt_rows = by_cmd.get("0x05", [])
    if hgt_rows:
        alts = [get_field(r, "alt_fu_cm", 0) for r in hgt_rows]
        print(f"\n  [0x05 高度(cm)]  均值={sum(alts)/len(alts):.1f}  min={min(alts):.1f}  max={max(alts):.1f}  range={max(alts)-min(alts):.1f}")

    # XY 位置（0x08）
    pos_rows = by_cmd.get("0x08", [])
    if pos_rows:
        xs = [get_field(r, "pos_x_cm", 0) for r in pos_rows]
        ys = [get_field(r, "pos_y_cm", 0) for r in pos_rows]
        print(f"\n  [0x08 XY位置(cm)]")
        print(f"    x  均值={sum(xs)/len(xs):.1f}  min={min(xs):.1f}  max={max(xs):.1f}  range={max(xs)-min(xs):.1f}")
        print(f"    y  均值={sum(ys)/len(ys):.1f}  min={min(ys):.1f}  max={max(ys):.1f}  range={max(ys)-min(ys):.1f}")

    # 姿态
    att_rows = by_cmd.get("0x03", []) + by_cmd.get("0x04", [])
    if att_rows:
        rolls  = [get_field(r, "roll_deg",  0) for r in att_rows]
        pitchs = [get_field(r, "pitch_deg", 0) for r in att_rows]
        yaws   = [get_field(r, "yaw_deg",   0) for r in att_rows]
        print(f"\n  [姿态 欧拉角(°)]")
        print(f"    roll   均值={sum(rolls)/len(rolls):+.2f}  range={max(rolls)-min(rolls):.2f}")
        print(f"    pitch  均值={sum(pitchs)/len(pitchs):+.2f}  range={max(pitchs)-min(pitchs):.2f}")
        print(f"    yaw    首={yaws[0]:+.1f}  末={yaws[-1]:+.1f}  range={max(yaws)-min(yaws):.2f}")

    return by_cmd

def stdev(arr):
    if len(arr) < 2:
        return 0.0
    m = sum(arr) / len(arr)
    return math.sqrt(sum((v-m)**2 for v in arr) / (len(arr)-1))

# ─── 位移估算（速度积分 vs 高度直测）────────────────
def integrate_vel(rows_07, axis):
    key = {"x": "vx_cm_s", "y": "vy_cm_s", "z": "vz_cm_s"}[axis]
    pts = [(r["t_mono"], get_field(r, key, 0)) for r in rows_07]
    if len(pts) < 2:
        return 0.0
    disp = 0.0
    for i in range(1, len(pts)):
        dt = pts[i][0] - pts[i-1][0]
        disp += pts[i-1][1] * dt
    return disp

def main():
    all_data = {}
    for key, fn in FILES.items():
        rows = load(fn)
        by_cmd = analyze(rows, f"{key}  ({fn})")
        all_data[key] = (rows, by_cmd)

    # ─── 综合诊断 ───────────────────────────────
    print_sep("综合诊断")

    # BUG 4: 静止漂移
    rows_jz, bc_jz = all_data["jingzhi"]
    vel07_jz = bc_jz.get("0x07", [])
    if vel07_jz:
        vxs = [get_field(r, "vx_cm_s", 0) for r in vel07_jz]
        vys = [get_field(r, "vy_cm_s", 0) for r in vel07_jz]
        bias_x = sum(vxs)/len(vxs)
        bias_y = sum(vys)/len(vys)
        print(f"\n[BUG 4 静止漂移]")
        print(f"  静止时 vx 均值={bias_x:+.2f} cm/s  vy 均值={bias_y:+.2f} cm/s")
        # 积分出来的位移
        dur = rows_jz[-1]["t_mono"] - rows_jz[0]["t_mono"]
        drift_x = bias_x * dur
        drift_y = bias_y * dur
        print(f"  在 {dur:.1f}s 内 X 方向预测漂移 ≈ {drift_x:.1f} cm  Y ≈ {drift_y:.1f} cm")
        if abs(bias_x) > 2 or abs(bias_y) > 2:
            print(f"  ? bias 较大，需要 ZUPT 零速补偿或速度偏置校正")
        else:
            print(f"  ? bias 可接受（< 2 cm/s）")

    # BUG 5a: 移动方向（X 移动时 vx 应该主导）
    print(f"\n[BUG 5a 移动方向诊断]")
    for mov_key, expected_dominant_axis in [("x_move","x"), ("y_move","y")]:
        rows_mv, bc_mv = all_data[mov_key]
        vel07 = bc_mv.get("0x07", [])
        if not vel07:
            print(f"  {mov_key}: 无 0x07 帧，跳过")
            continue
        vxs = [get_field(r, "vx_cm_s", 0) for r in vel07]
        vys = [get_field(r, "vy_cm_s", 0) for r in vel07]
        abs_vx_mean = abs(sum(vxs)/len(vxs))
        abs_vy_mean = abs(sum(vys)/len(vys))
        dominant = "x" if abs_vx_mean > abs_vy_mean else "y"
        ratio = max(abs_vx_mean, abs_vy_mean) / (min(abs_vx_mean, abs_vy_mean) + 0.01)
        print(f"  {mov_key}: |vx|均={abs_vx_mean:.2f}  |vy|均={abs_vy_mean:.2f}  主导轴={dominant}(期望={expected_dominant_axis})  比值={ratio:.1f}x")
        if dominant != expected_dominant_axis:
            print(f"    ? 方向混乱: 向 {expected_dominant_axis} 飞但 v{dominant} 更大 → yaw0 坐标旋转方向可能反了")
        else:
            print(f"    ? 主导轴正确")

    # BUG 5b: 比例一致性（Z 高度直测 vs vz 积分）
    print(f"\n[BUG 5b Z 轴比例（高度直测 vs vz 积分）]")
    rows_z, bc_z = all_data["z_move"]
    hgt_rows_z = bc_z.get("0x05", [])
    vel07_z    = bc_z.get("0x07", [])
    if hgt_rows_z:
        alts = [get_field(r, "alt_fu_cm", 0) for r in hgt_rows_z]
        z_range_hgt = max(alts) - min(alts)
        print(f"  Z 直测高度 range = {z_range_hgt:.1f} cm")
    if vel07_z:
        disp_z_integ = integrate_vel(vel07_z, "z")
        print(f"  vz 积分位移      = {disp_z_integ:.1f} cm")
        if hgt_rows_z:
            if z_range_hgt > 1.0:
                ratio_z = disp_z_integ / z_range_hgt
                print(f"  比值(积分/直测)   = {ratio_z:.2f}  (理想≈1 或-1)")
                if abs(ratio_z) < 0.3 or abs(ratio_z) > 3.0:
                    print(f"  ? 比例严重失调，vz 单位可能不是 cm/s，或 alt 单位不是 cm")

    # XY 积分位移 vs XY 直测（若有 0x08）
    print(f"\n[BUG 5c XY 比例（位置直测 vs vx/vy 积分）]")
    for mov_key, axis in [("x_move","x"), ("y_move","y")]:
        rows_mv, bc_mv = all_data[mov_key]
        vel07  = bc_mv.get("0x07", [])
        pos_rows = bc_mv.get("0x08", [])
        disp_integ = integrate_vel(vel07, axis) if vel07 else None
        if pos_rows:
            xs = [get_field(r, "pos_x_cm", 0) for r in pos_rows]
            ys = [get_field(r, "pos_y_cm", 0) for r in pos_rows]
            pos_range = max(xs)-min(xs) if axis=="x" else max(ys)-min(ys)
            print(f"  {mov_key}: 0x08 位置直测 {axis.upper()} range={pos_range:.1f} cm", end="")
            if disp_integ is not None:
                print(f"  vInteg={disp_integ:.1f} cm  比值={disp_integ/(pos_range+0.001):.2f}", end="")
            print()
        elif disp_integ is not None:
            print(f"  {mov_key}: 无 0x08 数据，只有 vInteg={disp_integ:.1f} cm")
        else:
            print(f"  {mov_key}: 无速度/位置数据")

    # yaw 信息
    print(f"\n[yaw0 参考值]")
    for key, (rows, bc) in all_data.items():
        att = bc.get("0x03", []) + bc.get("0x04", [])
        if att:
            yaw_first = get_field(att[0], "yaw_deg", 0)
            print(f"  {key}: 首帧 yaw = {yaw_first:+.1f}°")

if __name__ == "__main__":
    main()
