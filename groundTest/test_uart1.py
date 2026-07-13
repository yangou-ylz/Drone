# -*- coding: utf-8 -*-
"""
test_uart1.py — 凌霄飞控 UART1 姿态帧读取测试
==================================================
STM32 通过 UART1 (PA9, 115200baud, 8N1) 以 20Hz 转发匿名协议帧：
  0x03  姿态欧拉角  ROL/PIT/YAW（单位 0.01°）
  0x07  飞行速度    vx/vy/vz（单位 cm/s）
  0x06  飞控状态    mode/locked

用法：
  py -3 test_uart1.py                  # 默认 COM15
  py -3 test_uart1.py --port COM5      # 指定端口
  py -3 test_uart1.py --port COM5 --time 30   # 运行30秒退出

硬件接线：
  STM32 PA9 (UART1_TX) → USB转串口 RX
  STM32 GND            → USB转串口 GND
  （不需要接 PA10/RX，只监听 STM32 发出方向即可）
"""

import serial
import struct
import time
import sys
from collections import defaultdict

# ── 默认配置 ──────────────────────────────────────────────────
PORT     = "COM15"   # 改为你的实际端口
BAUDRATE = 115200    # UART1 由 Init_GPS() 最终设定为 115200
# ─────────────────────────────────────────────────────────────

def sc_ac_ok(buf):
    """验证 ANO 协议 SC/AC 校验（覆盖 buf[0..LEN+3]）"""
    ln = buf[3]
    if len(buf) < ln + 6:
        return False
    sc = ac = 0
    for i in range(ln + 4):
        sc = (sc + buf[i]) & 0xFF
        ac = (ac + sc) & 0xFF
    return sc == buf[ln + 4] and ac == buf[ln + 5]

def s16(b, off):  return struct.unpack_from('<h', b, off)[0]
def u16(b, off):  return struct.unpack_from('<H', b, off)[0]

def decode(cmd, payload):
    p = bytes(payload)
    try:
        if cmd == 0x03 and len(p) >= 6:
            rol = s16(p, 0) * 0.01
            pit = s16(p, 2) * 0.01
            yaw = s16(p, 4) * 0.01
            sta = p[6] if len(p) >= 7 else -1
            return f"ROL={rol:+7.2f}  PIT={pit:+7.2f}  YAW={yaw:+7.2f}  (deg)  sta={sta}"

        if cmd == 0x07 and len(p) >= 6:
            vx = s16(p, 0); vy = s16(p, 2); vz = s16(p, 4)
            return f"VX={vx:+5d}  VY={vy:+5d}  VZ={vz:+5d}  (cm/s)"

        if cmd == 0x06 and len(p) >= 2:
            mode = p[0]; lock = p[1]
            modes = {0:"姿态", 1:"定高", 2:"定点", 3:"程控"}
            return f"mode={modes.get(mode, f'?{mode}')}  {'解锁' if lock else '上锁'}"
    except Exception as e:
        return f"[err:{e}]"

    return "  ".join(f"{b:02X}" for b in payload)

NAME = {0x03:"姿态", 0x06:"状态", 0x07:"速度"}

def run(port, baudrate, run_sec):
    print("=" * 62)
    print(f"  UART1 姿态帧测试  |  {port}  @  {baudrate} baud")
    print(f"  STM32 每 50ms 发一组帧（20Hz），共 3 种：0x03/0x07/0x06")
    print("=" * 62)

    try:
        ser = serial.Serial(port, baudrate, timeout=0.05)
    except serial.SerialException as e:
        print(f"\n[错误] 无法打开 {port}: {e}")
        print("请确认：1) 飞控已上电  2) USB转串口已插好  3) 端口号正确")
        return

    buf = bytearray()
    ok = err = 0
    cnt = defaultdict(int)
    t_stat = time.time()
    t_start = time.time()
    last_print = defaultdict(float)

    # 同类帧限频，0.5秒打一次（避免刷屏）
    INTERVAL = {0x03: 0.5, 0x07: 0.5, 0x06: 1.0}

    print("\n等待数据...\n")
    try:
        while True:
            chunk = ser.read(256)
            if chunk:
                buf.extend(chunk)

            while len(buf) >= 6:
                idx = buf.find(0xAA)
                if idx == -1:
                    buf.clear(); break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) < 4:
                    break
                ln   = buf[3]
                need = ln + 6
                if len(buf) < need:
                    break
                frame = buf[:need]
                buf   = buf[need:]

                if sc_ac_ok(frame):
                    ok += 1
                    cmd     = frame[2]
                    payload = list(frame[4:4 + ln])
                    cnt[cmd] += 1

                    now = time.time()
                    if now - last_print[cmd] >= INTERVAL.get(cmd, 0.3):
                        last_print[cmd] = now
                        name   = NAME.get(cmd, f"0x{cmd:02X}")
                        detail = decode(cmd, payload)
                        print(f"  [0x{cmd:02X} {name}]  {detail}")
                else:
                    err += 1
                    buf = buf[1:]

            # 每 5 秒打一次统计
            now = time.time()
            if now - t_stat >= 5:
                t_stat = now
                print(f"\n  ── 统计：正确帧={ok}  错误帧={err} ──")
                if ok == 0 and err == 0:
                    print("  ?  无数据 → 检查接线/飞控是否上电/端口号是否正确")
                elif ok == 0:
                    print("  ?  有字节但校验全错 → 波特率不对（应为115200）或线接错")
                for c in sorted(cnt):
                    print(f"    [0x{c:02X}] {NAME.get(c,'?'):4s}: {cnt[c]} 帧")
                print()

            if run_sec and (time.time() - t_start) >= run_sec:
                break

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n  结束  正确帧={ok}  错误帧={err}")
        ser.close()

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--baud", type=int, default=BAUDRATE)
    ap.add_argument("--time", type=int, default=0, help="运行秒数(0=无限)")
    args = ap.parse_args()
    run(args.port, args.baud, args.time)
