# -*- coding: utf-8 -*-
"""列出所有可用串口。"""
from serial.tools import list_ports


def main():
    ports = list(list_ports.comports())
    if not ports:
        print("(未发现任何串口)")
        return
    print(f"{'PORT':<10} {'DESCRIPTION':<40} {'HWID'}")
    print("-" * 80)
    for p in ports:
        print(f"{p.device:<10} {p.description:<40} {p.hwid}")


if __name__ == "__main__":
    main()
