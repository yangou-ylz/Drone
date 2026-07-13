# -*- coding: utf-8 -*-
"""与 Win32Serial 接口兼容的最小 Linux 串口封装（基于 pyserial）。

暴露与 groundTest/win_serial.py 的 Win32Serial 相同的方法签名：
- open() / close() / write(data) / read_nonblocking(max_bytes, wait_s)
- 上下文管理器 __enter__ / __exit__

这样 gui/io/serial_worker.py 可以在非 Windows 平台无缝替换实现。
"""
from __future__ import annotations

import time

import serial


class LinuxSerial:
    """Win32Serial 的 Linux 兼容实现。"""

    def __init__(self, port: str, baudrate: int = 500000) -> None:
        self._port = port
        self._baudrate = baudrate
        self._ser = None  # type: ignore[assignment]

    def open(self) -> None:
        self._ser = serial.Serial(
            self._port,
            self._baudrate,
            timeout=0,
            write_timeout=0.2,
        )

    def write(self, data: bytes) -> int:
        if self._ser is None:
            raise RuntimeError("port not open")
        return int(self._ser.write(data))

    def read_nonblocking(self, max_bytes: int = 4096, wait_s: float = 0.05) -> bytes:
        if self._ser is None:
            raise RuntimeError("port not open")
        deadline = time.time() + wait_s
        while time.time() < deadline:
            n = int(self._ser.in_waiting or 0)
            if n > 0:
                return bytes(self._ser.read(min(max_bytes, n)))
            time.sleep(0.005)
        return b""

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self) -> "LinuxSerial":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
