# -*- coding: utf-8 -*-
"""发送 0xF5 树莓派位置帧并监听 STM32 0xA0 ACK/日志。

树莓派推荐用法：
    python3 send_f5.py --port /dev/serial/by-id/xxx --cur 0,0,80 --tar 100,0,80
    python3 send_f5.py --port /dev/ttyUSB0 --cur 0,0,0 --tar 0,100,0 --rate 10 --duration 5

第一阶段只验证通信和坐标方向：STM32 端只解析/回日志，不接 PID、不控飞。
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import platform
import sys
import threading
import time
from pathlib import Path

from ano_protocol import (
    ADDR_FC_STM32,
    FLAG_SLAM_VALID,
    FLAG_TARGET_VALID,
    FLAG_VISUAL_MODE,
    FrameParser,
    build_f5_position,
    hex_dump,
)


def parse_int(s: str) -> int:
    return int(s, 0)


def parse_xyz(s: str) -> tuple[float, float, float]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected X,Y,Z, for example 0,0,80")
    try:
        return float(parts[0]), float(parts[1]), float(parts[2])
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _color_tag(c: int) -> str:
    return {0: "BLACK", 1: "RED", 2: "GREEN"}.get(c, f"C{c}")


def setup_logger(log_file: str) -> logging.Logger:
    logger = logging.getLogger("send_f5")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    path = Path(log_file)
    if path.parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    return logger


def open_serial(port: str, baud: int):
    if platform.system().lower().startswith("win") or port.upper().startswith("COM"):
        from win_serial import Win32Serial

        ser = Win32Serial(port)
    else:
        from linux_serial import LinuxSerial

        ser = LinuxSerial(port, baud)
    ser.open()
    return ser


def reader_thread(ser, stop_evt: threading.Event, logger: logging.Logger):
    parser = FrameParser()
    while not stop_evt.is_set():
        try:
            chunk = ser.read_nonblocking(max_bytes=4096, wait_s=0.05)
        except Exception as exc:
            logger.error("serial read failed: %s", exc)
            return
        if not chunk:
            continue
        for frame in parser.feed(chunk):
            color_text = frame.color_str()
            if color_text is not None:
                color, text = color_text
                logger.info("[RX 0xA0 %s] %s", _color_tag(color), text)
            else:
                logger.info(
                    "[RX] dest=0x%02X cmd=0x%02X len=%d data=%s",
                    frame.dest,
                    frame.cmd,
                    len(frame.data),
                    hex_dump(frame.data),
                )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True, help="串口，如 /dev/ttyUSB0 或 /dev/serial/by-id/xxx")
    ap.add_argument("--baud", type=int, default=500000, help="默认 500000")
    ap.add_argument("--dest", type=parse_int, default=ADDR_FC_STM32, help="默认 0x61=STM32")
    ap.add_argument("--cur", type=parse_xyz, required=True, help="当前位置 cm，格式 X,Y,Z")
    ap.add_argument("--tar", type=parse_xyz, required=True, help="目标位置 cm，格式 X,Y,Z")
    ap.add_argument("--visual", action="store_true", help="置位 VISUAL_MODE")
    ap.add_argument("--slam-invalid", action="store_true", help="清除 SLAM_VALID，用于失效测试")
    ap.add_argument("--target-invalid", action="store_true", help="清除 TARGET_VALID，用于失效测试")
    ap.add_argument("--rate", type=float, default=0.0, help="连发频率 Hz；0=单帧")
    ap.add_argument("--duration", type=float, default=3.0, help="发送/监听时长秒")
    ap.add_argument("--log-file", default="logs/send_f5.log", help="日志文件路径")
    args = ap.parse_args()

    logger = setup_logger(args.log_file)

    flags = 0
    if not args.slam_invalid:
        flags |= FLAG_SLAM_VALID
    if not args.target_invalid:
        flags |= FLAG_TARGET_VALID
    if args.visual:
        flags |= FLAG_VISUAL_MODE

    frame = build_f5_position(args.dest, *args.cur, *args.tar, flags)
    logger.info("port=%s baud=%d dest=0x%02X flags=0x%02X", args.port, args.baud, args.dest, flags)
    logger.info("frame(%dB)=%s", len(frame), hex_dump(frame))

    ser = open_serial(args.port, args.baud)
    stop_evt = threading.Event()
    th = threading.Thread(target=reader_thread, args=(ser, stop_evt, logger), daemon=True)
    th.start()

    try:
        if args.rate > 0.0:
            interval = 1.0 / args.rate
            end_time = time.monotonic() + args.duration
            tx_cnt = 0
            while time.monotonic() < end_time:
                ser.write(frame)
                tx_cnt += 1
                logger.info("[TX #%d] 0xF5 cur=%s tar=%s flags=0x%02X", tx_cnt, args.cur, args.tar, flags)
                time.sleep(interval)
            time.sleep(1.0)
        else:
            ser.write(frame)
            logger.info("[TX #1] 0xF5 cur=%s tar=%s flags=0x%02X", args.cur, args.tar, flags)
            time.sleep(args.duration)
    finally:
        stop_evt.set()
        th.join(timeout=1.0)
        ser.close()
        logger.info("serial closed")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
