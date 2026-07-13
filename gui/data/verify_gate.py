# -*- coding: utf-8 -*-
"""验证两个假设：
1) cw90 旋转测试中 0x07 vx/vy 时序是否和 yaw 角速度强相关（→ 应在旋转时冻结积分）
2) left 测试 vy 时序是否有"先正后负"的反弹（→ 应在减速段冻结，避免反向积分）

输出关键时间序列，定位修复参数。
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent


def load_cmd(name, cmd):
    out = []
    with (DATA_DIR / name).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("_meta"):
                continue
            if obj.get("cmd") == cmd:
                out.append((obj["t_mono"], obj["fields"]))
    return out


def unwrap_series(ys):
    out = [ys[0]]
    for y in ys[1:]:
        prev = out[-1]
        d = y - prev
        if d > 180: d -= 360
        if d < -180: d += 360
        out.append(prev + d)
    return out


def yaw_rate_series(name):
    a03 = load_cmd(name, "0x03")
    ts = [t for t, _ in a03]
    y = unwrap_series([f["yaw_deg"] for _, f in a03])
    rates = []
    for i in range(1, len(ts)):
        dt = ts[i] - ts[i-1]
        if dt > 0:
            rates.append((ts[i], (y[i] - y[i-1]) / dt))
    return rates  # (t, deg/s)


def integrate_vel(name, deadband=2.0, gate_yaw_rate=None):
    """模拟 PathTracker 积分，看尾部累积位置。可选角速度门控。"""
    import math as M
    v07 = load_cmd(name, "0x07")
    a03 = load_cmd(name, "0x03")
    # 拼线 yaw_rate by nearest 0x03
    yaw_ts = [t for t, _ in a03]
    yaw_unw = unwrap_series([f["yaw_deg"] for _, f in a03])
    def nearest_yaw_rate(t):
        # 找最接近 t 的两个 0x03 求斜率
        if len(yaw_ts) < 2:
            return 0.0
        # 二分
        lo, hi = 0, len(yaw_ts) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if yaw_ts[mid] < t: lo = mid
            else: hi = mid
        dt = yaw_ts[hi] - yaw_ts[lo]
        if dt <= 0:
            return 0.0
        return (yaw_unw[hi] - yaw_unw[lo]) / dt
    x = y = 0.0
    last_t = None
    yaw0 = yaw_unw[0]
    gated_count = 0
    integrated_count = 0
    for t, f in v07:
        vx_b, vy_b = float(f["vx_cmps"]), float(f["vy_cmps"])
        # 当前 yaw（最近）
        idx = min(range(len(yaw_ts)), key=lambda i: abs(yaw_ts[i] - t))
        cur_yaw = yaw_unw[idx]
        delta = cur_yaw - yaw0
        rad = M.radians(((delta + 180) % 360) - 180)
        c, s = M.cos(rad), M.sin(rad)
        vx_l = vx_b * c - vy_b * s
        vy_l = vx_b * s + vy_b * c
        if vx_l*vx_l + vy_l*vy_l < deadband*deadband:
            vx_l = vy_l = 0.0
        if gate_yaw_rate is not None and abs(nearest_yaw_rate(t)) > gate_yaw_rate:
            vx_l = vy_l = 0.0
            gated_count += 1
        if last_t is not None:
            dt = t - last_t
            if 0 < dt < 0.5:
                x += vx_l * dt
                y += vy_l * dt
                if vx_l or vy_l:
                    integrated_count += 1
        last_t = t
    return x, y, gated_count, integrated_count, len(v07)


def show_left_vy_sequence():
    """看 left 测试 vy 时序中是否有正负翻转。"""
    v07 = load_cmd("向左20260527_123311.jsonl", "0x07")
    print(f"\n=== left vy 时序 (非零段) ===")
    last_state = None
    segments = []
    cur_seg = []
    for t, f in v07:
        vy = f["vy_cmps"]
        if abs(vy) >= 3:  # 显著非零
            cur_seg.append((t, vy))
        else:
            if cur_seg:
                segments.append(cur_seg)
                cur_seg = []
    if cur_seg:
        segments.append(cur_seg)
    for i, seg in enumerate(segments):
        signs = set(1 if v>0 else (-1 if v<0 else 0) for _, v in seg)
        print(f" seg{i}: t={seg[0][0]:.2f}~{seg[-1][0]:.2f} ({len(seg)}帧)  signs={signs}  values=", [v for _, v in seg[:10]], "..." if len(seg)>10 else "")


if __name__ == "__main__":
    # 1. cw90 角速度峰值
    rates = yaw_rate_series("顺时针90°20260527_123356.jsonl")
    abs_rates = [abs(r) for _, r in rates]
    abs_rates.sort()
    print(f"\n=== cw90 yaw rate (deg/s) ===")
    print(f"  total samples: {len(rates)}")
    print(f"  max={max(abs_rates):.1f}, p99={abs_rates[int(len(abs_rates)*0.99)]:.1f}, p50={abs_rates[len(abs_rates)//2]:.1f}")
    # 静止参考
    rates_s = yaw_rate_series("静止20260527_123106.jsonl")
    a_s = sorted([abs(r) for _, r in rates_s])
    print(f"=== static yaw rate (噪声底)  max={a_s[-1]:.2f}, p99={a_s[int(len(a_s)*0.99)]:.2f} ===")

    # 2. 模拟 PathTracker 在 cw90 / left 上的积分末位
    print("\n=== 积分末位 (deadband=2cm/s, 无角速度门控) ===")
    for name in ["静止20260527_123106.jsonl", "向前20260527_123244.jsonl",
                 "向左20260527_123311.jsonl", "顺时针90°20260527_123356.jsonl"]:
        x, y, g, n, total = integrate_vel(name, deadband=2.0)
        print(f"  {name[:6]:8s} 末位=({x:+6.1f},{y:+6.1f})cm 积分帧={n}/{total}")

    print("\n=== 积分末位 (deadband=2cm/s, 角速度门控>5deg/s) ===")
    for name in ["静止20260527_123106.jsonl", "向前20260527_123244.jsonl",
                 "向左20260527_123311.jsonl", "顺时针90°20260527_123356.jsonl"]:
        x, y, g, n, total = integrate_vel(name, deadband=2.0, gate_yaw_rate=5.0)
        print(f"  {name[:6]:8s} 末位=({x:+6.1f},{y:+6.1f})cm 门控掉={g}/{total}")

    # 3. left vy 反弹分析
    show_left_vy_sequence()
