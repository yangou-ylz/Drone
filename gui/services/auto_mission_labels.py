# -*- coding: utf-8 -*-
"""自主任务状态的人读中文显示层。

底层协议和 STM32 A0/F8 字段保持英文/数值不变；这里仅负责 GUI 展示。
"""
from __future__ import annotations

import re
from typing import Any


STATE_LABELS = {
    0: "空闲",
    1: "预检中",
    2: "请求定点",
    3: "等待定点稳定",
    4: "干运行:解锁段",
    5: "干运行:地面稳定",
    6: "干运行:起飞段",
    7: "干运行:悬停段",
    8: "干运行:降落段",
    9: "干运行:上锁段",
    10: "请求解锁",
    11: "等待解锁确认",
    12: "地面稳定等待",
    13: "发送起飞命令",
    14: "等待起飞窗口",
    15: "悬停计时",
    16: "发送降落命令",
    17: "等待降落/落地",
    18: "请求上锁",
    19: "完成",
    20: "中止降落",
    21: "急停上锁",
    22: "错误",
}

CMD_LABELS = {
    0x00: "查询状态",
    0x01: "预检",
    0x02: "请求定点",
    0x03: "起降干运行",
    0x04: "正式低高度起降",
    0x05: "中止并降落",
    0x06: "强制上锁",
    0x07: "清错误",
    0x08: "释放遥控权",
    0x09: "锁定遥控权",
}

ERROR_LABELS = {
    0x0000: "正常",
    0x0001: "帧长度错误",
    0x0002: "协议版本错误",
    0x0003: "安全钥匙错误",
    0x0004: "参数错误",
    0x0005: "重复序号",
    0x0006: "未知命令",
    0x0010: "电压无效",
    0x0011: "模式不满足",
    0x0012: "当前已解锁",
    0x0013: "等待校验忙",
    0x0014: "外部速度无效",
    0x0015: "外部测高无效",
    0x0020: "切定点超时",
    0x0030: "解锁超时",
    0x0040: "起飞等待超时",
    0x0041: "起飞未离地",
    0x0050: "降落等待超时",
    0x0060: "用户中止",
    0x0061: "急停上锁",
    0x0070: "运行中电压异常",
    0x0071: "运行中模式丢失",
    0x0072: "运行中外部传感异常",
}

FLAG_LABELS = (
    (0x0001, "电压OK"),
    (0x0002, "定点"),
    (0x0004, "已解锁"),
    (0x0008, "禁XY"),
    (0x0010, "F5新鲜"),
    (0x0020, "任务中"),
    (0x0040, "外速OK"),
    (0x0080, "测高OK"),
    (0x0100, "AUTO锁RC"),
    (0x0200, "RC失控"),
    (0x0400, "RC无帧"),
    (0x0800, "RC保持帧"),
)

AUTO_EVENT_LABELS = {
    "QUERY": "查询状态",
    "PRECHECK": "开始预检",
    "PRECHECK_OK": "预检通过",
    "READY": "预检通过",
    "PRECHECK_FAIL": "预检失败",
    "MODE2_REQ": "发送定点请求",
    "MODE2_WAIT": "等待定点稳定",
    "MODE2_DENY": "拒绝定点",
    "DRY_DENY": "拒绝干运行",
    "START_DENY": "拒绝正式起降",
    "DRY_UNLOCK": "干运行:解锁段",
    "DRY_GROUND": "干运行:地面稳定",
    "DRY_TAKEOFF": "干运行:起飞段",
    "DRY_HOLD": "干运行:悬停段",
    "DRY_LAND": "干运行:降落段",
    "DRY_LOCK": "干运行:上锁段",
    "UNLOCK_REQ": "请求解锁",
    "WAIT_UNLOCK": "等待解锁确认",
    "GROUND_STABLE": "地面稳定等待",
    "TO_REF": "记录起飞高度基准",
    "TAKEOFF_REQ": "发送起飞命令",
    "WAIT_TAKEOFF": "等待起飞窗口",
    "LIFT_OK": "确认离地",
    "NO_LIFT": "起飞未离地",
    "TAKEOFF_NO_LIFT": "起飞未离地:转降落",
    "HOLD": "悬停计时",
    "LAND_REQ": "发送降落命令",
    "WAIT_LAND": "等待降落/落地",
    "LOCK_REQ": "请求上锁",
    "DONE": "完成",
    "ABORT_LAND": "中止:发送降落",
    "ABORT_WAIT_LAND": "中止:等待降落",
    "ABORT_LOCK": "中止:请求上锁",
    "EMERGENCY": "急停上锁",
    "CLEAR": "清错回空闲",
    "RC_RELEASE": "释放遥控权",
    "RC_LOCKOUT": "锁定遥控权",
    "ERR": "错误",
    "DUP": "重复命令",
    "NO_XY_REQUIRED": "缺少禁XY标志",
    "MODE2_WAITCK": "切定点指令忙",
    "UNLOCK_WAITCK": "解锁指令忙",
    "TAKEOFF_WAITCK": "起飞指令忙",
    "LAND_WAITCK": "降落指令忙",
    "LOCK_WAITCK": "上锁指令忙",
    "MODE2_TIMEOUT": "切定点超时",
    "UNLOCK_TIMEOUT": "解锁超时",
    "TAKEOFF_TIMEOUT": "起飞等待超时",
    "LAND_TIMEOUT": "降落等待超时",
    "RUNTIME_VOLT": "运行中电压异常",
    "RUNTIME_MODE": "运行中模式丢失",
    "RUNTIME_EXT": "运行中外部传感异常",
}

