# -*- coding: utf-8 -*-
"""阶段2：发送 0xF2 参数写入帧（PID3D 目标坐标运行时覆盖）+ 监听回显。

帧格式：AA FF F2 05 | id(1B) | float_LE(4B) | SC AC
白名单 ID：
    0x01 = GOAL_X (cm)
    0x02 = GOAL_Y (cm)
    0x03 = GOAL_Z (cm)
安全限幅（飞控端会再做一次）：|value| <= 500.0 cm。

回显（飞控 0xA0 字符串）：
    成功     绿  "P01=50.0"
    限幅     绿  "P01=500.0 CLP"
    白名单外 红  "P?? UNK"

注意：与 send_f1.py 一样使用 Win32 CreateFile，--baud 仅作记录。
本脚本只改 RAM 副本；飞控 PID3D 任务在每次启动（CH6 触发）时
读取一次锁定为 const，因此修改后需要触发任务重启才生效。

用法：
    python send_param.py --port COM11 --id 1 --value 30.0
    python send_param.py --port COM11 --id 2 --value -50
    python send_param.py --port COM11 --id 3 --value 0
    python send_param.py --port COM11 --id 1 --value 30 --dest 0x61
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


PARAM_NAMES = {1: "GOAL_X", 2: "GOAL_Y", 3: "GOAL_Z"}
GOAL_LIMIT_CM = 500.0


def parse_int(s: str) -> int:
    return int(s, 0)


def _color_tag(c: int) -> str:
    return {0: "BLACK", 1: "RED", 2: "GREEN"}.get(c, f"C{c}")


def build_f2(dest: int, param_id: int, value: float) -> bytes:
    """组装 0xF2 帧：DATA = id(1B) + float_LE(4B)。"""
    if not (0 <= param_id <= 0xFF):
        raise ValueError("param_id 超出 1 字节范围")
    payload = struct.pack("<Bf", param_id, value)
    return build_frame(dest, 0xF2, payload)


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
    ap.add_argument("--id", dest="param_id", type=parse_int, required=True,
                    help="参数 ID：1=GOAL_X, 2=GOAL_Y, 3=GOAL_Z")
    ap.add_argument("--value", type=float, required=True,
                    help="目标值（cm），|value| <= 500")
    ap.add_argument("--listen", type=float, default=2.0,
                    help="发送后继续监听回显的秒数，默认 2s")
    args = ap.parse_args()

    name = PARAM_NAMES.get(args.param_id, "??")
    if args.param_id not in PARAM_NAMES:
        print(f"[WARN] ID=0x{args.param_id:02X} 不在白名单（1/2/3），飞控将回 RED UNK 用于验证拒绝路径")
    if abs(args.value) > GOAL_LIMIT_CM:
        print(f"[WARN] |value|={abs(args.value):.1f} > {GOAL_LIMIT_CM:.1f}，飞控将做限幅并回 CLP")

    frame = build_f2(args.dest, args.param_id, args.value)
    print(f"[INFO] 端口={args.port} 目标=0x{args.dest:02X}")
    print(f"[INFO] 参数 ID=0x{args.param_id:02X}({name}) value={args.value}")
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
        th.join(timeout=1.0)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
