# -*- coding: utf-8 -*-
"""serial_ports —— 纯标准库枚举本机串口（不打开，不触发 SetCommState）。

原理：读取注册表 ``HKLM\\HARDWARE\\DEVICEMAP\\SERIALCOMM``，列出系统所有
已注册的 COM 设备。该路径仅做 *枚举*，不会向驱动发送任何指令，因此对匿名
数传这类拒绝 SetCommState 的 USB-CDC 设备完全安全。

返回：``[(port_name, friendly_name), ...]``，按 COM 编号升序。
"""
from __future__ import annotations

import glob
import os
import sys


def list_serial_ports() -> list[tuple[str, str]]:
    """枚举 COM 口。失败回空列表，绝不抛异常。"""
    if sys.platform != "win32":
        patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*", "/dev/ttyS*"]
        ports = []
        for pattern in patterns:
            ports.extend(glob.glob(pattern))
        ports = sorted(set(ports))
        return [(pp, os.path.basename(pp)) for pp in ports]
    try:
        import winreg  # type: ignore
    except Exception:
        return []
    results: list[tuple[str, str]] = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
        ) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                # value = "COM11"; name = "\\Device\\...\\Serial0"
                results.append((str(value), str(name)))
                i += 1
    except FileNotFoundError:
        # 系统无任何串口
        return []
    except Exception:
        return []

    def _sort_key(item: tuple[str, str]) -> tuple[int, str]:
        port = item[0]
        try:
            return (int(port.lstrip("COM")), port)
        except ValueError:
            return (10_000, port)

    results.sort(key=_sort_key)
    return results