_AUTO_RE = re.compile(r"^AUTO\s+([A-Z0-9_]+)(.*)$", re.I)
_SEQ_RE = re.compile(r"\bseq=(\d+)\b", re.I)
_ERR_RE = re.compile(r"\berr=([0-9A-Fa-f]{4})\b", re.I)
_ALT_FIELD_RE = re.compile(r"\b([bhd])=(-?\d+)\b", re.I)


def state_label(state: int) -> str:
    return STATE_LABELS.get(int(state), f"未知状态{int(state)}")


def cmd_label(cmd: int) -> str:
    return CMD_LABELS.get(int(cmd), f"命令0x{int(cmd) & 0xFF:02X}")


def error_label(error: int, *, include_code: bool = True) -> str:
    error = int(error) & 0xFFFF
    text = ERROR_LABELS.get(error, "未知错误")
    if include_code:
        return f"{text}(0x{error:04X})"
    return text


def flag_labels(flags: int) -> list[str]:
    flags = int(flags) & 0xFFFF
    return [name for bit, name in FLAG_LABELS if flags & bit]


def flag_summary(flags: int, *, include_hex: bool = False) -> str:
    labels = flag_labels(flags)
    text = "/".join(labels) if labels else "无"
    if include_hex:
        text = f"{text} (0x{int(flags) & 0xFFFF:04X})"
    return text


def rc_control_label(sample: Any) -> str:
    return "AUTO锁定" if bool(sample.rc_lockout) else "RC可控"


def rc_input_label(sample: Any) -> str:
    if bool(sample.rc_no_signal):
        return "无接收帧"
    if bool(sample.rc_failsafe):
        return "失控保护"
    if bool(sample.rc_hold_frame):
        return "保持帧疑似关机"
    return "有效遥控帧"


def rc_input_color(sample: Any) -> str:
    if bool(sample.rc_no_signal):
        return "#777"
    if bool(sample.rc_failsafe) or bool(sample.rc_hold_frame):
        return "#C62828"
    return "#EF6C00"


def format_auto_a0_text(text: str) -> str:
    """把 STM32 的 AUTO A0 英文日志翻译成简短中文。"""
    raw = text.strip()
    m = _AUTO_RE.match(raw)
    if not m:
        return text
    event = m.group(1).upper()
    rest = m.group(2) or ""
    label = AUTO_EVENT_LABELS.get(event, event)
    parts = [label]
    seq = _SEQ_RE.search(rest)
    if seq:
        parts.append(f"seq={seq.group(1)}")
    err = _ERR_RE.search(rest)
    if err:
        try:
            err_int = int(err.group(1), 16)
            parts.append(f"错误={error_label(err_int)}")
        except ValueError:
            parts.append(f"错误=0x{err.group(1).upper()}")
    alt_fields = {m.group(1).lower(): m.group(2) for m in _ALT_FIELD_RE.finditer(rest)}
    if alt_fields:
        if "b" in alt_fields:
            parts.append(f"基准={alt_fields['b']}cm")
        if "h" in alt_fields:
            parts.append(f"当前={alt_fields['h']}cm")
        if "d" in alt_fields:
            parts.append(f"增量={alt_fields['d']}cm")
    return " ".join(parts)


def format_auto_status_log(sample: Any) -> str:
    f5_age = "--" if int(sample.f5_age_ms) >= 65535 else f"{int(sample.f5_age_ms)}ms"
    mode = "定点Mode2" if int(sample.mode) == 2 else f"Mode{int(sample.mode)}"
    unlock = "已解锁" if int(sample.unlock) else "已上锁"
    return (
        f"[F8] 状态={state_label(sample.state)} "
        f"错误={error_label(sample.error)} "
        f"命令={cmd_label(sample.last_cmd)} seq={int(sample.last_cmd_seq)} "
        f"模式={mode} 解锁={unlock} 电压={float(sample.voltage_v):.2f}V "
        f"高度={int(sample.alt_cm)}cm "
        f"外速={'正常' if sample.ext_vel_ok else '无效'} "
        f"测高={'正常' if sample.ext_alt_ok else '无效'} "
        f"F5={f5_age} RC={rc_control_label(sample)} "
        f"遥控={rc_input_label(sample)} "
        f"标志={flag_summary(sample.flags, include_hex=True)}"
    )
