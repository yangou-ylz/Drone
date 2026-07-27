# -*- coding: utf-8 -*-
"""
匿名通信协议 V7 — 极简编解码库
帧格式：0xAA | dest | CMD | LEN | DATA[LEN] | SC | AC
校验范围：前 (LEN + 4) 字节，即从帧头到 DATA 末尾
    for i in range(LEN + 4):
        sc += data[i]; ac += sc
"""
from __future__ import annotations
import struct
from dataclasses import dataclass

FRAME_HEAD = 0xAA

# 常用地址
ADDR_BROADCAST = 0xFF
ADDR_UPPER     = 0xAF  # 上位机
ADDR_IMU       = 0x60  # 凌霄IMU
ADDR_FC_STM32  = 0x61  # 凌霄飞控STM32（即 HW_TYPE）

# 0xF5 树莓派位置帧
CMD_RPI_POSITION = 0xF5
F5_DATA_LEN = 0x19
INVALID_S32 = -2147483648

# 0xF7/F8 自主任务命令/状态帧
CMD_AUTO_MISSION = 0xF7
CMD_AUTO_STATUS = 0xF8
CMD_AUTO_MOVE = 0xF9
CMD_AUTO_VELOCITY = 0xFA
AUTO_PROTOCOL_VER = 1
AUTO_SAFETY_KEY = 0xA55A
AUTO_FLAG_NO_XY_MOTION = 0x0008
AUTO_STATUS_FLAG_RC_LOCKOUT = 0x0100
AUTO_STATUS_FLAG_RC_FAILSAFE = 0x0200
AUTO_STATUS_FLAG_RC_NO_SIGNAL = 0x0400
AUTO_STATUS_FLAG_RC_HOLD_FRAME = 0x0800
AUTO_STATUS_FLAG_VOLT_TAKEOFF_OK = 0x1000
AUTO_STATUS_FLAG_VOLT_WARN = 0x2000
AUTO_STATUS_FLAG_VOLT_LOW = 0x4000

AUTO_CMD_QUERY_STATUS = 0x00
AUTO_CMD_PRECHECK = 0x01
AUTO_CMD_REQUEST_MODE2 = 0x02
AUTO_CMD_DRYRUN_TAKEOFF_LAND = 0x03
AUTO_CMD_START_LOW_TAKEOFF_LAND = 0x04
AUTO_CMD_ABORT_LAND = 0x05
AUTO_CMD_EMERGENCY_LOCK = 0x06
AUTO_CMD_CLEAR_ERROR = 0x07
AUTO_CMD_RELEASE_RC = 0x08
AUTO_CMD_LOCK_RC = 0x09
AUTO_CMD_TAKEOFF_HOLD = 0x0A
AUTO_CMD_LAND_ONLY = 0x0B

AUTO_MOVE_CMD_QUERY = 0x00
AUTO_MOVE_CMD_START = 0x01
AUTO_MOVE_CMD_STOP = 0x02

AUTO_MOVE_AXIS_XYZ = 0
AUTO_MOVE_AXIS_X = 1
AUTO_MOVE_AXIS_Y = 2
AUTO_MOVE_AXIS_Z = 3
AUTO_MOVE_AXIS_XY = 4
AUTO_MOVE_AXIS_AUTO = 0xFF
AUTO_MOVE_LIMIT_CM = 200
AUTO_VEL_CMD_QUERY = 0x00
AUTO_VEL_CMD_SET = 0x01
AUTO_VEL_CMD_STOP = 0x02
AUTO_VEL_LIMIT_CMPS = 30
AUTO_YAW_LIMIT_DPS = 45

FLAG_SLAM_VALID = 0x01
FLAG_TARGET_VALID = 0x02
FLAG_VISUAL_MODE = 0x04

# 颜色（0xA0 字符串帧首字节）
COLOR_BLACK = 0
COLOR_RED   = 1
COLOR_GREEN = 2


def calc_checksum(buf: bytes | bytearray) -> tuple[int, int]:
    """对 buf 累加得到 (SC, AC)。调用方负责传入 LEN+4 字节切片。"""
    sc = 0
    ac = 0
    for b in buf:
        sc = (sc + b) & 0xFF
        ac = (ac + sc) & 0xFF
    return sc, ac


