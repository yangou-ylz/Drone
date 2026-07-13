# -*- coding: utf-8 -*-
"""SerialWorker —— 串口 I/O 工作线程。

设计要点（与全局架构强约束一致）：
- 严格单线程独占 :class:`Win32Serial`，UI 线程禁止直接读写串口。
- TX 路径：UI 线程通过 ``invokeMethod(worker, "send_bytes", Qt.QueuedConnection)``
  把字节排入 Qt 事件队列，由 worker 线程串行化执行 —— 天然防 TX 冲突。
- RX 路径：worker 在 :meth:`run` 中轮询 ``read_nonblocking``，把原始字节喂给
  :class:`FrameParser` 状态机，逐帧通过信号上抛到 UI 线程。
- 异常处理：所有 I/O 操作均 try/except 兜底，错误以 :attr:`error` 信号上抛，
  绝不静默崩溃；致命错误后自动 close 并发 :attr:`disconnected`。
"""
from __future__ import annotations

import os
import sys
import time
from collections import deque
from typing import Optional

from PySide6.QtCore import QByteArray, QCoreApplication, QObject, QThread, Signal, Slot

# 把 groundTest 目录加入 sys.path，复用 Win32Serial
_GROUNDTEST_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "groundTest")
)
if _GROUNDTEST_DIR not in sys.path:
    sys.path.insert(0, _GROUNDTEST_DIR)

import sys as _sys
if _sys.platform == "win32":
    from win_serial import Win32Serial as SerialImpl  # noqa: E402
else:
    from linux_serial import LinuxSerial as SerialImpl  # noqa: E402
from .protocol import Frame, FrameParser  # noqa: E402


# 轮询参数：read_nonblocking 单次等待 + 主循环空闲让权
_READ_WAIT_S = 0.02   # 单次 ReadFile 最长阻塞 20ms
_IDLE_SLEEP_S = 0.001  # 完全无数据时再小睡 1ms，CPU 占用可忽略


