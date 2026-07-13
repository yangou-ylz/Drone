# -*- coding: utf-8 -*-
"""
凌霄飞控 UART5/UT5 串口数据帧解析测试
用途：直接监听 STM32?凌霄IMU 通信线，解析匿名协议帧

连接参数（来自工程源码 Drv_BSP.c DrvUart5Init(500000)）：
  波特率: 500000
  数据位: 8
  停止位: 1
  校验:   None（8N1）
  流控:   无

运行方式:
  python read_uart5.py
  python read_uart5.py --port COM15 --time 30

注意：你接的是 STM32 UART5 的 TX（PC12）或 RX（PD2）引脚？
  - 只接 IMU_TX→STM32_RX 那根线（即 STM32_PC12 一侧）：只能看到 STM32 发给 IMU 的帧
  - 只接 IMU_RX→STM32_TX 那根线（即 STM32_PD2 一侧）：只能看到 IMU 发给 STM32 的帧
  - 如果 UT5 外引口是两根线都并联出来的，两个方向的帧都会看到
"""

import serial
import struct
import time
import sys
from collections import defaultdict

# ── 配置 ──────────────────────────────────────────────────────
PORT     = "COM15"
BAUDRATE = 500000
RUN_SEC  = 0        # 运行秒数，0 = 一直跑直到 Ctrl+C

# 只打印这些帧 ID（空列表 = 打印全部已解码帧）
SHOW_IDS = []       # 例如 [0x03, 0x06, 0x07] 只看姿态+状态+速度
# ──────────────────────────────────────────────────────────────

# 帧 ID → 名称
FRAME_NAMES = {
    0x01: "惯性传感器",
    0x02: "气压/罗盘",
    0x03: "姿态欧拉角",
    0x04: "姿态四元数",
    0x05: "融合高度",
    0x06: "飞控状态",
    0x07: "飞行速度",
    0x08: "XY位移",
    0x09: "风速",
    0x0A: "目标姿态",
    0x0B: "目标速度",
    0x0D: "电池",
    0x0E: "外接模块状态",
    0x0F: "RGB LED",
    0x20: "电机PWM",
    0x21: "姿态控制量",
    0x32: "通用位置上报",
    0x33: "通用速度上报",
    0x34: "通用测距上报",
    0x40: "遥控器数据",
    0x41: "实时控制帧",
    0x51: "光流数据",
    0xA0: "字符串LOG",
    0xE0: "CMD命令",
    0xE2: "参数写入",
    0x00: "CK返回",
}

# 地址 → 名称
ADDR_NAMES = {
    0xFF: "广播",
    0x60: "凌霄IMU",
    0x61: "STM32飞控板",
    0xAF: "上位机",
    0x10: "匿名数传",
    0x22: "匿名光流",
    0x30: "匿名UWB",
}


def sc_ac_check(buf):
    """验证 SC/AC 校验：覆盖 buf[0]~buf[LEN+3] 共 LEN+4 字节"""
    ln = buf[3]
    if len(buf) < ln + 6:
        return False
    sc = ac = 0
    for i in range(ln + 4):
        sc = (sc + buf[i]) & 0xFF
        ac = (ac + sc) & 0xFF
    return sc == buf[ln + 4] and ac == buf[ln + 5]


def s16(b, off):
    return struct.unpack_from('<h', b, off)[0]

def u16(b, off):
    return struct.unpack_from('<H', b, off)[0]

def s32(b, off):
    return struct.unpack_from('<i', b, off)[0]

def u32(b, off):
    return struct.unpack_from('<I', b, off)[0]