def build_frame(dest: int, cmd: int, data: bytes = b"") -> bytes:
    """组装完整帧（含 SC/AC）。data 长度必须 ≤ 255。"""
    if len(data) > 255:
        raise ValueError("DATA too long (>255)")
    head = bytes([FRAME_HEAD, dest & 0xFF, cmd & 0xFF, len(data) & 0xFF]) + bytes(data)
    sc, ac = calc_checksum(head)
    return head + bytes([sc, ac])


def build_f1_xy(dest: int, x: int, y: int) -> bytes:
    """阶段1 灵活帧 0xF1，DATA 前 4 字节为 S16 X, S16 Y（小端）。"""
    if not (-32768 <= x <= 32767):
        raise ValueError(f"x out of s16 range: {x}")
    if not (-32768 <= y <= 32767):
        raise ValueError(f"y out of s16 range: {y}")
    data = struct.pack("<hh", x, y)  # 小端 s16 ×2
    return build_frame(dest, 0xF1, data)


def build_f2_param(dest: int, param_id: int, value: float) -> bytes:
    """阶段2 参数写入 0xF2，DATA = U8 ID + Float32(LE) Value（共 5 字节）。

    飞控端白名单 ID：0x01/0x02/0x03 = 目标 X/Y/Z (cm)；超出走限幅或 UNK 回执。
    上位机不做语义校验，原样发送由飞控决断。
    """
    if not (0 <= param_id <= 0xFF):
        raise ValueError(f"param_id out of u8 range: {param_id}")
    data = struct.pack("<Bf", int(param_id) & 0xFF, float(value))
    return build_frame(dest, 0xF2, data)


def build_f3_xyz(dest: int, x: float, y: float, z: float) -> bytes:
    """阶段2b 三轴目标同帧写入 0xF3，DATA = float_LE * 3（共 12 字节）。

    飞控对每个轴各自做 |v|≤500cm 限幅，任一轴被限幅 → 回显末尾带 CLP。
    与 0xF2 共享同一组 RAM 槽位，生效时机一致（任务启动拍照）。
    """
    data = struct.pack("<fff", float(x), float(y), float(z))
    return build_frame(dest, 0xF3, data)


def _to_s32_cm(v: int | float | None) -> int:
    """把 cm 输入转换为 signed s32；None/NaN 使用 0x80000000 无效哨兵。"""
    if v is None:
        return INVALID_S32
    if isinstance(v, float) and v != v:
        return INVALID_S32
    iv = int(round(v))
    if not (INVALID_S32 <= iv <= 2147483647):
        raise ValueError(f"value out of s32 range: {v}")
    return iv


def build_f5_position(
    dest: int,
    cur_x: int | float | None,
    cur_y: int | float | None,
    cur_z: int | float | None,
    tar_x: int | float | None,
    tar_y: int | float | None,
    tar_z: int | float | None,
    flags: int,
) -> bytes:
    """树莓派位置帧 0xF5。

    DATA = cur_x/y/z + tar_x/y/z（signed s32 little-endian，单位 cm）+ flags。
    注意：无效轴在协议字节上是 0x80000000，但 Python signed int 必须写
    -2147483648，不能把 0x80000000 直接传给 struct.pack('<i')。
    """
    if not (0 <= int(flags) <= 0xFF):
        raise ValueError(f"flags out of u8 range: {flags}")
    data = struct.pack(
        "<iiiiiiB",
        _to_s32_cm(cur_x),
        _to_s32_cm(cur_y),
        _to_s32_cm(cur_z),
        _to_s32_cm(tar_x),
        _to_s32_cm(tar_y),
        _to_s32_cm(tar_z),
        int(flags) & 0xFF,
    )
    if len(data) != F5_DATA_LEN:
        raise AssertionError(f"internal F5 length error: {len(data)}")
    return build_frame(dest, CMD_RPI_POSITION, data)


