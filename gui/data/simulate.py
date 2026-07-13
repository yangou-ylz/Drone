# -*- coding: utf-8 -*-
"""
完整模拟 PathTracker 逻辑，重建每个文件的轨迹，诊断 bug 4/5。
输出：每个文件最终位置、中途峰值、偏置估计。
"""
import json, math, pathlib

DATA = pathlib.Path(__file__).parent

FILES = {
    "静止":  "静止_20260527_105513.jsonl",
    "x移动": "x移动_20260527_110221.jsonl",
    "y移动": "y移动_20260527_105859.jsonl",
    "z移动": "z移动_20260527_110412.jsonl",
}

def load(fn):
    rows = []
    for line in (DATA / fn).open(encoding="utf-8"):
        j = json.loads(line)
        if "_meta" not in j:
            rows.append(j)
    return rows

# ─── 模拟 PathTracker（与 gui/services/path_tracker.py 完全一致）─────
class SimTracker:
    def __init__(self, yaw0_deg, z0_cm):
        self.yaw0 = yaw0_deg
        r = math.radians(yaw0_deg)
        self.c = math.cos(-r)
        self.s = math.sin(-r)
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.z0 = z0_cm
        self._last_ts = None
        self.path = [(0.0, 0.0, 0.0, 0.0)]  # (ts, x, y, z)

    def feed_vel(self, ts, vx_w, vy_w, vz_w):
        # 同 path_tracker.py：0x07 视为世界系速度，去 yaw0 旋转
        vx_l = vx_w * self.c - vy_w * self.s
        vy_l = vx_w * self.s + vy_w * self.c
        if self._last_ts is None:
            self._last_ts = ts
            return
        dt = ts - self._last_ts
        self._last_ts = ts
        if dt <= 0 or dt > 1.0:
            return
        self.x += vx_l * dt
        self.y += vy_l * dt

    def feed_hgt(self, ts, alt_cm):
        self.z = alt_cm - self.z0
        self.path.append((ts, self.x, self.y, self.z))

def simulate(fn, label):
    rows = load(fn)
    by_cmd = {}
    for r in rows:
        by_cmd.setdefault(r["cmd"], []).append(r)

    att  = by_cmd.get("0x03", []) + by_cmd.get("0x04", [])
    vel  = by_cmd.get("0x07", [])
    hgt  = by_cmd.get("0x05", [])

    # yaw0 = 首帧姿态
    yaw0 = att[0]["fields"]["yaw_deg"] if att else 0.0
    # z0 = 首帧高度
    z0 = hgt[0]["fields"]["alt_fu_cm"] if hgt else 0.0
    t0 = rows[0]["t_mono"]

    tracker = SimTracker(yaw0, z0)

    # 按时间序混合喂入
    events = []
    for r in vel:
        f = r["fields"]
        events.append((r["t_mono"], "vel",
                        f.get("vx_cmps",0), f.get("vy_cmps",0), f.get("vz_cmps",0)))
    for r in hgt:
        f = r["fields"]
        events.append((r["t_mono"], "hgt", f.get("alt_fu_cm",0)))
    events.sort(key=lambda e: e[0])

    for e in events:
        if e[1] == "vel":
            tracker.feed_vel(e[0], e[2], e[3], e[4])
        else:
            tracker.feed_hgt(e[0], e[2])

    # 统计路径
    xs = [p[1] for p in tracker.path]
    ys = [p[2] for p in tracker.path]
    zs = [p[3] for p in tracker.path]

    print(f"\n{'='*60}")
    print(f"  {label}  (yaw0={yaw0:.1f}°  z0={z0:.0f}cm)")
    print(f"{'='*60}")
    print(f"  模拟点数={len(tracker.path)}")
    print(f"  X(cm): [{min(xs):.1f}, {max(xs):.1f}]  最终={xs[-1]:.1f}")
    print(f"  Y(cm): [{min(ys):.1f}, {max(ys):.1f}]  最终={ys[-1]:.1f}")
    print(f"  Z(cm): [{min(zs):.1f}, {max(zs):.1f}]  最终={zs[-1]:.1f}")

    # 静止漂移：看 X/Y/Z 积累量
    dur = rows[-1]["t_mono"] - t0
    print(f"  时长={dur:.1f}s  X漂移={xs[-1]:.1f}cm  Y漂移={ys[-1]:.1f}cm")

    # 速度 bias 估计（全程均值）
    vxs = [e[2] for e in events if e[1]=="vel"]
    vys = [e[3] for e in events if e[1]=="vel"]
    vzs = [e[4] for e in events if e[1]=="vel"]
    if vxs:
        bx = sum(vxs)/len(vxs)
        by_ = sum(vys)/len(vys)
        bz = sum(vzs)/len(vzs)
        print(f"  速度均值: vx={bx:+.2f} vy={by_:+.2f} vz={bz:+.2f} cm/s")

    # 真实轨迹中点（最大位移时刻）
    xabs = [abs(p[1]) for p in tracker.path]
    if xabs:
        peak_i = xabs.index(max(xabs))
        pp = tracker.path[peak_i]
        print(f"  X峰值时刻: t={pp[0]-t0:.1f}s  X={pp[1]:.1f}cm  Y={pp[2]:.1f}cm  Z={pp[3]:.1f}cm")

    return tracker

