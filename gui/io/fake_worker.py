# -*- coding: utf-8 -*-
"""FakeWorker —— 离线仿真串口工作线程（飞控不在身边时用）。

接口与 :class:`SerialWorker` 鸭子兼容，可由 MainWindow 透明替换。

仿真行为（无飞控也能完整跑通整个发送→回执流程）：
- :meth:`open_port` 立刻成功，发 ``connected("FAKE://<name>")``；
- :meth:`send_bytes` 解析输入帧（仅 0xF1 / 0xF2），按飞控固件逻辑
  生成对应的 0xA0 字符串回执帧，**异步**（QTimer 单次触发，
  延迟 ``ECHO_DELAY_MS``）发回到 :attr:`frame_received`；
- :meth:`close_port` 取消所有待回执的回环；
- 仿真 UNK / CLP 等异常分支，让上位机三态反馈和 ERROR 报警都能在
  无硬件状态下被测到。

激活方式（仅 GUI 启动时）：环境变量 ``LINGXIAO_GUI_FAKE=1``。

设计原则：
- **只在仿真路径活动**；MainWindow 真接入硬件时永远不引用本文件；
- 飞控固件改变行为时，本文件的 echo 逻辑也要同步改，否则离线测试
  与真实回执表现不一致（视为已知限制，每次改 Uplink_Cmd.c 需同步检查）；
- 不依赖 Win32 串口、不写 sys.path —— 完全离线、跨平台。
"""
from __future__ import annotations

import struct
from typing import Optional

from PySide6.QtCore import (
    QByteArray,
    QObject,
    QTimer,
    Signal,
    Slot,
)

from .protocol import (
    ADDR_BROADCAST,
    ADDR_UPPER,
    COLOR_GREEN,
    COLOR_RED,
    Frame,
    FrameParser,
    build_frame,
)


# 模拟飞控限频回执的延迟（毫秒）；真实固件约 100ms 一次，此处偏小方便快测
ECHO_DELAY_MS = 80

# 与 FcSrc/Uplink_Cmd.h 对齐
_PARAM_ID_GOAL_X = 0x01
_PARAM_ID_GOAL_Y = 0x02
_PARAM_ID_GOAL_Z = 0x03
_PARAM_GOAL_LIMIT_CM = 500.0


def _make_a0_frame(color: int, text: str) -> Frame:
    """造一个 0xA0 字符串帧，用于喂给 FrameParser 模拟入站。"""
    body = bytes([color & 0xFF]) + text.encode("ascii", errors="replace")
    raw = build_frame(ADDR_UPPER, 0xA0, body)
    # 直接构造 Frame 对象，绕开 FrameParser（也可以喂解析器，但更慢且无意义）
    # DATA = body
    return Frame(
        dest=ADDR_UPPER,
        cmd=0xA0,
        data=body,
        sc=raw[-2],
        ac=raw[-1],
        raw=raw,
    )