def build_f7_auto_cmd(
    dest: int,
    seq: int,
    cmd: int,
    *,
    safety_key: int = 0,
    height_cm: int = 40,
    hold_ms: int = 3000,
    flags: int = AUTO_FLAG_NO_XY_MOTION,
    timeout_ms: int = 30000,
    reserved: int = 0,
    ver: int = AUTO_PROTOCOL_VER,
) -> bytes:
    """GUI → STM32 自主任务命令帧 0xF7。

    DATA = ver:u8, seq:u16, cmd:u8, safety_key:u16, height_cm:u16,
    hold_ms:u16, flags:u16, timeout_ms:u16, reserved:u16，全小端。
    """
    checks = {
        "ver": (ver, 0, 0xFF),
        "seq": (seq, 0, 0xFFFF),
        "cmd": (cmd, 0, 0xFF),
        "safety_key": (safety_key, 0, 0xFFFF),
        "height_cm": (height_cm, 0, 0xFFFF),
        "hold_ms": (hold_ms, 0, 0xFFFF),
        "flags": (flags, 0, 0xFFFF),
        "timeout_ms": (timeout_ms, 0, 0xFFFF),
        "reserved": (reserved, 0, 0xFFFF),
    }
    for name, (value, lo, hi) in checks.items():
        iv = int(value)
        if not (lo <= iv <= hi):
            raise ValueError(f"{name} out of range: {value}")
    data = struct.pack(
        "<BHBHHHHHH",
        int(ver) & 0xFF,
        int(seq) & 0xFFFF,
        int(cmd) & 0xFF,
        int(safety_key) & 0xFFFF,
        int(height_cm) & 0xFFFF,
        int(hold_ms) & 0xFFFF,
        int(flags) & 0xFFFF,
        int(timeout_ms) & 0xFFFF,
        int(reserved) & 0xFFFF,
    )
    if len(data) != 0x10:
        raise AssertionError(f"internal F7 length error: {len(data)}")
    return build_frame(dest, CMD_AUTO_MISSION, data)


def build_f9_move_cmd(
    dest: int,
    seq: int,
    cmd: int,
    *,
    safety_key: int = 0,
    x_cm: int | float = 0,
    y_cm: int | float = 0,
    z_cm: int | float = 0,
    axis_mode: int = AUTO_MOVE_AXIS_AUTO,
    flags: int = 0,
    ver: int = AUTO_PROTOCOL_VER,
) -> bytes:
    """GUI → STM32 相对位移命令帧 0xF9。

    DATA = ver:u8, seq:u16, cmd:u8, safety_key:u16, x/y/z:s16 cm,
    axis_mode:u8, flags:u16，全小端。第一版飞控端每轴限制 ±200cm。
    """
    checks = {
        "ver": (ver, 0, 0xFF),
        "seq": (seq, 0, 0xFFFF),
        "cmd": (cmd, 0, 0xFF),
        "safety_key": (safety_key, 0, 0xFFFF),
        "x_cm": (round(float(x_cm)), -32768, 32767),
        "y_cm": (round(float(y_cm)), -32768, 32767),
        "z_cm": (round(float(z_cm)), -32768, 32767),
        "axis_mode": (axis_mode, 0, 0xFF),
        "flags": (flags, 0, 0xFFFF),
    }
    for name, (value, lo, hi) in checks.items():
        iv = int(value)
        if not (lo <= iv <= hi):
            raise ValueError(f"{name} out of range: {value}")
    data = struct.pack(
        "<BHBHhhhBH",
        int(ver) & 0xFF,
        int(seq) & 0xFFFF,
        int(cmd) & 0xFF,
        int(safety_key) & 0xFFFF,
        int(round(float(x_cm))),
        int(round(float(y_cm))),
        int(round(float(z_cm))),
        int(axis_mode) & 0xFF,
        int(flags) & 0xFFFF,
    )
    if len(data) != 0x0F:
        raise AssertionError(f"internal F9 length error: {len(data)}")
    return build_frame(dest, CMD_AUTO_MOVE, data)


