# -*- coding: utf-8 -*-
"""P5.5 传感器帧记录器：把入站状态帧落盘为 JSONL，便于离线/AI 诊断。

设计：
- 白名单仅"状态/传感器"类帧：0x01/0x02/0x03/0x04/0x05/0x06/0x07/0x08/0x0E
  显式排除：0x41 实时控制、0xE0/0xE2 命令回执、0xA0 字符串日志等
- 每条日志一行 JSON（JSONL），既人类可读也方便 `json.loads` 批量解析
- 帧体除"已知字段解码"外，永远附带 `hex` 原始数据 → 解码错也能复盘
- 时间戳同时记 `t_mono`（单调，秒，相对录制起点）和 `t_iso`（带时区墙钟），方便对齐
- 文件 IO 缓冲；每 32 帧或 0.5s flush 一次，宕机最多丢 0.5s 数据
- 纯 QObject + 主线程：与 SerialWorker.frame_received 同步（feed_frame 流早就在主线程跑了，挂同一信号即可）

依赖：
- gui.io.protocol.Frame：cmd / data / addr
- gui.services.telemetry_decoder：已有 0x03/0x04/0x05/0x07 decoder（直接复用，保证解码语义一致）

不做的事（避免范围爆炸）：
- 不解析命令/回执帧（不在传感器范畴）
- 不做流量截断（用户决定记多久）
- 不做 ring buffer（落盘是顺序追加；想截短自己删头）
"""
from __future__ import annotations

import json
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal

from gui.io.protocol import Frame
from gui.services.telemetry_decoder import (
    decode_attitude_euler,
    decode_attitude_quat,
    decode_height,
    decode_velocity,
)


# 白名单：状态/传感器帧
RECORD_CMDS = frozenset({0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0E})

# 字段解码格式（与 .github/instructions/lingxiao-protocol.instructions.md 对齐）
_FMT_0x01 = "<hhhhhhB"   # ACC_X/Y/Z + GYR_X/Y/Z + SHOCK_STA → LEN=13
_FMT_0x02 = "<hhhihBB"   # MAG_X/Y/Z + ALT_BAR + TMP + BAR_STA + MAG_STA → LEN=14
_FMT_0x06 = "<BBBBB"     # MODE/LOCKED/CID/CMD0/CMD1 → LEN=5
_FMT_0x08 = "<ii"        # POS_X / POS_Y (cm) → LEN=8
_FMT_0x0E = "<BBBB"      # STA_G_VEL/G_POS/GPS/ALT_ADD → LEN=4


def _decode_fields(cmd: int, data: bytes) -> Optional[Dict[str, Any]]:
    """已知帧 → 友好字段名字典；未知 / 长度错 → None。"""
    try:
        if cmd == 0x01 and len(data) == struct.calcsize(_FMT_0x01):
            ax, ay, az, gx, gy, gz, shock = struct.unpack(_FMT_0x01, data)
            return {
                "acc_x": ax, "acc_y": ay, "acc_z": az,         # 原始 LSB（量纲见手册）
                "gyr_x": gx, "gyr_y": gy, "gyr_z": gz,
                "shock_sta": shock,
            }
        if cmd == 0x02 and len(data) == struct.calcsize(_FMT_0x02):
            mx, my, mz, alt_bar, tmp, bar_sta, mag_sta = struct.unpack(_FMT_0x02, data)
            return {
                "mag_x": mx, "mag_y": my, "mag_z": mz,
                "alt_bar_cm": alt_bar,
                "temp_x10c": tmp,
                "bar_sta": bar_sta, "mag_sta": mag_sta,
            }
        if cmd == 0x03:
            s = decode_attitude_euler(data)
            if s is None:
                return None
            return {
                "roll_deg": s.roll_deg, "pitch_deg": s.pitch_deg, "yaw_deg": s.yaw_deg,
                "fusion_sta": s.fusion_sta, "source": "euler",
            }
        if cmd == 0x04:
            s = decode_attitude_quat(data)
            if s is None:
                return None
            # 同时把原始 V0..V3 也记一份，方便复盘 quat 顺序
            raw = struct.unpack("<hhhhB", data)
            return {
                "roll_deg": s.roll_deg, "pitch_deg": s.pitch_deg, "yaw_deg": s.yaw_deg,
                "fusion_sta": s.fusion_sta, "source": "quat",
                "quat_raw": [raw[0], raw[1], raw[2], raw[3]],   # ×10000
            }
        if cmd == 0x05:
            s = decode_height(data)
            if s is None:
                return None
            return {
                "alt_fu_cm": s.alt_fu_cm,
                "alt_add_cm": s.alt_add_cm,
                "alt_sta": s.alt_sta,
            }
        if cmd == 0x06 and len(data) == struct.calcsize(_FMT_0x06):
            mode, locked, cid, cmd0, cmd1 = struct.unpack(_FMT_0x06, data)
            return {
                "mode": mode,           # 0=姿态 / 1=定高 / 2=定点 / 3=程控
                "locked": locked,       # 1=锁定 / 0=解锁
                "cid": cid,             # 当前程控编号
                "cmd0": cmd0, "cmd1": cmd1,
            }
        if cmd == 0x07:
            s = decode_velocity(data)
            if s is None:
                return None
            return {
                "vx_cmps": s.vx_cmps, "vy_cmps": s.vy_cmps, "vz_cmps": s.vz_cmps,
            }
        if cmd == 0x08 and len(data) == struct.calcsize(_FMT_0x08):
            px, py = struct.unpack(_FMT_0x08, data)
            return {"pos_x_cm": px, "pos_y_cm": py}
        if cmd == 0x0E and len(data) == struct.calcsize(_FMT_0x0E):
            g_vel, g_pos, gps, alt_add = struct.unpack(_FMT_0x0E, data)
            return {
                "sta_g_vel": g_vel,     # 0=无数据 / 1=有数据但不可用 / 2=正常
                "sta_g_pos": g_pos,
                "sta_gps": gps,
                "sta_alt_add": alt_add,
            }
    except struct.error:
        return None
    return None