def decode_payload(cmd, payload):
    """
    将 DATA 字节列表解码为可读字符串。
    字段偏移直接对应 DATA（即 buf[4] 起的字节）。
    """
    p = bytes(payload)
    n = len(p)
    try:
        if cmd == 0x03 and n >= 7:   # 姿态欧拉角
            rol = s16(p, 0) * 0.01
            pit = s16(p, 2) * 0.01
            yaw = s16(p, 4) * 0.01
            sta = p[6]
            return f"rol={rol:+7.2f}°  pit={pit:+7.2f}°  yaw={yaw:+7.2f}°  fusion={sta}"

        elif cmd == 0x04 and n >= 9: # 四元数
            q = [s16(p, i*2) * 0.0001 for i in range(4)]
            return f"q=[{q[0]:.4f}, {q[1]:.4f}, {q[2]:.4f}, {q[3]:.4f}]  sta={p[8]}"

        elif cmd == 0x05 and n >= 9: # 融合高度
            alt_fu  = s32(p, 0)
            alt_add = s32(p, 4)
            sta = p[8]
            return f"alt_fused={alt_fu}cm  alt_add={alt_add}cm  sta={sta}"

        elif cmd == 0x06 and n >= 5: # 飞控状态
            mode = p[0]
            lock = p[1]
            cid  = p[2]
            cmd0 = p[3]
            cmd1 = p[4]
            mode_str = {0:"姿态", 1:"定高", 2:"定点", 3:"程控"}.get(mode, f"?{mode}")
            lock_str = "解锁" if lock else "上锁"
            return f"mode={mode_str}({mode})  {lock_str}  CID=0x{cid:02X} CMD0={cmd0} CMD1={cmd1}"

        elif cmd == 0x07 and n >= 6: # 飞行速度
            vx = s16(p, 0)
            vy = s16(p, 2)
            vz = s16(p, 4)
            return f"vx={vx:+5d}cm/s  vy={vy:+5d}cm/s  vz={vz:+5d}cm/s"

        elif cmd == 0x08 and n >= 8: # XY位移
            px = s32(p, 0)
            py = s32(p, 4)
            return f"pos_x={px}cm  pos_y={py}cm"

        elif cmd == 0x09 and n >= 4: # 风速
            wx = s16(p, 0)
            wy = s16(p, 2)
            return f"wind_x={wx}cm/s  wind_y={wy}cm/s"

        elif cmd == 0x0D and n >= 4: # 电池
            volt = u16(p, 0) * 0.01
            curr = u16(p, 2) * 0.01
            return f"电压={volt:.2f}V  电流={curr:.2f}A"

        elif cmd == 0x0E and n >= 4: # 外接模块状态
            sta_map = {0:"无数据", 1:"不可用", 2:"正常", 3:"良好"}
            gvel = sta_map.get(p[0], f"?{p[0]}")
            gpos = sta_map.get(p[1], f"?{p[1]}")
            gps  = sta_map.get(p[2], f"?{p[2]}")
            alt  = sta_map.get(p[3], f"?{p[3]}")
            return f"通速={gvel}  通位={gpos}  GPS={gps}  辅高={alt}"

        elif cmd == 0x20:            # 电机PWM（8~16字节）
            n_pwm = n // 2
            pwms = [u16(p, i*2) for i in range(n_pwm)]
            s = "  ".join(f"M{i+1}={v}" for i, v in enumerate(pwms))
            return s

        elif cmd == 0x40 and n >= 20: # 遥控器数据（STM32→IMU方向）
            chs = [s16(p, i*2) for i in range(10)]
            names = ['ROL','PIT','THR','YAW','AUX1','AUX2','AUX3','AUX4','AUX5','AUX6']
            if all(c == 0 for c in chs):
                return "(全0 = 无遥控信号)"
            parts = [f"{names[i]}={chs[i]}" for i in range(6) if chs[i] != 0]
            return "  ".join(parts) if parts else "(全0)"

        elif cmd == 0x41 and n >= 14: # 实时控制帧
            rol    = s16(p,  0) * 0.01
            pit    = s16(p,  2) * 0.01
            thr    = s16(p,  4) * 0.1
            yaw    = s16(p,  6)
            vel_x  = s16(p,  8)
            vel_y  = s16(p, 10)
            vel_z  = s16(p, 12)
            return (f"rol={rol:.2f}° pit={pit:.2f}° thr={thr:.1f}% "
                    f"yaw={yaw}°/s  vel=({vel_x},{vel_y},{vel_z})cm/s")

        elif cmd == 0xA0 and n >= 1: # 字符串 LOG
            color = {0:"黑", 1:"红", 2:"绿"}.get(p[0], f"?{p[0]}")
            text  = p[1:].decode('gbk', errors='replace').rstrip('\x00')
            return f"[{color}] {text}"

        elif cmd == 0x00 and n >= 3: # CK 返回
            return f"CK for ID=0x{p[0]:02X}  SC={p[1]:02X}  AC={p[2]:02X}"

        elif cmd == 0x01 and n >= 13: # 惯性传感器
            ax = s16(p, 0); ay = s16(p, 2); az = s16(p, 4)
            gx = s16(p, 6); gy = s16(p, 8); gz = s16(p, 10)
            sh = p[12]
            return (f"ACC=({ax},{ay},{az})  "
                    f"GYR=({gx},{gy},{gz})  shock={sh}")

        elif cmd == 0x02 and n >= 14: # 气压/罗盘
            mx  = s16(p,  0); my = s16(p, 2); mz = s16(p, 4)
            alt = s32(p,  6)
            tmp = s16(p, 10) * 0.1
            return f"MAG=({mx},{my},{mz})  BAR={alt}cm  TMP={tmp:.1f}°C"

    except Exception as ex:
        return f"[解码错误:{ex}]"

    # 未匹配：返回原始 hex
    return "  ".join(f"{b:02X}" for b in payload)


