# -*- coding: utf-8 -*-
"""持续监听串口，解析所有入站匿名协议帧并打印。

使用 Win32 CreateFile 后端，--baud 仅作记录。

用法：
    python monitor.py --port COM11
    python monitor.py --port COM11 --filter 0xA0   # 仅打印 0xA0 字符串帧
"""
from __future__ import annotations
import argparse

from ano_protocol import FrameParser, hex_dump
from win_serial import Win32Serial


def parse_int(s: str) -> int:
    return int(s, 0)


def _color_tag(c: int) -> str:
    return {0: "BLACK", 1: "RED", 2: "GREEN"}.get(c, f"C{c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--baud", type=int, default=500000, help="仅供参考")
    ap.add_argument("--filter", type=parse_int, default=None,
                    help="只显示指定 CMD 的帧，例如 0xA0")
    args = ap.parse_args()

    print(f"[INFO] 监听 {args.port}，Ctrl+C 退出")
    ser = Win32Serial(args.port)
    ser.open()
    parser = FrameParser()
    try:
        while True:
            chunk = ser.read_nonblocking(max_bytes=4096, wait_s=0.1)
            if not chunk:
                continue
            for f in parser.feed(chunk):
                if args.filter is not None and f.cmd != args.filter:
                    continue
                cs = f.color_str()
                if cs is not None:
                    color, text = cs
                    print(f"[0xA0 {_color_tag(color)}] {text}")
                else:
                    print(
                        f"dest=0x{f.dest:02X} cmd=0x{f.cmd:02X} "
                        f"len={len(f.data):3d} data={hex_dump(f.data)}"
                    )
    except KeyboardInterrupt:
        print("\n[INFO] 退出。")
    finally:
        ser.close()


if __name__ == "__main__":
    main()
