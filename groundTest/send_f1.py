# -*- coding: utf-8 -*-
"""发送 0xF1 灵活帧（阶段1链路验证）+ 同步监听回显。

注意：本脚本使用 Win32 CreateFile 直接打开 COM 口（绕过 SetCommState），
适配匿名数传等驱动固化波特率的设备。--baud 参数仅作记录、不会被驱动接受。

用法：
    python send_f1.py --port COM11 --x 1234 --y -4562
    python send_f1.py --port COM11 --x 100 --y 200 --rate 10 --duration 60
    python send_f1.py --port COM11 --x 100 --y 200 --dest 0x61
"""
from __future__ import annotations
import argparse
import threading
import time
import sys

from ano_protocol import (
    ADDR_BROADCAST,
    FrameParser,
    build_f1_xy,
    hex_dump,
)
from win_serial import Win32Serial


def parse_int(s: str) -> int:
    return int(s, 0)


def _color_tag(c: int) -> str:
    return {0: "BLACK", 1: "RED", 2: "GREEN"}.get(c, f"C{c}")


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
                    help="仅供参考，本脚本不调 SetCommState，波特率由驱动固化")
    ap.add_argument("--dest", type=parse_int, default=ADDR_BROADCAST,
                    help="目标地址（默认 0xFF 广播）。0x61=STM32飞控")
    ap.add_argument("--x", type=int, required=True, help="S16 X 字段")
    ap.add_argument("--y", type=int, required=True, help="S16 Y 字段")
    ap.add_argument("--rate", type=float, default=0.0,
                    help="连发频率 Hz；0=单帧（默认）")
    ap.add_argument("--duration", type=float, default=3.0,
                    help="rate>0 时连发总时长秒；rate=0 时为发完后监听时长。默认 3s")
    args = ap.parse_args()

    frame = build_f1_xy(args.dest, args.x, args.y)
    print(f"[INFO] 端口={args.port} 目标=0x{args.dest:02X}（驱动固化波特率，--baud {args.baud} 仅记录）")
    print(f"[INFO] 帧({len(frame)}B): {hex_dump(frame)}")

    ser = Win32Serial(args.port)
    ser.open()
    try:
        stop_evt = threading.Event()
        th = threading.Thread(target=reader_thread, args=(ser, stop_evt), daemon=True)
        th.start()

        if args.rate > 0:
            interval = 1.0 / args.rate
            t_end = time.time() + args.duration
            n = 0
            print(f"[INFO] 以 {args.rate} Hz 连发 {args.duration} 秒...")
            while time.time() < t_end:
                ser.write(frame)
                n += 1
                time.sleep(interval)
            print(f"[INFO] 共发出 {n} 帧。继续监听 1s 收尾...")
            time.sleep(1.0)
        else:
            ser.write(frame)
            print(f"[INFO] 单帧已发出，监听 {args.duration} 秒...")
            time.sleep(args.duration)

        stop_evt.set()
        th.join(timeout=1.0)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