class FrameRecorder(QObject):
    """JSONL 帧记录器（QObject，主线程使用）。

    信号：
    - state_changed(bool active, str path) — 录制开关切换；停止时 path 是""或最后的文件路径
    - frame_logged(int total_count) — 每条写入后回发，配合状态栏更新（≥10 帧节流也行，先简单）
    - error(str) — 文件 IO 异常等
    """

    state_changed = Signal(bool, str)
    frame_logged = Signal(int)
    error = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._fp = None                  # type: ignore[assignment]
        self._path: str = ""
        self._count: int = 0
        self._start_mono: float = 0.0
        self._buf_writes: int = 0
        self._last_flush: float = 0.0

    # ---- 状态查询 ----
    @property
    def is_recording(self) -> bool:
        return self._fp is not None

    @property
    def path(self) -> str:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    # ---- 控制 ----
    def start(self, path: str) -> bool:
        """打开文件，写头注释行。失败发 error 并返回 False。"""
        if self.is_recording:
            self.error.emit("已在记录中，请先停止")
            return False
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._fp = open(p, "w", encoding="utf-8", buffering=1024 * 64)
            self._path = str(p)
            self._count = 0
            self._start_mono = time.monotonic()
            self._buf_writes = 0
            self._last_flush = self._start_mono
            # 第一行：元数据（仍然合法 JSON，便于程序读）
            meta = {
                "_meta": True,
                "format": "lingxiao-jsonl-v1",
                "started_iso": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "started_mono": self._start_mono,
                "record_cmds": sorted(f"0x{c:02X}" for c in RECORD_CMDS),
                "note": "每行一帧；t_mono 单位秒，相对 started_mono；cmd 为十六进制字符串；fields 由 decoder 解析，hex 永远附原始字节。",
            }
            self._fp.write(json.dumps(meta, ensure_ascii=False) + "\n")
            self._fp.flush()
            self.state_changed.emit(True, self._path)
            return True
        except OSError as exc:
            self.error.emit(f"打开记录文件失败：{exc}")
            self._fp = None
            self._path = ""
            return False

    def stop(self) -> None:
        if not self.is_recording:
            return
        try:
            # 写收尾元数据
            tail = {
                "_meta": True,
                "stopped_iso": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "frames": self._count,
                "duration_s": round(time.monotonic() - self._start_mono, 3),
            }
            assert self._fp is not None
            self._fp.write(json.dumps(tail, ensure_ascii=False) + "\n")
            self._fp.flush()
            self._fp.close()
        except OSError as exc:
            self.error.emit(f"关闭记录文件异常：{exc}")
        finally:
            self._fp = None
            last_path = self._path
            self._path = ""
            self.state_changed.emit(False, last_path)

    # ---- 数据入口：挂在 SerialWorker.frame_received ----
    def on_frame(self, fr: Frame) -> None:
        if self._fp is None:
            return
        if fr.cmd not in RECORD_CMDS:
            return
        try:
            now = time.monotonic()
            entry: Dict[str, Any] = {
                "t_mono": round(now - self._start_mono, 4),
                "t_iso": datetime.now().astimezone().isoformat(timespec="milliseconds"),
                "dest": f"0x{fr.dest:02X}" if isinstance(fr.dest, int) else None,
                "cmd": f"0x{fr.cmd:02X}",
                "len": len(fr.data),
                "hex": fr.data.hex(),
            }
            fields = _decode_fields(fr.cmd, fr.data)
            if fields is not None:
                entry["fields"] = fields
            self._fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._count += 1
            self._buf_writes += 1
            # 周期性 flush，最多 0.5s 或 32 帧
            if self._buf_writes >= 32 or (now - self._last_flush) >= 0.5:
                self._fp.flush()
                self._buf_writes = 0
                self._last_flush = now
            self.frame_logged.emit(self._count)
        except (OSError, ValueError) as exc:
            self.error.emit(f"写入帧记录失败：{exc}")
