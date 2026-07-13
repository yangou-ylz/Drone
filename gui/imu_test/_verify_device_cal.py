# -*- coding: utf-8 -*-
"""临时验证脚本：设备校准 Tab（Phase B）。

用法：DISPLAY=:1 ./.venv-linux/bin/python -m gui.imu_test._verify_device_cal
- 构造 ImuTestWindow（带假 send_frame_fn），切到「设备校准」页
- 向 hub 灌入几条假的 0xA0 提示，验证终端着色显示
- 截图保存 /tmp/device_cal_fb.png
验证完成后请删除本文件。
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from gui.imu_test.data_hub import ImuDataHub
from gui.imu_test.imu_test_window import ImuTestWindow
from groundTest.ano_protocol import build_frame, FrameParser


def _fake_send(frame: bytes) -> bool:
    print("SEND:", " ".join(f"{b:02X}" for b in frame))
    return True


def main() -> int:
    app = QApplication(sys.argv)
    hub = ImuDataHub()
    win = ImuTestWindow(hub, None, send_frame_fn=_fake_send)
    # 切到设备校准页
    for i in range(win._tabs.count()):
        if win._tabs.tabText(i) == "设备校准":
            win._tabs.setCurrentIndex(i)
            break
    win.resize(1000, 640)
    win.show()

    # 灌入假 0xA0 提示（模拟凌霄 IMU 回传）：color 0=白, 1=红, 2=绿
    parser = FrameParser()
    for color, text in [
        (2, "陀螺仪校准完成"),
        (0, "请把机头向上放置"),
        (2, "罗盘校准完成"),
        (1, "校准失败，请重试"),
    ]:
        data = bytes([color]) + text.encode("gbk")
        raw = build_frame(0xAF, 0xA0, data)
        for fr in parser.feed(raw):
            hub.on_frame(fr)

    app.processEvents()
    QApplication.processEvents()

    img = win.grab()
    img.save("/tmp/device_cal_fb.png")
    print("saved /tmp/device_cal_fb.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