print("=== PathTracker 轨迹模拟（重现 GUI 显示逻辑）===\n")
trackers = {}
for label, fn in FILES.items():
    trackers[label] = simulate(fn, label)

# ─── 综合诊断 ──────────────────────────────────────────────
print("\n\n" + "="*60)
print("  综合诊断结论")
print("="*60)

# BUG4：静止漂移
t_jz = trackers["静止"]
jz_path = t_jz.path
xs_jz = [p[1] for p in jz_path]
ys_jz = [p[2] for p in jz_path]
print(f"\n[BUG 4 静止漂移]")
print(f"  静止 {max(load(FILES['静止'])[-1]['t_mono']-load(FILES['静止'])[0]['t_mono'],0):.0f}s 后:")
print(f"    X 最终漂移 = {xs_jz[-1]:.1f} cm  (峰值 {max(abs(min(xs_jz)), abs(max(xs_jz))):.1f} cm)")
print(f"    Y 最终漂移 = {ys_jz[-1]:.1f} cm")
if abs(xs_jz[-1]) > 30 or abs(ys_jz[-1]) > 30:
    print(f"  ? 漂移严重 (>30cm)，velocity bias 影响大")
elif abs(xs_jz[-1]) > 10 or abs(ys_jz[-1]) > 10:
    print(f"  ? 漂移中等 (10-30cm)")
else:
    print(f"  ? 漂移轻微 (<10cm)")

# BUG5：方向分析
print(f"\n[BUG 5a 移动主轴分析]")
for key in ["x移动","y移动","z移动"]:
    t = trackers[key]
    p = t.path
    xs = [pt[1] for pt in p]
    ys = [pt[2] for pt in p]
    zs = [pt[3] for pt in p]
    rx = max(xs)-min(xs)
    ry = max(ys)-min(ys)
    rz = max(zs)-min(zs)
    dom = "X" if rx>=ry and rx>=rz else ("Y" if ry>=rz else "Z")
    print(f"  {key}: Xrange={rx:.0f}cm  Yrange={ry:.0f}cm  Zrange={rz:.0f}cm  → 主轴={dom}")

print(f"\n[BUG 5b XYZ 比例一致性]")
for key in ["x移动","y移动","z移动"]:
    t = trackers[key]
    p = t.path
    xs = [pt[1] for pt in p]
    ys = [pt[2] for pt in p]
    zs = [pt[3] for pt in p]
    rx = max(xs)-min(xs)
    ry = max(ys)-min(ys)
    rz = max(zs)-min(zs)
    total_h = max(abs(min(xs)),abs(max(xs)),abs(min(ys)),abs(max(ys)))
    print(f"  {key}: XY最大位移≈{total_h:.0f}cm  Z位移range={rz:.0f}cm(来自0x05直测)", end="")
    # 检查vz vs alt 是否一致
    rows = load(FILES[key])
    by_cmd = {}
    for r in rows:
        by_cmd.setdefault(r["cmd"], []).append(r)
    vz_mean = sum(r["fields"].get("vz_cmps",0) for r in by_cmd.get("0x07",[])) / max(1, len(by_cmd.get("0x07",[])))
    print(f"  vz均值={vz_mean:+.1f}cm/s")

print(f"\n[BUG 5c 假设：0x07 是机体系还是世界系?]")
print(f"  数据验证方法：x移动时 yaw0≈142°，若0x07是世界系，vx_world主导方向应与yaw无关。")
print(f"  若是机体系，x移动时 vx_body主导→世界系中会旋转到 yaw=142° 对应的方向。")
print(f"  x移动 yaw0={trackers['x移动'].yaw0:.1f}°：")
print(f"    cos(-yaw0)={trackers['x移动'].c:.3f}  sin(-yaw0)={trackers['x移动'].s:.3f}")
print(f"  如果 vx_cmps=+49(峰值)代表世界系东方向，去旋后:")
print(f"    vx_local = 49*{trackers['x移动'].c:.3f} = {49*trackers['x移动'].c:.1f} cm/s")
print(f"    vy_local = 49*{trackers['x移动'].s:.3f} = {49*trackers['x移动'].s:.1f} cm/s")
