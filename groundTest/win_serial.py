# -*- coding: utf-8 -*-
"""
极简 Win32 串口：用 CreateFile 直接打开 COM 口，跳过 SetCommState。

适配场景：匿名数传等设备驱动不接受标准 SetCommState（波特率由驱动固化），
导致 pyserial / .NET SerialPort 报 ERROR_GEN_FAILURE(31)。直接 CreateFile
打开就能用驱动内置的配置正常读写。

仅暴露最小接口：open / write / read_nonblocking / close。
"""
from __future__ import annotations
import ctypes
import time
from ctypes import wintypes, byref

_k = ctypes.windll.kernel32

GENERIC_READ  = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = 0xFFFFFFFFFFFFFFFF  # 64位下；32位下是 0xFFFFFFFF；与 -1 兼容判断
MAXDWORD = 0xFFFFFFFF


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


class Win32Serial:
    def __init__(self, port: str):
        # 支持 'COM11' 或 '\\.\COM11'。COM10+ 必须用 \\.\ 前缀才能被 CreateFile 打开。
        if not port.startswith("\\\\.\\"):
            port = "\\\\.\\" + port
        self._port = port
        self._h = None

    def open(self) -> None:
        h = _k.CreateFileW(
            self._port,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h == 0 or h == INVALID_HANDLE_VALUE or h == -1:
            err = ctypes.get_last_error()
            raise OSError(f"CreateFile {self._port} failed, GetLastError={err}")
        self._h = h
        # 关键：设置非阻塞读超时。默认 COMMTIMEOUTS 全 0 时 ReadFile 会
        # 一直阻塞到至少 1 字节到达；这会让 GUI 工作线程卡死，导致用户
        # 点"断开"按钮时 QueuedConnection 槽永远等不到执行（无人机不在
        # 身边、无数据流入时尤其明显）。
        # ReadIntervalTimeout=MAXDWORD + 其余为 0 → ReadFile 立即返回
        # 缓冲区里已有的字节（哪怕是 0 字节）。
        timeouts = COMMTIMEOUTS(
            ReadIntervalTimeout=MAXDWORD,
            ReadTotalTimeoutMultiplier=0,
            ReadTotalTimeoutConstant=0,
            WriteTotalTimeoutMultiplier=0,
            WriteTotalTimeoutConstant=0,
        )
        if not _k.SetCommTimeouts(self._h, byref(timeouts)):
            err = ctypes.get_last_error()
            # 不致命：部分驱动可能拒绝；最差行为退化为旧版（仍能用，
            # 但断开响应可能变慢）
            print(f"[Win32Serial] SetCommTimeouts 失败 GetLastError={err}（继续）")

    def write(self, data: bytes) -> int:
        if self._h is None:
            raise RuntimeError("port not open")
        n = wintypes.DWORD()
        ok = _k.WriteFile(self._h, data, len(data), byref(n), None)
        if not ok:
            raise OSError(f"WriteFile failed, GetLastError={ctypes.get_last_error()}")
        return n.value

    def read_nonblocking(self, max_bytes: int = 4096, wait_s: float = 0.05) -> bytes:
        """
        阻塞最多 wait_s 秒等待数据。底层 ReadFile 行为依驱动设置而定，
        这里用轮询 + 短 sleep 的方式适配大多数 COM 驱动。
        """
        if self._h is None:
            raise RuntimeError("port not open")
        deadline = time.time() + wait_s
        buf = (ctypes.c_ubyte * max_bytes)()
        n = wintypes.DWORD()
        while True:
            ok = _k.ReadFile(self._h, buf, max_bytes, byref(n), None)
            if ok and n.value > 0:
                return bytes(buf[: n.value])
            if time.time() >= deadline:
                return b""
            time.sleep(0.01)

    def close(self) -> None:
        if self._h is not None:
            _k.CloseHandle(self._h)
            self._h = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