class FakeWorker(QObject):
    """与 SerialWorker 鸭子兼容的离线仿真器。"""

    # ---- 与 SerialWorker 完全相同的信号 ----
    connected = Signal(str)
    disconnected = Signal(str)
    error = Signal(str)
    frame_received = Signal(object)
    bytes_in = Signal(int)
    bytes_out = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._opened = False
        self._port_name = ""
        self._parser = FrameParser()
        # 持有所有未触发的 QTimer，避免 GC；close 时全部取消
        self._pending_timers: list[QTimer] = []

    # ---- 线程入口（保留接口签名，仿真不需要循环） ----
    @Slot()
    def start_loop(self) -> None:
        """无需主循环；保留方法以保持接口一致。"""
        # 仿真模式下，所有事件都由 invokeMethod 派发到此对象所在线程，
        # 由该线程的 QEventLoop 自动处理。
        return

    @Slot()
    def stop(self) -> None:
        self._cancel_all_timers()
        self._opened = False

    @Slot(str)
    def open_port(self, port_name: str) -> None:
        if self._opened:
            self.disconnected.emit("仿真重开端口")
        self._opened = True
        self._port_name = port_name or "FAKE"
        self._parser = FrameParser()
        self.connected.emit(f"FAKE://{self._port_name}")

    @Slot()
    def close_port(self) -> None:
        if not self._opened:
            return
        self._cancel_all_timers()
        self._opened = False
        self.disconnected.emit("用户断开（仿真）")

    @Slot(QByteArray)
    def send_bytes(self, payload) -> None:
        if isinstance(payload, QByteArray):
            payload = bytes(payload)
        elif isinstance(payload, (bytearray, memoryview)):
            payload = bytes(payload)
        if not self._opened:
            self.error.emit("发送失败：仿真串口未打开")
            return
        self.bytes_out.emit(len(payload))
        # 解析帧、生成回执
        try:
            frames = self._parser.feed(payload)
        except Exception as exc:
            self.error.emit(f"仿真解析输入异常：{exc}")
            return
        for fr in frames:
            self._handle_outgoing_frame(fr)

    # ---- 内部 ----
    def _handle_outgoing_frame(self, fr: Frame) -> None:
        """按飞控固件逻辑生成 0xA0 回执并异步注入。"""
        if fr.cmd == 0xF1:
            self._echo_f1(fr.data)
        elif fr.cmd == 0xF2:
            self._echo_f2(fr.data)
        elif fr.cmd == 0xF3:
            self._echo_f3(fr.data)
        # 其它 CMD 静默丢弃（飞控也不会回执）

    def _echo_f1(self, data: bytes) -> None:
        if len(data) < 4:
            return
        x, y = struct.unpack_from("<hh", data, 0)
        self._schedule_echo(COLOR_GREEN, f"F1: X={x} Y={y}")

    def _echo_f2(self, data: bytes) -> None:
        if len(data) < 5:
            return
        pid = data[0]
        value = struct.unpack_from("<f", data, 1)[0]
        if pid not in (_PARAM_ID_GOAL_X, _PARAM_ID_GOAL_Y, _PARAM_ID_GOAL_Z):
            # 未知 ID → 红字 UNK
            self._schedule_echo(COLOR_RED, f"P{pid:02X} UNK")
            return
        # 限幅
        clamped = False
        if value > _PARAM_GOAL_LIMIT_CM:
            value = _PARAM_GOAL_LIMIT_CM
            clamped = True
        elif value < -_PARAM_GOAL_LIMIT_CM:
            value = -_PARAM_GOAL_LIMIT_CM
            clamped = True
        text = f"P{pid:02X}={value:.1f}"
        if clamped:
            text += " CLP"
        self._schedule_echo(COLOR_GREEN, text)

    def _echo_f3(self, data: bytes) -> None:
        """0xF3 三轴目标同帧写入：DATA = float_LE × 3，回执 ``P*=x,y,z[ CLP]``。"""
        if len(data) < 12:
            return
        x, y, z = struct.unpack_from("<fff", data, 0)
        clamped = False
        axes = []
        for v in (x, y, z):
            if v > _PARAM_GOAL_LIMIT_CM:
                v = _PARAM_GOAL_LIMIT_CM
                clamped = True
            elif v < -_PARAM_GOAL_LIMIT_CM:
                v = -_PARAM_GOAL_LIMIT_CM
                clamped = True
            axes.append(v)
        text = f"P*={axes[0]:.1f},{axes[1]:.1f},{axes[2]:.1f}"
        if clamped:
            text += " CLP"
        self._schedule_echo(COLOR_GREEN, text)

    def _schedule_echo(self, color: int, text: str) -> None:
        timer = QTimer(self)
        timer.setSingleShot(True)
        # 闭包捕获，避免 lambda 共享变量
        def _fire(c=color, t=text, tm=timer) -> None:
            try:
                if not self._opened:
                    return
                fr = _make_a0_frame(c, t)
                self.bytes_in.emit(len(fr.raw))
                self.frame_received.emit(fr)
            finally:
                # 清理自身
                try:
                    self._pending_timers.remove(tm)
                except ValueError:
                    pass
                tm.deleteLater()
        timer.timeout.connect(_fire)
        self._pending_timers.append(timer)
        timer.start(ECHO_DELAY_MS)

    def _cancel_all_timers(self) -> None:
        for tm in list(self._pending_timers):
            tm.stop()
            tm.deleteLater()
        self._pending_timers.clear()