def build_fa_velocity_cmd(
    dest: int,
    seq: int,
    cmd: int,
    *,
    safety_key: int = 0,
    vx_cmps: int | float = 0,
    vy_cmps: int | float = 0,
    yaw_dps: int | float = 0,
    flags: int = 0,
    ver: int = AUTO_PROTOCOL_VER,
) -> bytes:
    """GUI → STM32 键盘低速速度命令帧 0xFA。

    DATA = ver:u8, seq:u16, cmd:u8, safety_key:u16,
    vx/vy/yaw:s16, flags:u16。只表达水平线速度和偏航角速度。
    """
    checks = {
        "ver": (ver, 0, 0xFF),
        "seq": (seq, 0, 0xFFFF),
        "cmd": (cmd, 0, 0xFF),
        "safety_key": (safety_key, 0, 0xFFFF),
        "vx_cmps": (round(float(vx_cmps)), -32768, 32767),
        "vy_cmps": (round(float(vy_cmps)), -32768, 32767),
        "yaw_dps": (round(float(yaw_dps)), -32768, 32767),
        "flags": (flags, 0, 0xFFFF),
    }
    for name, (value, lo, hi) in checks.items():
        iv = int(value)
        if not (lo <= iv <= hi):
            raise ValueError(f"{name} out of range: {value}")
    data = struct.pack(
        "<BHBHhhhH",
        int(ver) & 0xFF,
        int(seq) & 0xFFFF,
        int(cmd) & 0xFF,
        int(safety_key) & 0xFFFF,
        int(round(float(vx_cmps))),
        int(round(float(vy_cmps))),
        int(round(float(yaw_dps))),
        int(flags) & 0xFFFF,
    )
    if len(data) != 0x0E:
        raise AssertionError(f"internal FA length error: {len(data)}")
    return build_frame(dest, CMD_AUTO_VELOCITY, data)



# ---------------- 解析器 ----------------

@dataclass
class Frame:
    dest: int
    cmd: int
    data: bytes
    sc: int
    ac: int
    raw: bytes

    def color_str(self) -> tuple[int, str] | None:
        """若为 0xA0 字符串帧，返回 (color, text)；否则 None。"""
        if self.cmd != 0xA0 or len(self.data) < 1:
            return None
        color = self.data[0]
        # STM32 端日志默认 GBK 编码（包含中文）；ASCII 解码会把高字节变 ? 导致乱码。
        try:
            text = self.data[1:].decode("gbk", errors="replace")
        except Exception:
            try:
                text = self.data[1:].decode("utf-8", errors="replace")
            except Exception:
                text = repr(self.data[1:])
        return color, text


@dataclass(frozen=True)
class AutoStatus:
    """STM32 → GUI 自主任务状态帧 0xF8。"""

    ver: int
    status_seq: int
    last_cmd_seq: int
    state: int
    last_cmd: int
    error: int
    flags: int
    mode: int
    unlock: int
    voltage_100: int
    alt_cm: int
    state_ms: int
    f5_age_ms: int
    rx_f7_cnt: int
    err_cnt: int


def parse_f8_auto_status(data: bytes) -> AutoStatus:
    """解析 0xF8 DATA；长度错误时抛 ValueError。"""
    fmt = "<BHHBBHHBBHhHHHH"
    if len(data) != struct.calcsize(fmt):
        raise ValueError(f"bad F8 DATA length: {len(data)}")
    return AutoStatus(*struct.unpack(fmt, data))


class FrameParser:
    """字节流状态机，与 STM32 端 ANO_DT_LX_Data_Receive_Prepare 等价。"""

    def __init__(self):
        self._state = 0
        self._buf = bytearray()
        self._len = 0

    def feed(self, chunk: bytes) -> list[Frame]:
        out: list[Frame] = []
        for b in chunk:
            f = self._step(b)
            if f is not None:
                out.append(f)
        return out

    def _step(self, b: int) -> Frame | None:
        if self._state == 0:
            if b == FRAME_HEAD:
                self._buf = bytearray([b])
                self._state = 1
        elif self._state == 1:  # dest
            self._buf.append(b)
            self._state = 2
        elif self._state == 2:  # cmd
            self._buf.append(b)
            self._state = 3
        elif self._state == 3:  # len
            self._buf.append(b)
            self._len = b
            self._state = 4 if self._len > 0 else 5
        elif self._state == 4:  # data
            self._buf.append(b)
            if len(self._buf) - 4 >= self._len:
                self._state = 5
        elif self._state == 5:  # sc
            self._sc_rx = b
            self._buf.append(b)
            self._state = 6
        elif self._state == 6:  # ac
            self._ac_rx = b
            self._buf.append(b)
            # 校验
            sc, ac = calc_checksum(bytes(self._buf[:-2]))
            self._state = 0
            if sc == self._sc_rx and ac == self._ac_rx:
                return Frame(
                    dest=self._buf[1],
                    cmd=self._buf[2],
                    data=bytes(self._buf[4:4 + self._len]),
                    sc=sc,
                    ac=ac,
                    raw=bytes(self._buf),
                )
            # 校验失败：丢弃，状态机已回到 0
        return None


def hex_dump(b: bytes) -> str:
    return " ".join(f"{x:02X}" for x in b)