def run(port, baudrate, run_sec):
    print(f"{'='*65}")
    print(f"  凌霄 UART5 帧解析测试")
    print(f"  端口: {port}   波特率: {baudrate}   格式: 8N1")
    if run_sec:
        print(f"  运行 {run_sec} 秒后自动退出，按 Ctrl+C 可提前退出")
    else:
        print(f"  按 Ctrl+C 退出")
    print(f"{'='*65}")
    print("  接线方向说明:")
    print("  ├─ 接 PC12(UART5_TX) → 看 STM32→IMU 方向: 0x40遥控/0x0D电池/0x41控制")
    print("  └─ 接 PD2 (UART5_RX) → 看 IMU→STM32 方向: 0x03姿态/0x07速度/0x05高度")
    print(f"{'='*65}")

    try:
        ser = serial.Serial(port, baudrate, timeout=0.05)
    except serial.SerialException as e:
        print(f"\n[错误] 串口打开失败: {e}")
        print("\n如果报 PermissionError / Access Denied → 串口被占用，关掉其他程序")
        print("如果报错误代码31 → 换成下面的 Win32 直连方式（见脚本末尾注释）")
        return

    buf        = bytearray()
    total_ok   = 0
    total_err  = 0
    stats      = defaultdict(int)
    last_stat  = time.time()
    start_time = time.time()

    # 每个帧 ID 最近一次解码结果，用于限频显示
    last_print = defaultdict(float)
    PRINT_INTERVAL = {
        0x03: 0.5,   # 姿态：每0.5秒打一次
        0x07: 0.5,   # 速度
        0x05: 0.5,   # 高度
        0x0D: 5.0,   # 电池：5秒一次（减少刷屏）
        0x06: 1.0,   # 状态：1秒一次
        0x20: 0.5,   # PWM
        0x08: 0.5,   # XY位移
        0x0E: 2.0,   # 模块状态
        0x01: 1.0,   # 惯性
        0x02: 1.0,   # 气压
        0x40: 2.0,   # 遥控器：2秒一次（减少刷屏）
        0x41: 0.5,   # 实时控制
    }
    DEFAULT_INTERVAL = 0.5

    print("\n[开始接收]\n")
    try:
        while True:
            chunk = ser.read(512)
            if chunk:
                buf.extend(chunk)

            # ── 帧同步 & 解析 ──
            while len(buf) >= 6:
                idx = buf.find(0xAA)
                if idx == -1:
                    buf.clear()
                    break
                if idx > 0:
                    buf = buf[idx:]
                if len(buf) < 4:
                    break

                ln   = buf[3]
                need = ln + 6  # AA + dest + cmd + LEN + data[LEN] + SC + AC
                if len(buf) < need:
                    break

                frame = buf[:need]
                buf   = buf[need:]

                if sc_ac_check(frame):
                    total_ok += 1
                    cmd     = frame[2]
                    dest    = frame[1]
                    payload = list(frame[4:4 + ln])
                    stats[cmd] += 1

                    # 是否在过滤列表里
                    if SHOW_IDS and cmd not in SHOW_IDS:
                        continue

                    now = time.time()
                    interval = PRINT_INTERVAL.get(cmd, DEFAULT_INTERVAL)
                    if now - last_print[cmd] < interval:
                        continue
                    last_print[cmd] = now

                    dest_str  = ADDR_NAMES.get(dest,  f"0x{dest:02X}")
                    frame_str = FRAME_NAMES.get(cmd,   f"未知0x{cmd:02X}")
                    detail    = decode_payload(cmd, payload)
                    # 方向标签：dest=0x61/STM32 说明是IMU发出的，其余是STM32发出的
                    if dest == 0x61:
                        direction = "IMU→STM32"
                    elif cmd in (0x03,0x04,0x05,0x06,0x07,0x08,0x09,0x0A,0x0B,0x0C,0x0D,0x0E,0x0F,0x20,0x21):
                        direction = "IMU→STM32"
                    else:
                        direction = "STM32→IMU"

                    print(f"[{direction}][0x{cmd:02X}] {frame_str:<10s}  LEN={ln:2d}  {detail}")
                else:
                    total_err += 1
                    buf = buf[1:]  # 跳一字节，重新同步帧头

            # ── 每 5 秒打一次统计 ──
            now = time.time()
            if now - last_stat >= 5:
                last_stat = now
                print(f"\n{'─'*65}")
                print(f"  统计 | 正确帧: {total_ok}  校验错误帧: {total_err}")
                if total_ok == 0 and total_err == 0:
                    print("  ?  尚未收到任何数据 → 检查接线和波特率")
                elif total_ok == 0:
                    print("  ?  有字节但全部校验失败 → 波特率可能不对，或线接错方向")
                for c, cnt in sorted(stats.items()):
                    name = FRAME_NAMES.get(c, f"未知0x{c:02X}")
                    print(f"    0x{c:02X}  {name:<14s}: {cnt} 次")
                print(f"{'─'*65}\n")

            # 超时退出
            if run_sec and (time.time() - start_time) >= run_sec:
                break

    except KeyboardInterrupt:
        pass
    finally:
        print(f"\n{'='*65}")
        print(f"  结束 | 正确帧: {total_ok}  校验错误帧: {total_err}")
        ser.close()
        print(f"{'='*65}")


