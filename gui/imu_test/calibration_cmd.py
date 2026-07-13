# -*- coding: utf-8 -*-
"""凌霄 IMU 硬件校准命令（0xE0 CMD 命令帧）。

依据：项目内官方手册 `用户手册/匿名通信协议V7.pdf` 的「0xE0 CMD 命令帧 / 命令定义」，
并与飞控固件 `FcSrc/LX_FC_Fun.c` 中现有的校准函数逐字节核对一致（固件为准）。

数据路径：电脑 → 匿名数传 → 凌霄IMU → STM32。校准是 IMU 级命令，
广播地址 0xFF 发出后由凌霄 IMU 自身执行，过程提示通过 0xA0 字符串帧回传。

帧结构（与固件 CMD_Send 一致）：
    AA  FF  E0  0B  | CID  CMD0  CMD1  CMD2..CMD9(共10字节)  | SC  AC
    DATA 区 = CID + CMD0~CMD9，共 11 字节（LEN=0x0B）。
"""
from __future__ import annotations

from dataclasses import dataclass

from gui.io.protocol import ADDR_BROADCAST, build_frame

# 0xE0 CMD 命令帧功能码
_CMD_FRAME_ID = 0xE0


@dataclass(frozen=True)
class CalibrationDef:
    """一项校准的定义（命令字节 + 面向用户的说明）。"""

    key: str          # 内部键
    name: str         # 显示名
    cid: int          # CID
    cmd0: int         # CMD0
    cmd1: int         # CMD1
    principle: str    # 原理说明（面向用户）
    steps: str        # 操作提示（校准时怎么做）


# 校准项定义（命令字节严格取自固件 LX_FC_Fun.c）
CALIBRATIONS: tuple[CalibrationDef, ...] = (
    CalibrationDef(
        key="gyro",
        name="陀螺仪校准",
        cid=0x01, cmd0=0x00, cmd1=0x02,
        principle=(
            "陀螺仪测量角速度，静止时三轴应读数为 0。长期使用或温漂会产生零偏，"
            "静止时也输出微小角速度，积分后姿态缓慢漂移。本校准在静止状态下测量并"
            "存储三轴零偏，之后由 IMU 自动扣除。"
        ),
        steps="把飞控水平静置在稳固桌面，保持完全静止，然后点击校准。约 1~2 秒完成。",
    ),
    CalibrationDef(
        key="level",
        name="快速水平校准",
        cid=0x01, cmd0=0x00, cmd1=0x03,
        principle=(
            "加速度计安装存在微小倾斜，导致飞控水平放置时 roll/pitch 不为 0。"
            "本校准以当前静止姿态为水平基准，修正安装倾角，使水平放置时姿态角归零。"
        ),
        steps="把飞控按实际水平安装状态静置平稳，保持不动，然后点击校准。",
    ),
    CalibrationDef(
        key="mag",
        name="磁力计校准",
        cid=0x01, cmd0=0x00, cmd1=0x04,
        principle=(
            "磁力计（罗盘）会受机体铁磁材料与电流磁场干扰（硬磁偏置 + 软磁畸变）。"
            "校准需绕各轴缓慢旋转飞机、采集各方向磁场，拟合成椭球求出偏置与缩放，"
            "使输出还原为真实地磁方向。室内磁环境差时罗盘可能不可用。"
        ),
        steps="点击后按 IMU 提示旋转飞机（通常绕三轴各转一圈 / 画 8 字），直到提示完成。",
    ),
    CalibrationDef(
        key="acc6",
        name="6面加速度校准",
        cid=0x01, cmd0=0x00, cmd1=0x05,
        principle=(
            "加速度计三轴各有零偏和刻度误差。6 面校准依次把飞控的 6 个面（上/下/前/后/左/右）"
            "分别朝上静置，每个面采集一次重力矢量，拟合出三轴的零偏与刻度系数，"
            "保证静止时合加速度精确等于 1g。"
        ),
        steps=(
            "点击后按 IMU 提示依次摆放 6 个面（例如“请把机头向上放置”），"
            "每个面保持静止直到提示切换，直到全部完成。"
        ),
    ),
)

# key → 定义 的索引
CALIBRATION_BY_KEY: dict[str, CalibrationDef] = {c.key: c for c in CALIBRATIONS}


def build_cal_frame(cal: CalibrationDef) -> bytes:
    """把一项校准定义组装为完整的 0xE0 CMD 帧（含 SC/AC 校验）。

    DATA = CID + CMD0~CMD9（共 11 字节），CMD2~CMD9 全填 0（NA）。
    目标地址固定广播 0xFF（由凌霄 IMU 接收执行）。
    """
    data = bytes([cal.cid & 0xFF, cal.cmd0 & 0xFF, cal.cmd1 & 0xFF] + [0] * 8)
    return build_frame(ADDR_BROADCAST, _CMD_FRAME_ID, data)
