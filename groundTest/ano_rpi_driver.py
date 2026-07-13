# -*- coding: utf-8 -*-
"""
ano_rpi_driver.py — 凌霄匿名协议完整解析库（树莓派专用）
=============================================================
硬件接线（最小接法）：
    STM32 PD2 (UART5_RX) → 树莓派 GPIO15 (RXD)
    STM32 GND             → 树莓派 GND
    波特率: 500000 bps, 8N1, 无流控

快速开始：
    from ano_rpi_driver import AnoProtocol

    proto =好，那你写一个文档，我把这个文档拿给树莓派那边的ai，让他来写串口驱动接收imu的数据，并且能够写一个解析器，在需要的时候能够读取任何已经定义的数据帧。这个时候需要你来给一个百科全书。

如果已经有写好的解析器，也可以直接用，但是你要在文档里面说好，我的树莓派虽然目前只需要得到姿态和速度，但是后续有可能会发一些自定义的数据帧，或者说还要获取更多的信息，比如电量等等，所以多一事不如少一事，我希望他能够直接做一个所有数据帧都能解析的解析器，需要哪一个数据真就调用某一个解析就行。开始写吧

对了，我还是希望数据的传输速度能更快，帧率更高，这样子延迟会少一些，处理更好。 AnoProtocol('/dev/ttyAMA0', 500000)
    proto.start()

    att = proto.get_frame(0x04, timeout=0.1)   # 四元数（67Hz）★首选
    if att:
        print(att['roll_deg'], att['pitch_deg'], att['yaw_deg'])

    proto.stop()

帧频率速查：
    0x04 四元数    ~67 Hz  ★首选姿态
    0x01 IMU原始   ~100Hz
    0x07 飞行速度  ~50 Hz
    0x05 融合高度  ~50 Hz
    0x06 飞控状态  ~20 Hz
    0x02 气压/磁力 ~20 Hz
    0x0D 电池      ~1  Hz
    0x03 欧拉角    ~0.67Hz  ?极低，勿用于控制！
"""

import serial
import struct
import threading
import time
import math
from collections import defaultdict

# ── 地址常量 ────────────────────────────────────────────────────
ADDR_BROADCAST = 0xFF   # 广播
ADDR_IMU       = 0x60   # 凌霄 IMU 模块
ADDR_STM32     = 0x61   # STM32 飞控板
ADDR_PC        = 0xAF   # 上位机/地面站

# ── 帧名称（调试用） ────────────────────────────────────────────
FRAME_NAME = {
    0x00: 'CK_Reply',
    0x01: 'IMU_Raw',
    0x02: 'Baro_Mag',
    0x03: 'Euler_Angle',
    0x04: 'Quaternion',
    0x05: 'Fused_Alt',
    0x06: 'FC_Status',
    0x07: 'Velocity',
    0x08: 'XY_Pos',
    0x09: 'Wind',
    0x0A: 'Target_Att',
    0x0D: 'Battery',
    0x0E: 'Module_Status',
    0x20: 'Motor_PWM',
    0x21: 'Att_Ctrl',
    0x32: 'Pos_Report',
    0x33: 'Vel_Report',
    0x34: 'Dist_Report',
    0x40: 'RC_Data',
    0x41: 'RT_Ctrl',
    0xA0: 'Log_String',
    0xE0: 'CMD',
    0xE2: 'Param_Write',
}


# ── 工具函数 ─────────────────────────────────────────────────────
def _s16(b, off): return struct.unpack_from('<h', b, off)[0]
def _u16(b, off): return struct.unpack_from('<H', b, off)[0]
def _s32(b, off): return struct.unpack_from('<i', b, off)[0]
def _u32(b, off): return struct.unpack_from('<I', b, off)[0]


def verify_frame(buf: bytes | bytearray) -> bool:
    """
    验证帧 SC/AC 双校验。
    buf 为完整帧（从 0xAA 开始，包含 SC 和 AC）。
    返回 True = 校验通过。
    """
    if len(buf) < 6 or buf[0] != 0xAA:
        return False
    ln = buf[3]
    if len(buf) < ln + 6:
        return False
    sc = ac = 0
    for i in range(ln + 4):          # 覆盖 0xAA → DATA 末尾
        sc = (sc + buf[i]) & 0xFF
        ac = (ac + sc)     & 0xFF
    return sc == buf[ln + 4] and ac == buf[ln + 5]