# ── 命令行参数解析 ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="凌霄UART5帧解析")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--baud", type=int, default=BAUDRATE)
    ap.add_argument("--time", type=int, default=RUN_SEC, help="运行秒数，0=无限")
    ap.add_argument("--show", nargs="*", help="只显示哪些帧ID，如 --show 0x03 0x06")
    args = ap.parse_args()

    if args.show:
        SHOW_IDS = [int(x, 16) for x in args.show]

    run(args.port, args.baud, args.time)

# ── Win32 备用方案（如果 pyserial 报错 31）──────────────────────
# import ctypes, ctypes.wintypes
# class Win32Serial:
#     def __init__(self, port, baud):
#         self._h = ctypes.windll.kernel32.CreateFileW(
#             f"\\\\.\\{port}", 0xC0000000, 0, None, 3, 0, None)
#         timeouts = (ctypes.c_ulong * 5)(0, 0, 0, 0, 0)
#         ctypes.windll.kernel32.SetCommTimeouts(self._h, ctypes.byref(
#             (ctypes.c_ulong * 5)(1,0,1,0,1)))
#     def read(self, n):
#         buf = ctypes.create_string_buffer(n)
#         got = ctypes.c_ulong(0)
#         ctypes.windll.kernel32.ReadFile(self._h, buf, n, ctypes.byref(got), None)
#         return bytes(buf.raw[:got.value])
#     def close(self):
#         ctypes.windll.kernel32.CloseHandle(self._h)
