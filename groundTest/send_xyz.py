# -*- coding: utf-8 -*-
"""阶段2b：发送 0xF3 三轴目标坐标同时写入帧 + 监听回显。

帧格式：AA FF F3 0C | x_float_LE(4B) | y_float_LE(4B) | z_float_LE(4B) | SC AC
        - 总长 15B（4 帧头 + 12 数据 + 2 校验）
        - 飞控对每个轴各自做 |v|<=500cm 限幅，任一轴被限幅则回显末尾带 " CLP"

回显（飞控 0xA0 字符串）：
    成功     绿  "P*=30.0,44.0,55.0"
    任一限幅 绿  "P*=500.0,44.0,55.0 CLP"

与 send_param.py（单轴 0xF2）共用 RAM 槽位与 Getter；
飞控 PID3D 任务在每次启动（CH6 触发）时读取一次锁定为 const，
因此修改后需要触发任务重启才生效。

用法：
    python send_xyz.py --port COM11 --x 30 --y 44 --z 55
    python send_xyz.py --port COM11 --x 0 --y 0 --z 0 --dest 0x61
    python send_xyz.py --port COM11 --x 600 --y 10 --z 10   # 触发 X 轴 CLP
"""
from __future__ import annotations
import argparse
import struct
import threading
import time
import sys

from ano_protocol import (
    ADDR_BROADCAST,
    FrameParser,
    build_frame,
    hex_dump,
)
from win_serial import Win32Serial


GOAL_LIMIT_CM = 500.0


def parse_int(s: str) -> int:
    return int(s, 0)


def _color_tag(c: int) -> str:
    return {0: "BLACK", 1: "RED", 2: "GREEN"}.get(c, f"C{c}")


def build_f3(dest: int, gx: float, gy: float, gz: float) -> bytes:
    """组装 0xF3 帧：DATA = float_LE * 3 = 12B。"""
    payload = struct.pack("<fff", gx, gy, gz)
    return build_frame(dest, 0xF3, payload)


def reader_thread(ser: Win32Serial, stop_evt: threading.Event):
    parser = FrameParser()
    while not stop_evt.is_set():
        try:
            chunk = ser.read_nonblocking(max_bytes=4096, wait_s=0.05)
        except OSError as e:
            print(f"[ERR] 串口读取失败: {e}", file=sys.stderr)
            return
        if not chunk:
            continue
        for f in parser.feed(chunk):
            cs = f.color_str()
            if cs is not None:
                color, text = cs
                print(f"[RX 0xA0 {_color_tag(color)}] {text}")
            else:
                print(
                    f"[RX] dest=0x{f.dest:02X} cmd=0x{f.cmd:02X} "
                    f"len={len(f.data)} data={hex_dump(f.data)}"
                )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="串口号，例如 COM11")
    ap.add_argument("--baud", type=int, default=500000,
                    help="仅供参考，本脚本不调 SetCommState")
    ap.add_argument("--dest", type=parse_int, default=ADDR_BROADCAST,
                    help="目标地址（默认 0xFF 广播）。0x61=STM32飞控")
    ap.add_argument("--x", type=float, required=True, help="GOAL_X (cm)")
    ap.add_argument("--y", type=float, required=True, help="GOAL_Y (cm)")
    ap.add_argument("--z", type=float, required=True, help="GOAL_Z (cm)")
    ap.add_argument("--listen", type=float, default=2.0,
                    help="发送后继续监听回显的秒数，默认 2s")
    args = ap.parse_args()

    for axis, v in (("X", args.x), ("Y", args.y), ("Z", args.z)):
        if abs(v) > GOAL_LIMIT_CM:
            print(f"[WARN] |{axis}|={abs(v):.1f} > {GOAL_LIMIT_CM:.1f}，飞控将对该轴限幅并回 CLP")

    frame = build_f3(args.dest, args.x, args.y, args.z)
    print(f"[INFO] 端口={args.port} 目标=0x{args.dest:02X}")
    print(f"[INFO] 三轴目标: X={args.x} Y={args.y} Z={args.z} (cm)")
    print(f"[INFO] 帧({len(frame)}B): {hex_dump(frame)}")

    ser = Win32Serial(args.port)
    ser.open()
    try:
        stop_evt = threading.Event()
        th = threading.Thread(target=reader_thread, args=(ser, stop_evt), daemon=True)
        th.start()

        ser.write(frame)
        print(f"[INFO] 单帧已发出，监听 {args.listen} 秒...")
        time.sleep(args.listen)

        stop_evt.set()
        th.join(timeout=0.5)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
