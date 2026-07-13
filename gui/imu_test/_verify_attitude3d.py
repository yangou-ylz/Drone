# -*- coding: utf-8 -*-
"""临时可视化验证：注入已知姿态，截图 Attitude3DPanel。

用法（真实桌面 DISPLAY=:1）：
    DISPLAY=:1 ./.venv-linux/bin/python -m gui.imu_test._verify_attitude3d yaw45
参数决定注入的姿态场景，输出 /tmp/attitude3d_<name>.png。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from gui.imu_test.widgets.attitude_3d_panel import Attitude3DPanel


SCENES = {
    "level": (0.0, 0.0, 0.0),
    "yaw45": (0.0, 0.0, 45.0),      # 机头右转 45°（俯视顺时针）
    "yaw90": (0.0, 0.0, 90.0),
    "roll30": (30.0, 0.0, 0.0),
    "pitch20": (0.0, 20.0, 0.0),
    "mix": (20.0, 15.0, 40.0),
}


def main() -> int:
    name = sys.argv[1] if len(sys.argv) > 1 else "yaw45"
    roll, pitch, yaw = SCENES.get(name, SCENES["yaw45"])

    app = QApplication(sys.argv)
    panel = Attitude3DPanel()
    panel.setWindowFlags(panel.windowFlags() | Qt.FramelessWindowHint)
    panel.resize(760, 760)
    panel.move(0, 0)
    panel.show()

    # 注入姿态
    att = SimpleNamespace(roll_deg=roll, pitch_deg=pitch, yaw_deg=yaw)
    panel.on_attitude(att)

    def _shoot():
        # 用 QScreen.grabWindow 捕获真实屏幕像素（含 OpenGL）
        screen = app.primaryScreen()
        pix = screen.grabWindow(panel.winId())
        out = f"/tmp/attitude3d_{name}.png"
        pix.save(out)
        print(f"[SAVED] {out}  scene roll={roll} pitch={pitch} yaw={yaw}")
        # 直接抓 GL framebuffer（无窗口 chrome，最真实的 3D 视口）
        try:
            img = panel._view.grabFramebuffer()
            out2 = f"/tmp/attitude3d_{name}_fb.png"
            img.save(out2)
            print(f"[SAVED] {out2}")
        except Exception as e:
            print(f"[FB-ERR] {e}")
        app.quit()

    # 等几帧刷新后再截图
    QTimer.singleShot(1200, _shoot)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
