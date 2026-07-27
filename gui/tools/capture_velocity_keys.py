# -*- coding: utf-8 -*-
"""Capture Qt key codes for GUI velocity control.

Run:
    .venv-linux/bin/python gui/tools/capture_velocity_keys.py

Click the small capture window if it is not focused, then press the prompted keys.
The saved key codes are used by ``自主飞行控制`` on next GUI start.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget  # noqa: E402


KEYMAP_FILE = _REPO_ROOT / "gui" / "keymaps" / "velocity_keys.json"
STEPS = [
    ("forward", "向上箭头", "前进 vx+"),
    ("back", "向下箭头", "后退 vx-"),
    ("left", "向左箭头", "左移 vy+"),
    ("right", "向右箭头", "右移 vy-"),
    ("yaw_left", "A", "左旋 yaw+"),
    ("yaw_right", "D", "右旋 yaw-"),
]


class CaptureWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("速度控制按键捕获")
        self.setMinimumSize(460, 150)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.index = 0
        self.keymap: dict[str, int] = {}
        layout = QVBoxLayout(self)
        self.prompt = QLabel()
        self.prompt.setStyleSheet("font-size:16px;font-weight:bold;")
        layout.addWidget(self.prompt)
        self.detail = QLabel("请让此窗口保持焦点。捕获完成后会写入 gui/keymaps/velocity_keys.json。")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self._show_prompt()

    def _show_prompt(self) -> None:
        if self.index >= len(STEPS):
            KEYMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            KEYMAP_FILE.write_text(
                json.dumps(self.keymap, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print("\n捕获完成，已保存：", KEYMAP_FILE)
            for action, _label, meaning in STEPS:
                print(f"  {action:10s} {meaning:12s} -> QtKey {self.keymap[action]}")
            self.prompt.setText("捕获完成，可以关闭窗口。")
            self.detail.setText(str(KEYMAP_FILE))
            return
        _action, label, meaning = STEPS[self.index]
        msg = f"第 {self.index + 1}/{len(STEPS)} 步：请按 {label}（{meaning}）"
        print(msg, flush=True)
        self.prompt.setText(msg)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.isAutoRepeat():
            event.accept()
            return
        if self.index >= len(STEPS):
            event.accept()
            return
        action, label, meaning = STEPS[self.index]
        key = int(event.key())
        self.keymap[action] = key
        print(f"  捕获 {label} / {meaning}: QtKey={key}", flush=True)
        self.index += 1
        self._show_prompt()
        event.accept()


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", os.environ.get("QT_QPA_PLATFORM", "xcb"))
    app = QApplication(sys.argv)
    win = CaptureWindow()
    win.show()
    win.activateWindow()
    win.raise_()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