class SerialWorker(QObject):
    """运行在独立 QThread 中的串口 I/O 对象。

    使用方式（在 UI 线程）::

        self._thread = QThread()
        self._worker = SerialWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start_loop)
        # 信号订阅
        self._worker.frame_received.connect(self._on_frame)
        self._worker.error.connect(self._on_error)
        ...
        self._thread.start()

        # 打开/发送/关闭（线程安全）
        QMetaObject.invokeMethod(self._worker, "open_port",
                                 Qt.QueuedConnection,
                                 Q_ARG(str, "COM11"))
        QMetaObject.invokeMethod(self._worker, "send_bytes",
                                 Qt.QueuedConnection,
                                 Q_ARG("QByteArray", payload))

    阶段 A 仅保证：可以启动、open/close、能把入站 0xA0 帧抛出来。
    """

    # ---- 信号 ----
    connected = Signal(str)                 # 串口名
    disconnected = Signal(str)              # 原因
    error = Signal(str)                     # 错误文本（人读）
    frame_received = Signal(object)         # 一帧解析成功的 Frame
    bytes_in = Signal(int)                  # 入站字节计数增量
    bytes_out = Signal(int)                 # 出站字节计数增量

    def __init__(self) -> None:
        super().__init__()
        self._ser: Optional[object] = None
        self._port_name: str = ""
        self._parser = FrameParser()
        self._stop = False
        # 入站字节计数批量上报，避免每字节都触发 UI 刷新
        self._rx_accum = 0
        self._last_emit_ts = 0.0

    # ---- 线程入口 ----
    @Slot()
    def start_loop(self) -> None:
        """QThread.started 触发的入口；进入主循环直到 :meth:`stop` 被调用。

        关键：每轮都要调用 ``QCoreApplication.processEvents()`` 派发
        UI 线程通过 ``QueuedConnection`` 投递过来的槽调用（open_port/
        send_bytes/close_port），否则点击「连接」会石沉大海。
        """
        self._stop = False
        try:
            while not self._stop:
                # 先把 UI 线程排队过来的槽调用全部派发掉
                QCoreApplication.processEvents()
                if self._stop:
                    break
                if self._ser is None:
                    # 未连接时不空转 CPU
                    QThread.msleep(20)
                    continue
                self._pump_once()
        except Exception as exc:  # 兜底：任何漏网异常都要上抛
            self._safe_emit_error(f"串口工作线程崩溃：{exc!r}")
        finally:
            self._close_port_internal("worker 退出")

    @Slot()
    def stop(self) -> None:
        """请求退出主循环。UI 线程调用。"""
        self._stop = True

    # ---- 公共槽：open/close/send ----
    @Slot(str)
    def open_port(self, port_name: str) -> None:
        """打开串口；若已打开会先关闭旧口。"""
        if self._ser is not None:
            self._close_port_internal("切换串口")
        try:
            ser = SerialImpl(port_name)
            ser.open()
        except Exception as exc:
            self._safe_emit_error(f"打开串口 {port_name} 失败：{exc}")
            return
        self._ser = ser
        self._port_name = port_name
        self._parser = FrameParser()  # 清空解析状态
        self.connected.emit(port_name)

    @Slot()
    def close_port(self) -> None:
        """主动关闭串口（不视为错误）。"""
        self._close_port_internal("用户断开")

    @Slot(QByteArray)
    def send_bytes(self, payload) -> None:
        """发送一段字节流。线程安全（通过 QueuedConnection 调用）。

        跨线程调用时 ``payload`` 是 QByteArray（bytes 不是注册的 QMetaType），
        本地调用也兼容 bytes/bytearray。进入实际写口前统一转 bytes。
        """
        if isinstance(payload, QByteArray):
            payload = bytes(payload)
        elif isinstance(payload, (bytearray, memoryview)):
            payload = bytes(payload)
        if self._ser is None:
            self._safe_emit_error("发送失败：串口未连接")
            return
        try:
            n = self._ser.write(payload)
            if n != len(payload):
                self._safe_emit_error(
                    f"发送字节数不匹配：期望 {len(payload)} 实写 {n}"
                )
                return
            self.bytes_out.emit(n)
        except Exception as exc:
            self._safe_emit_error(f"写串口异常：{exc}")
            self._close_port_internal("写异常")

    # ---- 内部 ----
    def _pump_once(self) -> None:
        """单次 RX 抽取：读 -> 喂解析器 -> emit 帧。"""
        assert self._ser is not None
        try:
            data = self._ser.read_nonblocking(max_bytes=4096, wait_s=_READ_WAIT_S)
        except Exception as exc:
            self._safe_emit_error(f"读串口异常：{exc}")
            self._close_port_internal("读异常")
            return
        if not data:
            time.sleep(_IDLE_SLEEP_S)
            return
        # 计数批量上报（>=50ms 或 >=512B）
        self._rx_accum += len(data)
        now = time.time()
        if self._rx_accum >= 512 or (now - self._last_emit_ts) >= 0.05:
            self.bytes_in.emit(self._rx_accum)
            self._rx_accum = 0
            self._last_emit_ts = now
        # 喂解析器
        try:
            frames = self._parser.feed(data)
        except Exception as exc:
            self._safe_emit_error(f"帧解析异常：{exc}")
            return
        for fr in frames or []:
            # Frame 是 dataclass，跨线程传递安全
            self.frame_received.emit(fr)

    def _close_port_internal(self, reason: str) -> None:
        if self._ser is None:
            return
        try:
            self._ser.close()
        except Exception as exc:
            # close 失败只打报警，不抛
            self._safe_emit_error(f"关闭串口异常：{exc}")
        port = self._port_name
        self._ser = None
        self._port_name = ""
        # 最后清空残留计数
        if self._rx_accum:
            self.bytes_in.emit(self._rx_accum)
            self._rx_accum = 0
        self.disconnected.emit(f"{port}（{reason}）" if port else reason)

    def _safe_emit_error(self, msg: str) -> None:
        """发 error 信号，本身再失败也不抛出。"""
        try:
            self.error.emit(msg)
        except Exception:
            # 信号本身不应失败，万一连发信号也炸，至少 stderr 留痕
            print(f"[SerialWorker.error] {msg}", file=sys.stderr)