def build_frame(dest: int, cmd: int, data: bytes) -> bytes:
    """
    构造完整协议帧（含 SC/AC 校验）。
    返回 bytes，可直接写入串口。
    """
    ln  = len(data)
    buf = bytearray([0xAA, dest & 0xFF, cmd & 0xFF, ln & 0xFF])
    buf += bytearray(data)
    sc = ac = 0
    for b in buf:
        sc = (sc + b) & 0xFF
        ac = (ac + sc) & 0xFF
    buf.append(sc)
    buf.append(ac)
    return bytes(buf)


def decode_frame(cmd: int, data: bytes) -> dict:
    """
    将 DATA 区字节解码为字典。

    返回值：
        成功  → dict，键名见下方各帧说明
        未知  → {'raw': hex字符串}
        异常  → {'error': '描述', 'raw': hex}

    所有 IMU→STM32 上报帧均已实现。
    扩展方法：在末尾 elif 链中添加新 elif cmd == 0xXX 分支，无需改其他代码。
    """
    p = data
    n = len(p)
    try:
        # ── 0x01 惯性传感器原始值（~100 Hz） ──────────────────
        if cmd == 0x01 and n >= 13:
            return {
                'acc_x': _s16(p, 0), 'acc_y': _s16(p, 2), 'acc_z': _s16(p, 4),
                'gyr_x': _s16(p, 6), 'gyr_y': _s16(p, 8), 'gyr_z': _s16(p, 10),
                'shock': p[12],
            }

        # ── 0x02 气压计 + 磁力计（~20 Hz） ─────────────────────
        elif cmd == 0x02 and n >= 12:
            return {
                'mag_x': _s16(p, 0), 'mag_y': _s16(p, 2), 'mag_z': _s16(p, 4),
                'baro_alt_cm': _s32(p, 6),
                'temp_c': _s16(p, 10) * 0.1,
            }

        # ── 0x03 欧拉角（~0.67 Hz）? 极低频，请用 0x04 替代 ──
        elif cmd == 0x03 and n >= 7:
            return {
                'roll_deg':   _s16(p, 0) * 0.01,
                'pitch_deg':  _s16(p, 2) * 0.01,
                'yaw_deg':    _s16(p, 4) * 0.01,
                'fusion_sta': p[6],
            }

        # ── 0x04 四元数（~67 Hz）★首选姿态来源 ─────────────────
        elif cmd == 0x04 and n >= 9:
            w = _s16(p, 0) * 0.0001
            x = _s16(p, 2) * 0.0001
            y = _s16(p, 4) * 0.0001
            z = _s16(p, 6) * 0.0001
            # 同步计算欧拉角，方便直接使用
            roll  = math.degrees(math.atan2(2*(w*x + y*z), 1 - 2*(x*x + y*y)))
            sinp  = max(-1.0, min(1.0, 2*(w*y - z*x)))
            pitch = math.degrees(math.asin(sinp))
            yaw   = math.degrees(math.atan2(2*(w*z + x*y), 1 - 2*(y*y + z*z)))
            return {
                'w': w, 'x': x, 'y': y, 'z': z,
                'roll_deg': roll, 'pitch_deg': pitch, 'yaw_deg': yaw,
                'fusion_sta': p[8],
            }

        # ── 0x05 融合高度（~50 Hz） ─────────────────────────────
        elif cmd == 0x05 and n >= 9:
            return {
                'alt_fused_cm': _s32(p, 0),
                'alt_add_cm':   _s32(p, 4),
                'sta': p[8],
            }

        # ── 0x06 飞控状态（~20 Hz） ─────────────────────────────
        elif cmd == 0x06 and n >= 5:
            mode_map = {0: 'attitude', 1: 'alt_hold', 2: 'pos_hold', 3: 'mission'}
            return {
                'mode':     p[0],
                'mode_str': mode_map.get(p[0], f'unknown({p[0]})'),
                'unlocked': bool(p[1]),
                'cmd_cid':  p[2],
                'cmd_0':    p[3],
                'cmd_1':    p[4],
            }

        # ── 0x07 飞行速度（~50 Hz） ─────────────────────────────
        elif cmd == 0x07 and n >= 6:
            return {
                'vel_x_cms': _s16(p, 0),
                'vel_y_cms': _s16(p, 2),
                'vel_z_cms': _s16(p, 4),
            }

        # ── 0x08 XY 位移（~20 Hz，需外部定位） ─────────────────
        elif cmd == 0x08 and n >= 8:
            return {
                'pos_x_cm': _s32(p, 0),
                'pos_y_cm': _s32(p, 4),
            }

        # ── 0x09 风速估计 ────────────────────────────────────────
        elif cmd == 0x09 and n >= 4:
            return {
                'wind_x_cms': _s16(p, 0),
                'wind_y_cms': _s16(p, 2),
            }

        # ── 0x0D 电池（~1 Hz） ──────────────────────────────────
        elif cmd == 0x0D and n >= 4:
            return {
                'voltage_v': _u16(p, 0) * 0.01,
                'current_a': _u16(p, 2) * 0.01,
            }

        # ── 0x0E 外接模块状态（~2 Hz） ──────────────────────────
        elif cmd == 0x0E and n >= 4:
            sta_str = {0: 'no_data', 1: 'unavail', 2: 'ok', 3: 'good'}
            return {
                'sta_gvel': sta_str.get(p[0], '?'),
                'sta_gpos': sta_str.get(p[1], '?'),
                'sta_gps':  sta_str.get(p[2], '?'),
                'sta_alt':  sta_str.get(p[3], '?'),
            }

        # ── 0x20 电机 PWM ────────────────────────────────────────
        elif cmd == 0x20 and n >= 2:
            return {f'M{i+1}': _u16(p, i*2) for i in range(n // 2)}

        # ── 0x21 姿态控制量 ──────────────────────────────────────
        elif cmd == 0x21 and n >= 8:
            return {
                'ctrl_roll':  _s16(p, 0),
                'ctrl_pitch': _s16(p, 2),
                'ctrl_yaw':   _s16(p, 4),
                'ctrl_thr':   _s16(p, 6),
            }

        # ── 0x40 遥控器原始通道（STM32→IMU，~50 Hz） ───────────
        elif cmd == 0x40 and n >= 20:
            names = ['roll', 'pitch', 'throttle', 'yaw',
                     'aux1', 'aux2', 'aux3', 'aux4', 'aux5', 'aux6']
            return {names[i]: _s16(p, i * 2) for i in range(10)}

        # ── 0x41 实时控制帧（程控模式，~50 Hz） ─────────────────
        elif cmd == 0x41 and n >= 14:
            return {
                'roll_deg':  _s16(p, 0) * 0.01,
                'pitch_deg': _s16(p, 2) * 0.01,
                'thr_pct':   _s16(p, 4) * 0.1,
                'yaw_rate':  _s16(p, 6),
                'vel_x_cms': _s16(p, 8),
                'vel_y_cms': _s16(p, 10),
                'vel_z_cms': _s16(p, 12),
            }

        # ── 0xA0 日志字符串 ──────────────────────────────────────
        elif cmd == 0xA0 and n >= 1:
            color = {0: 'black', 1: 'red', 2: 'green'}.get(p[0], '?')
            return {
                'color': color,
                'text': p[1:].decode('utf-8', errors='replace').rstrip('\x00'),
            }

        # ── 0x00 CK 应答 ─────────────────────────────────────────
        elif cmd == 0x00 and n >= 3:
            return {'for_cmd': p[0], 'sc': p[1], 'ac': p[2]}

        # ── 0xE0 CMD 命令 ────────────────────────────────────────
        elif cmd == 0xE0 and n >= 3:
            return {'cid': p[0], 'cmd_0': p[1], 'cmd_1': p[2]}

        # ── 在此处扩展新帧 ───────────────────────────────────────
        # elif cmd == 0xXX and n >= YY:
        #     return { 'field': ... }

    except Exception as e:
        return {'error': str(e), 'raw': p.hex()}

    return {'raw': p.hex()}   # 未知帧或长度不足


class AnoProtocol:
    """
    凌霄匿名协议驱动（后台线程，线程安全）。

    支持 context manager：
        with AnoProtocol('/dev/ttyAMA0') as proto:
            att = proto.get_frame(0x04, timeout=0.1)

    主要 API：
        get_frame(cmd, timeout)      → dict | None
        get_frame_age(cmd)           → float | None  (秒)
        is_fresh(cmd, max_age_sec)   → bool
        register_callback(cmd, fn)   → None
        send(dest, cmd, data)        → None
        send_cmd(cid, cmd_0, cmd_1)  → None
        send_ctrl(roll, pitch, thr, yaw_rate, vx, vy, vz)
        report_position(x, y, z, quality)
        report_distance(dist_cm)
        get_stats()                  → (dict, int)
    """

    def __init__(self, port: str, baudrate: int = 500000):
        self._ser       = serial.Serial(port, baudrate, timeout=0.02)
        self._buf       = bytearray()
        self._lock      = threading.Lock()
        # {cmd: (decoded_dict, raw_bytes, monotonic_ts)}
        self._frames    = {}
        self._callbacks = defaultdict(list)
        self._running   = False
        self._thread    = None
        self._stats     = defaultdict(int)
        self._err_cnt   = 0

    # ── 生命周期 ─────────────────────────────────────────────────

    def start(self):
        """启动后台接收线程（daemon，程序退出自动结束）"""
        self._running = True
        self._thread  = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止接收线程，关闭串口"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        try:
            self._ser.close()
        except Exception:
            pass

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_):
        self.stop()

    # ── 数据读取 API ─────────────────────────────────────────────

    def get_frame(self, cmd: int, timeout: float = None) -> dict | None:
        """
        获取指定 CMD 帧的最新解码数据（dict）。

        timeout=None  → 立即返回，帧未收到时返回 None
        timeout=0.05  → 最多等待 0.05 秒

        示例：
            att = proto.get_frame(0x04, timeout=0.05)
            if att:
                print(att['roll_deg'], att['pitch_deg'])
        """
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        while True:
            with self._lock:
                entry = self._frames.get(cmd)
            if entry:
                return entry[0]
            if deadline is None or time.monotonic() >= deadline:
                return None
            time.sleep(0.002)

    def get_frame_raw(self, cmd: int) -> bytes | None:
        """返回最新一帧的原始字节（完整帧含校验），用于透传/转发"""
        with self._lock:
            entry = self._frames.get(cmd)
        return entry[1] if entry else None

    def get_frame_age(self, cmd: int) -> float | None:
        """该帧距今多少秒。None = 从未收到"""
        with self._lock:
            entry = self._frames.get(cmd)
        return (time.monotonic() - entry[2]) if entry else None

    def is_fresh(self, cmd: int, max_age_sec: float) -> bool:
        """判断某帧在 max_age_sec 内是否收到过（数据是否新鲜）"""
        age = self.get_frame_age(cmd)
        return age is not None and age <= max_age_sec

    def get_stats(self) -> tuple:
        """返回 ({cmd: 接收次数}, 校验错误总数)"""
        with self._lock:
            return dict(self._stats), self._err_cnt

    # ── 回调注册 ─────────────────────────────────────────────────

    def register_callback(self, cmd: int, fn) -> None:
        """
        注册帧回调。每次成功收到并解析 cmd 帧时调用 fn(decoded_dict)。
        回调在接收线程中同步执行——避免阻塞操作（不要在回调里 sleep/IO 等）。
        可为同一帧注册多个回调。
        """
        self._callbacks[cmd].append(fn)

    # ── 发送 API ─────────────────────────────────────────────────

    def send(self, dest: int, cmd: int, data: bytes = b'') -> None:
        """发送任意协议帧（自动计算校验）"""
        self._ser.write(build_frame(dest, cmd, data))

    def send_cmd(self, cid: int, cmd_0: int, cmd_1: int = 0) -> None:
        """
        发送 0xE0 CMD 命令帧（广播 0xFF）。
        常用命令（飞控处于对应状态时才生效）：
            send_cmd(0x10, 0x01)  → 解锁
            send_cmd(0x10, 0x02)  → 上锁
            send_cmd(0x10, 0x03)  → 一键起飞
            send_cmd(0x10, 0x04)  → 一键降落
            send_cmd(0x10, 0x05)  → 急停
        """
        self.send(ADDR_BROADCAST, 0xE0,
                  bytes([cid & 0xFF, cmd_0 & 0xFF, cmd_1 & 0xFF]))

    def send_ctrl(self, roll_deg: float = 0.0, pitch_deg: float = 0.0,
                  thr_pct: float = 0.0, yaw_rate: int = 0,
                  vel_x: int = 0, vel_y: int = 0, vel_z: int = 0) -> None:
        """
        发送 0x41 实时控制帧（仅在程控模式 mode=3 下有效，需 50Hz 持续发送）。
            roll_deg / pitch_deg : 目标角度（度）
            thr_pct              : 油门 0~100
            yaw_rate             : 偏航角速度（度/秒）
            vel_x/y/z            : 速度指令（cm/s）
        """
        data = struct.pack('<7h',
                           int(roll_deg * 100),
                           int(pitch_deg * 100),
                           int(thr_pct * 10),
                           int(yaw_rate),
                           int(vel_x), int(vel_y), int(vel_z))
        self.send(ADDR_BROADCAST, 0x41, data)

    def report_position(self, x_cm: int, y_cm: int, z_cm: int,
                        quality: int = 100) -> None:
        """
        向 IMU 上报位置（0x32 帧），IMU 融合进定位估计。
        适合视觉/UWB 定位系统输出。
        """
        data = struct.pack('<iiiB', x_cm, y_cm, z_cm, quality)
        self.send(ADDR_IMU, 0x32, data)

    def report_velocity(self, vx_cms: int, vy_cms: int, vz_cms: int,
                        quality: int = 100) -> None:
        """向 IMU 上报速度（0x33 帧）"""
        data = struct.pack('<iiiB', vx_cms, vy_cms, vz_cms, quality)
        self.send(ADDR_IMU, 0x33, data)

    def report_distance(self, dist_cm: int) -> None:
        """向 IMU 上报测距（0x34 帧），用于辅助高度融合"""
        data = struct.pack('<i', dist_cm)
        self.send(ADDR_IMU, 0x34, data)

    # ── 内部接收解析循环 ─────────────────────────────────────────

    def _recv_loop(self):
        while self._running:
            try:
                chunk = self._ser.read(512)
                if chunk:
                    self._buf.extend(chunk)
                    self._parse_buf()
            except Exception:
                pass

    def _parse_buf(self):
        buf = self._buf
        while len(buf) >= 6:
            idx = buf.find(0xAA)
            if idx == -1:
                self._buf = bytearray()
                return
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

            if verify_frame(frame):
                cmd     = frame[2]
                payload = bytes(frame[4:4 + ln])
                decoded = decode_frame(cmd, payload)
                ts      = time.monotonic()
                with self._lock:
                    self._frames[cmd] = (decoded, bytes(frame), ts)
                    self._stats[cmd] += 1
                for fn in self._callbacks.get(cmd, []):
                    try:
                        fn(decoded)
                    except Exception:
                        pass
            else:
                with self._lock:
                    self._err_cnt += 1
                buf = buf[1:]   # 跳一字节，重新同步

        self._buf = buf


# ── 独立运行：实时监视模式 ──────────────────────────────────────
if __name__ == '__main__':
    import argparse

    ap = argparse.ArgumentParser(description='凌霄协议实时监视器')
    ap.add_argument('--port', default='/dev/ttyAMA0')
    ap.add_argument('--baud', type=int, default=500000)
    ap.add_argument('--show', nargs='*',
                    help='只显示哪些帧，如 --show 0x04 0x07')
    args = ap.parse_args()

    show_ids = set()
    if args.show:
        show_ids = {int(x, 16) for x in args.show}

    print(f'凌霄协议监视器  端口={args.port}  波特率={args.baud}')
    print('按 Ctrl+C 退出\n')

    last_ts = {}

    def on_frame(decoded, cmd):
        now = time.time()
        if show_ids and cmd not in show_ids:
            return
        min_interval = {0x04: 0.1, 0x07: 0.2, 0x0D: 5.0}.get(cmd, 0.5)
        if now - last_ts.get(cmd, 0) < min_interval:
            return
        last_ts[cmd] = now
        name = FRAME_NAME.get(cmd, f'0x{cmd:02X}')
        print(f'[0x{cmd:02X}] {name:<15s} {decoded}')

    with AnoProtocol(args.port, args.baud) as proto:
        for c in FRAME_NAME:
            proto.register_callback(c, lambda d, cmd=c: on_frame(d, cmd))
        try:
            while True:
                time.sleep(5)
                stats, errs = proto.get_stats()
                print(f'\n--- 统计 | 校验错 {errs} ---')
                for c, cnt in sorted(stats.items()):
                    print(f'  0x{c:02X} {FRAME_NAME.get(c,"?"):<15s}: {cnt}次')
                print()
        except KeyboardInterrupt:
            print('\n退出')
