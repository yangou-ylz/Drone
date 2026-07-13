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
