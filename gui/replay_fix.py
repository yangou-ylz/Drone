# -*- coding: utf-8 -*-
"""用真实 jsonl 离线重放 PathTracker，验证修复后 4 个场景的末位漂移。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gui.services.path_tracker import PathTracker
from gui.services.telemetry_decoder import (
    decode_attitude_euler, decode_attitude_quat, decode_velocity, decode_height,
)

DATA_DIR = Path(__file__).parent / "data"
FILES = [
    "静止20260527_123106.jsonl",
    "向前20260527_123244.jsonl",
    "向左20260527_123311.jsonl",
    "顺时针90°20260527_123356.jsonl",
]


def replay(name, dump_yaw=False):
    tracker = PathTracker()
    tracker.enable()
    max_dist = 0.0
    n_points = 0
    yaw_imu_first = yaw_imu_last = None
    yaw_render_first = yaw_render_last = None
    static_yaw_window = []  # 末 5 秒内 render yaw 的极差
    last_ts = None
    with (DATA_DIR / name).open("r", encoding="utf-8") as f:
        lines = f.readlines()
    # 先确定数据 t 区间，用于"末 5 秒"判定
    t_end = None
    for line in lines:
        line = line.strip()
        if not line: continue
        obj = json.loads(line)
        if obj.get("_meta"): continue
        if 't_mono' in obj: t_end = obj['t_mono']
    for line in lines:
        line = line.strip()
        if not line:
            continue
        obj = json.loads(line)
        if obj.get("_meta"):
            continue
        cmd = obj.get("cmd")
        data = bytes.fromhex(obj["hex"])
        ts = obj["t_mono"]
        last_ts = ts
        if cmd == "0x03":
            s = decode_attitude_euler(data, ts=ts)
            if s: tracker.on_attitude(s)
        elif cmd == "0x04":
            s = decode_attitude_quat(data, ts=ts)
            if s: tracker.on_attitude(s)
        elif cmd == "0x05":
            s = decode_height(data, ts=ts)
            if s: tracker.on_height(s)
        elif cmd == "0x07":
            s = decode_velocity(data, ts=ts)
            if s: tracker.on_velocity(s)
        # 每次 0x03/0x04 后看一次渲染 yaw
        if cmd in ("0x03", "0x04"):
            snap = tracker.snapshot()
            imu_yaw = tracker._latest_attitude.yaw_deg if tracker._latest_attitude else 0.0
            render_yaw = snap.attitude_deg[2]
            if yaw_imu_first is None:
                yaw_imu_first = imu_yaw
                yaw_render_first = render_yaw
            yaw_imu_last = imu_yaw
            yaw_render_last = render_yaw
            # 末 5 秒数据
            if t_end and ts > t_end - 5.0:
                static_yaw_window.append((ts, imu_yaw, render_yaw, False))
    snap = tracker.snapshot()
    for p in snap.points:
        d = (p.x_cm**2 + p.y_cm**2) ** 0.5
        if d > max_dist:
            max_dist = d
        n_points += 1
    if dump_yaw:
        # 计算末 5s 区间 imu yaw 极差和 render yaw 极差
        if static_yaw_window:
            imu_ys = [imu for _, imu, _, _ in static_yaw_window]
            ren_ys = [r for _, _, r, _ in static_yaw_window]
            locks = sum(1 for _, _, _, lk in static_yaw_window if lk)
            print(f"    [末5s] IMU yaw 极差={max(imu_ys)-min(imu_ys):+.2f}° / render yaw 极差={max(ren_ys)-min(ren_ys):+.2f}° / 锁定帧={locks}/{len(static_yaw_window)}")
    return snap.pos_cm, max_dist, n_points


if __name__ == "__main__":
    print("=== 修复后离线重放结果 ===")
    print(f"{'场景':12s} {'末位 X/Y':22s} {'轨迹最远':8s}  点数")
    for name in FILES:
        (x, y, z), mx, n = replay(name, dump_yaw=True)
        print(f"  {name[:10]:10s}  ({x:+6.1f},{y:+6.1f},{z:+6.1f})cm  {mx:6.1f}cm  n={n}")
