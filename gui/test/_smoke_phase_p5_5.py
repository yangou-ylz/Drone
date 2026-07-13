# -*- coding: utf-8 -*-
"""P5.5 烟雾测试：传感器帧记录（JSONL）+ 轴箭头/标签字段。

验证：
- FrameRecorder.start/stop 生命周期、写入 _meta 头尾
- on_frame 过滤白名单（0x01/0x02/0x03/0x04/0x05/0x06/0x07/0x08/0x0E），
  非传感器帧（0xE0/0xA0/0x41）被忽略
- 已知帧解析正确：0x03 姿态、0x05 高度、0x08 XY 位置
- DEFAULTS["axis"] 含 head_radius_cm / head_length_cm / labels_visible
- DEFAULTS["vel_arrow"] 含 head_radius_cm / head_length_cm
- _make_cone_mesh 输出非空

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe gui\\test\\_smoke_phase_p5_5.py
通过：EXIT=0 + [P5.5-x] OK。
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.io.protocol import Frame  # noqa: E402
from gui.services.frame_recorder import FrameRecorder, RECORD_CMDS  # noqa: E402
from gui.widgets.path_visualization_widget import (  # noqa: E402
    DEFAULTS as W_DEFAULTS,
    _make_cone_mesh,
)


def _mk_frame(cmd: int, data: bytes) -> Frame:
    return Frame(dest=0xFF, cmd=cmd, data=data, sc=0, ac=0,
                 raw=bytes([0xAA, 0xFF, cmd, len(data)]) + data + bytes([0, 0]))


def case_1_record_lifecycle() -> None:
    """[P5.5-1] 启停 + _meta 头尾。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    rec = FrameRecorder()
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "t1.jsonl")
        assert rec.start(path) is True
        assert rec.is_recording is True
        rec.stop()
        assert rec.is_recording is False
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        # 至少 2 行：_meta 头 + _meta 尾
        assert len(lines) >= 2
        head = json.loads(lines[0])
        tail = json.loads(lines[-1])
        assert head.get("_meta") and head.get("format") == "lingxiao-jsonl-v1"
        assert tail.get("_meta") and "stopped_iso" in tail
    print("[P5.5-1] FrameRecorder 生命周期 + _meta 头尾 OK")


def case_2_record_filter_whitelist() -> None:
    """[P5.5-2] 仅记录状态传感器帧，命令/控制/日志帧被忽略。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    rec = FrameRecorder()
    with tempfile.TemporaryDirectory() as td:
        path = str(Path(td) / "t2.jsonl")
        rec.start(path)
        # 模拟一个 0x03 姿态帧（LEN 7：roll/pitch/yaw 各 s16 ×100 + sta 1字节）
        f_03 = _mk_frame(0x03, struct.pack("<hhhB", 150, -200, 4500, 0))
        # 0x05 对地高度 s32 cm
        f_05 = _mk_frame(0x05, struct.pack("<i", 125))
        # 0x08 XY 位置
        f_08 = _mk_frame(0x08, struct.pack("<ii", 100, -50))
        # 非白名单：0xE0 / 0xA0 / 0x41
        f_e0 = _mk_frame(0xE0, b"\x01\x02")
        f_a0 = _mk_frame(0xA0, b"hello")
        f_41 = _mk_frame(0x41, b"\x00" * 12)
        for f in (f_03, f_05, f_08, f_e0, f_a0, f_41):
            rec.on_frame(f)
        rec.stop()
        assert rec.count == 3, f"count={rec.count}"
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        # 跳过 _meta 头，取数据行
        data_lines = [json.loads(l) for l in lines[1:-1]]
        cmds = [int(d["cmd"], 16) for d in data_lines]
        assert cmds == [0x03, 0x05, 0x08]
        # 0x03 应解出 roll/pitch/yaw
        assert "fields" in data_lines[0] and "roll_deg" in data_lines[0]["fields"]
        # 0x08 应解出 pos_x_cm / pos_y_cm
        assert data_lines[2]["fields"]["pos_x_cm"] == 100
        assert data_lines[2]["fields"]["pos_y_cm"] == -50
        # dest 字段名（不是 addr）
        assert "dest" in data_lines[0] and data_lines[0]["dest"] == "0xFF"
    print("[P5.5-2] 白名单过滤 + 字段解析 + dest 字段名 OK")


def case_3_record_cmds_set() -> None:
    """[P5.5-3] RECORD_CMDS 准确含所有状态传感器帧。"""
    expected = {0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x0E}
    assert RECORD_CMDS == expected, f"实际={sorted(RECORD_CMDS):x}"
    print("[P5.5-3] RECORD_CMDS 白名单内容 OK")


def case_4_defaults_axis_arrow_fields() -> None:
    """[P5.5-4] DEFAULTS.axis/vel_arrow 含箭头头与字标字段。"""
    ax = W_DEFAULTS["axis"]
    for k in ("head_radius_cm", "head_length_cm", "labels_visible", "label_size", "label_offset_cm"):
        assert k in ax, f"axis missing {k}"
    assert ax["labels_visible"] is True
    va = W_DEFAULTS["vel_arrow"]
    for k in ("head_radius_cm", "head_length_cm"):
        assert k in va, f"vel_arrow missing {k}"
    print("[P5.5-4] DEFAULTS 含 axis/vel_arrow 新字段 OK")


def case_5_cone_mesh_nonempty() -> None:
    """[P5.5-5] _make_cone_mesh 生成非空 mesh。"""
    md = _make_cone_mesh(2.0, 5.0, cols=12)
    assert md is not None
    verts = md.vertexes()
    faces = md.faces()
    # apex + base_center + 12 rim points = 14 顶点
    assert verts.shape[0] == 14, f"verts={verts.shape}"
    # 侧面 12 三角 + 底面 12 三角 = 24 面
    assert faces.shape[0] == 24, f"faces={faces.shape}"
    # 退化输入 → None
    assert _make_cone_mesh(0.0, 5.0) is None
    assert _make_cone_mesh(2.0, 0.0) is None
    print("[P5.5-5] _make_cone_mesh 输出形状 OK")


def main() -> int:
    cases = [
        case_1_record_lifecycle,
        case_2_record_filter_whitelist,
        case_3_record_cmds_set,
        case_4_defaults_axis_arrow_fields,
        case_5_cone_mesh_nonempty,
    ]
    for c in cases:
        try:
            c()
        except BaseException as e:
            import traceback
            print(f"[P5.5 FAIL] {c.__name__}: {e}")
            traceback.print_exc()
            return 1
    print(f"\n[P5.5 OK] {len(cases)}/{len(cases)} cases passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
