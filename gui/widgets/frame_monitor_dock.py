# -*- coding: utf-8 -*-
"""阶段D - 数据帧监视 Dock (FrameMonitorDock)。

显示飞控上报的所有已知数据帧；每帧占一行（折叠）→ 点击行展开字段明细。
有新数据到达时该行短暂闪绿（~0.8s），右侧实时显示帧速率（Hz）。

布局示意：
  ┌─[▶ 0x03  欧拉姿态  rol=10.2° pit=-2.1° yaw=45.0°  @ 100Hz]──────┐
  │  (点击后展开)                                                      │
  │    Roll:   10.20°                                                 │
  │    Pitch:  -2.10°                                                 │
  │    Yaw:    45.00°                                                 │
  │    融合状态: 0                                                     │
  │    原始DATA: 03 F8 EB 11 62 00                                    │
  │    完整帧:   AA FF 03 07 ... SC AC                                │
  └────────────────────────────────────────────────────────────────────┘

未出现在目录中的 CMD 在首次收到时动态添加到列表尾部。
"""
from __future__ import annotations

import struct
import time
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from gui.io.protocol import Frame


# ---------------------------------------------------------------------------
# 辅助：状态/模式名映射（与 flight_data_dock 保持一致）
# ---------------------------------------------------------------------------
_STA_NAMES: dict[int, str] = {0: "无数据", 1: "不可用", 2: "正常", 3: "良好"}
_MODE_NAMES: dict[int, str] = {0: "自稳", 1: "定高", 2: "定点", 3: "程控"}

# 行首活动指示灯样式（只在状态翻转时 setStyleSheet，避免每帧 repolish 整块样式）
_DOT_LIVE_QSS = "color: #2ecc71; font-size: 14px;"   # 新数据：亮绿
_DOT_IDLE_QSS = "color: #3a3a3a; font-size: 14px;"   # 静默：暗灰
_SUMMARY_LIVE_QSS = "font-family: Consolas,'Courier New',monospace; color: #e0e0e0;"
_SUMMARY_IDLE_QSS = "color: #666; font-family: Consolas,'Courier New',monospace;"
_DOT_FRESH_SEC = 0.8    # 活动灯保持绿色的时长
_UI_REFRESH_MS = 66     # 面板 UI 刷新周期（~15Hz），与数据速率解耦

# IMU 量纲换算
# 加速度：实测标定。静止平放时三轴合成模值应=1g，实测原始合成模值稳定在
# 1363 LSB（多次会话一致）。协议文档未给出加速度量程/分辨率定义，故此处
# 采用实测标定系数，而不是按 ±16g 假设；用 ±16g(0.000488) 会让静止读数偏
# 低约 33%（0.67g 而非 1.0g）。
_ACC_LSB_PER_G = 1363.4                       # 实测：1g 对应的原始 LSB
_ACC_LSB_TO_G = 1.0 / _ACC_LSB_PER_G          # ≈ 0.000733 g 每 LSB
_ACC_LSB_TO_MS2 = 9.80665 / _ACC_LSB_PER_G    # ≈ 0.007193 m/s² 每 LSB
_GYR_LSB_TO_DPS = 2000.0 / 32768.0           # ≈ 0.06104 °/s 每 LSB


# ---------------------------------------------------------------------------
# 格式化函数：接收 bytes，返回 (one_line_summary, detail_text)
# detail_text 是多行字符串，已含缩进
# ---------------------------------------------------------------------------

def _fmt_euler(data: bytes) -> tuple[str, str]:
    fmt = "<hhhB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    rol, pit, yaw, sta = struct.unpack(fmt, data)
    s = f"rol={rol/100:.1f}° pit={pit/100:.1f}° yaw={yaw/100:.1f}°"
    d = (f"  Roll:     {rol/100:.2f} °\n"
         f"  Pitch:    {pit/100:.2f} °\n"
         f"  Yaw:      {yaw/100:.2f} °\n"
         f"  融合状态: {sta}")
    return s, d


def _fmt_quat(data: bytes) -> tuple[str, str]:
    fmt = "<hhhhB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    v0, v1, v2, v3, sta = struct.unpack(fmt, data)
    s = f"w={v0/10000:.4f} x={v1/10000:.4f} y={v2/10000:.4f} z={v3/10000:.4f}"
    d = (f"  V0 (w): {v0/10000:.5f}\n"
         f"  V1 (x): {v1/10000:.5f}\n"
         f"  V2 (y): {v2/10000:.5f}\n"
         f"  V3 (z): {v3/10000:.5f}\n"
         f"  融合状态: {sta}")
    return s, d


def _fmt_height(data: bytes) -> tuple[str, str]:
    fmt = "<iiB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    fu, add, sta = struct.unpack(fmt, data)
    s = f"融合={fu}cm  附加={add}cm"
    d = f"  融合高度: {fu} cm\n  附加测高: {add} cm\n  状态: {sta}"
    return s, d


def _fmt_flight_mode(data: bytes) -> tuple[str, str]:
    fmt = "<BBBBB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    mode, locked, cid, cmd0, cmd1 = struct.unpack(fmt, data)
    mode_s = _MODE_NAMES.get(mode, str(mode))
    lock_s = "已解锁" if locked else "已锁定"
    s = f"{mode_s}  {lock_s}  CID={cid}"
    d = (f"  飞行模式: {mode_s} ({mode})\n"
         f"  锁定状态: {lock_s} ({locked})\n"
         f"  CID:  {cid}\n"
         f"  CMD0: {cmd0}\n"
         f"  CMD1: {cmd1}")
    return s, d


def _fmt_velocity(data: bytes) -> tuple[str, str]:
    fmt = "<hhh"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    vx, vy, vz = struct.unpack(fmt, data)
    s = f"vx={vx}  vy={vy}  vz={vz}  cm/s"
    d = f"  Vx: {vx} cm/s\n  Vy: {vy} cm/s\n  Vz: {vz} cm/s"
    return s, d


def _fmt_battery(data: bytes) -> tuple[str, str]:
    fmt = "<HH"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    volt, curr = struct.unpack(fmt, data)
    s = f"{volt/100:.2f}V  {curr/100:.2f}A"
    d = f"  电压: {volt/100:.2f} V\n  电流: {curr/100:.2f} A"
    return s, d


def _fmt_module_status(data: bytes) -> tuple[str, str]:
    fmt = "<BBBB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    gv, gp, gps, alt = struct.unpack(fmt, data)
    s = (f"G_VEL={_STA_NAMES.get(gv,'?')}  "
         f"G_POS={_STA_NAMES.get(gp,'?')}  "
         f"GPS={_STA_NAMES.get(gps,'?')}  "
         f"ALT={_STA_NAMES.get(alt,'?')}")
    d = (f"  通用速度传感器(G_VEL): {_STA_NAMES.get(gv, '?')} ({gv})\n"
         f"  通用位置传感器(G_POS): {_STA_NAMES.get(gp, '?')} ({gp})\n"
         f"  GPS:                  {_STA_NAMES.get(gps, '?')} ({gps})\n"
         f"  附加测高(ALT_ADD):    {_STA_NAMES.get(alt, '?')} ({alt})")
    return s, d


def _fmt_log(data: bytes) -> tuple[str, str]:
    if not data:
        return "(空)", "  (空帧)"
    color = data[0]
    try:
        text = data[1:].decode("gbk", errors="replace")
    except Exception:
        text = repr(data[1:])
    color_s = {0: "白", 1: "红", 2: "绿"}.get(color, str(color))
    short = text[:60].replace("\n", "↩")
    d = f"  颜色: {color_s} ({color})\n  文本: {text[:300]}"
    return short, d


def _fmt_gen_pos(data: bytes) -> tuple[str, str]:
    fmt = "<iii"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    x, y, z = struct.unpack(fmt, data)
    INV = -2147483648

    def v(n: int) -> str:
        return f"{n} cm" if n != INV else "— (无效)"

    s = f"X={v(x)}  Y={v(y)}  Z={v(z)}"
    d = f"  X: {v(x)}\n  Y: {v(y)}\n  Z: {v(z)}"
    return s, d


def _fmt_gen_vel(data: bytes) -> tuple[str, str]:
    fmt = "<hhh"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    vx, vy, vz = struct.unpack(fmt, data)
    INV = -32768

    def v(n: int) -> str:
        return f"{n} cm/s" if n != INV else "— (无效)"

    s = f"vx={v(vx)}  vy={v(vy)}  vz={v(vz)}"
    d = f"  Vx: {v(vx)}\n  Vy: {v(vy)}\n  Vz: {v(vz)}"
    return s, d


def _fmt_gen_dist(data: bytes) -> tuple[str, str]:
    fmt = "<BHI"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    direction, angle, dist = struct.unpack(fmt, data)
    dir_s = "垂直" if direction == 1 else "水平"
    dist_s = f"{dist} cm" if dist != 0xFFFFFFFF else "— (无效)"
    s = f"{dir_s}  {angle}°  {dist_s}"
    d = f"  方向: {dir_s} ({direction})\n  角度: {angle} °\n  距离: {dist_s}"
    return s, d


def _fmt_raw(data: bytes) -> tuple[str, str]:
    hex_s = data.hex(" ").upper() if data else "(空)"
    short = hex_s[:64] + ("…" if len(hex_s) > 64 else "")
    return short, f"  (无专属解析器)\n  DATA: {hex_s}"


def _fmt_imu(data: bytes) -> tuple[str, str]:
    fmt = "<hhhhhhB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    ax, ay, az, gx, gy, gz, shock = struct.unpack(fmt, data)
    # LSB → 物理量纲（日常分析单位）：加速度用 g，角速度用 °/s
    axg, ayg, azg = ax * _ACC_LSB_TO_G, ay * _ACC_LSB_TO_G, az * _ACC_LSB_TO_G
    gxd, gyd, gzd = gx * _GYR_LSB_TO_DPS, gy * _GYR_LSB_TO_DPS, gz * _GYR_LSB_TO_DPS
    s = (f"Ax={axg:+.2f} Ay={ayg:+.2f} Az={azg:+.2f} g   "
         f"Gx={gxd:+.1f} Gy={gyd:+.1f} Gz={gzd:+.1f} °/s")
    d = (f"  加速度 Ax: {axg:+.3f} g   ({ax * _ACC_LSB_TO_MS2:+.3f} m/s²)\n"
         f"  加速度 Ay: {ayg:+.3f} g   ({ay * _ACC_LSB_TO_MS2:+.3f} m/s²)\n"
         f"  加速度 Az: {azg:+.3f} g   ({az * _ACC_LSB_TO_MS2:+.3f} m/s²)\n"
         f"  角速度 Gx: {gxd:+.2f} °/s\n"
         f"  角速度 Gy: {gyd:+.2f} °/s\n"
         f"  角速度 Gz: {gzd:+.2f} °/s\n"
         f"  震动状态:  {shock}")
    return s, d


def _fmt_mag_baro(data: bytes) -> tuple[str, str]:
    fmt = "<hhhihBB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    mx, my, mz, alt_bar, tmp, bar_sta, mag_sta = struct.unpack(fmt, data)
    # 温度：协议文档标注 ×10(0.1℃)，但实测原始值 4880 按此算是 488℃（离谱）。
    # 实测按 ×100(0.01℃) → 48.8℃，与温热的 IMU 芯片相符，故采用 /100。
    # 气压高度 ALT_BAR：绝对气压高度（以海平面标准气压为基准），静止实测≈129m，
    # 等于本地海拔，并非离地相对高度（离地相对高度见 0x05 融合高度帧）。
    s = f"Mx={mx}  My={my}  Mz={mz}  气压海拔={alt_bar/100:.1f}m  温={tmp / 100:.1f}℃"
    d = (f"  罗盘 Mx:   {mx}\n"
         f"  罗盘 My:   {my}\n"
         f"  罗盘 Mz:   {mz}\n"
         f"  气压海拔:  {alt_bar} cm = {alt_bar/100:.2f} m (绝对/海平面基准)\n"
         f"  温度:      {tmp / 100:.1f} ℃ (×0.01)\n"
         f"  气压状态:  {bar_sta}\n"
         f"  罗盘状态:  {mag_sta}")
    return s, d


def _fmt_pos_offset(data: bytes) -> tuple[str, str]:
    fmt = "<ii"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    px, py = struct.unpack(fmt, data)
    s = f"X={px} cm  Y={py} cm"
    d = f"  X 偏移: {px} cm\n  Y 偏移: {py} cm"
    return s, d


def _fmt_wind(data: bytes) -> tuple[str, str]:
    fmt = "<hh"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    wx, wy = struct.unpack(fmt, data)
    s = f"Wx={wx} cm/s  Wy={wy} cm/s"
    d = f"  风速 X: {wx} cm/s\n  风速 Y: {wy} cm/s"
    return s, d


def _fmt_tar_att(data: bytes) -> tuple[str, str]:
    fmt = "<hhh"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    rol, pit, yaw = struct.unpack(fmt, data)
    s = f"目标 rol={rol / 100:.2f}°  pit={pit / 100:.2f}°  yaw={yaw / 100:.2f}°"
    d = (f"  目标横滚: {rol / 100:.2f} °\n"
         f"  目标俯仰: {pit / 100:.2f} °\n"
         f"  目标偏航: {yaw / 100:.2f} °")
    return s, d


def _fmt_tar_vel(data: bytes) -> tuple[str, str]:
    fmt = "<hhh"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    vx, vy, vz = struct.unpack(fmt, data)
    s = f"目标 Vx={vx}  Vy={vy}  Vz={vz}  cm/s"
    d = f"  目标速度 X: {vx} cm/s\n  目标速度 Y: {vy} cm/s\n  目标速度 Z: {vz} cm/s"
    return s, d


def _fmt_home(data: bytes) -> tuple[str, str]:
    fmt = "<hH"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    angle_x10, dist_m = struct.unpack(fmt, data)
    s = f"回航角={angle_x10 / 10:.1f}°  距离={dist_m} m"
    d = f"  回航角度: {angle_x10 / 10:.1f} °\n  回航距离: {dist_m} m"
    return s, d


def _fmt_rgb(data: bytes) -> tuple[str, str]:
    fmt = "<BBBB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    r, g, b, a = struct.unpack(fmt, data)
    s = f"R={r}  G={g}  B={b}  A={a}  (0-20级)"
    d = (f"  红 BRI_R:      {r}\n"
         f"  绿 BRI_G:      {g}\n"
         f"  蓝 BRI_B:      {b}\n"
         f"  单独LED BRI_A: {a}")
    return s, d


def _fmt_gps(data: bytes) -> tuple[str, str]:
    fmt = "<BBiiihhhBBB"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    fix, snum, lng7, lat7, alt, nspd, espd, dspd, pdop_u8, sacc_u8, vacc_u8 = struct.unpack(fmt, data)
    s = (f"FIX={fix}  卫星={snum}  "
         f"({lat7 / 1e7:.5f}°N, {lng7 / 1e7:.5f}°E)  "
         f"Alt={alt} cm")
    d = (f"  定位状态 FIX_STA: {fix}\n"
         f"  卫星数量 S_NUM:   {snum}\n"
         f"  经度 LNG:         {lng7 / 1e7:.7f} °\n"
         f"  纬度 LAT:         {lat7 / 1e7:.7f} °\n"
         f"  GPS高度:          {alt} cm\n"
         f"  北向速度 N_SPE:   {nspd} cm/s\n"
         f"  东向速度 E_SPE:   {espd} cm/s\n"
         f"  垂直速度 D_SPE:   {dspd} cm/s\n"
         f"  定位精度 PDOP:    {pdop_u8 * 0.01:.2f}\n"
         f"  速度精度 SACC:    {sacc_u8 * 0.01:.2f} mm\n"
         f"  高度精度 VACC:    {vacc_u8 * 0.01:.2f} mm")
    return s, d


def _fmt_rc(data: bytes) -> tuple[str, str]:
    fmt = "<HHHHHHHHHH"
    if len(data) < struct.calcsize(fmt):
        return _fmt_raw(data)
    ch = struct.unpack_from(fmt, data)
    s = "  ".join(f"CH{i + 1}={v}" for i, v in enumerate(ch))
    d = "\n".join(f"  CH{i + 1}: {v}" for i, v in enumerate(ch))
    return s, d


def _fmt_log_num(data: bytes) -> tuple[str, str]:
    if len(data) < 4:
        return _fmt_raw(data)
    (val,) = struct.unpack_from("<i", data)
    text = data[4:].decode("ascii", errors="replace").rstrip("\x00")
    s = f"val={val}  \"{text[:60]}\""
    d = f"  数值 VAL: {val}\n  字符串:   {text}"
    return s, d


def _fmt_cmd(data: bytes) -> tuple[str, str]:
    fmt = "<BBBBBBBBBBB"
    if len(data) < struct.calcsize(fmt):
        return _fmt_raw(data)
    fields = struct.unpack_from(fmt, data)
    cid = fields[0]
    cmds = fields[1:]
    s = f"CID=0x{cid:02X}  CMD=[{' '.join(f'{c:02X}' for c in cmds)}]"
    d = f"  CID:  0x{cid:02X}\n" + "\n".join(
        f"  CMD{i}: 0x{c:02X} ({c})" for i, c in enumerate(cmds)
    )
    return s, d


def _fmt_param_back(data: bytes) -> tuple[str, str]:
    fmt = "<Hi"
    if len(data) != struct.calcsize(fmt):
        return _fmt_raw(data)
    par_id, par_val = struct.unpack(fmt, data)
    s = f"ID=0x{par_id:04X}  Val={par_val}"
    d = f"  参数 ID:  0x{par_id:04X} ({par_id})\n  参数值:   {par_val}"
    return s, d


# ---------------------------------------------------------------------------
# 已知帧目录：(帧名, 格式化函数)；决定面板里行的初始顺序
# ---------------------------------------------------------------------------
_CATALOG: tuple[tuple[int, str, Callable], ...] = (
    (0x01, "IMU 加速度/角速度",      _fmt_imu),
    (0x02, "磁力计/气压/温度",       _fmt_mag_baro),
    (0x03, "欧拉姿态",               _fmt_euler),
    (0x04, "四元数姿态",             _fmt_quat),
    (0x05, "高度",                   _fmt_height),
    (0x06, "飞控模式",               _fmt_flight_mode),
    (0x07, "速度",                   _fmt_velocity),
    (0x08, "位置偏移 XY",            _fmt_pos_offset),
    (0x09, "风速估计",               _fmt_wind),
    (0x0A, "目标姿态",               _fmt_tar_att),
    (0x0B, "目标速度",               _fmt_tar_vel),
    (0x0C, "回航信息",               _fmt_home),
    (0x0D, "电压电流",               _fmt_battery),
    (0x0E, "外接模块状态",           _fmt_module_status),
    (0x0F, "RGB 亮度",               _fmt_rgb),
    (0x30, "GPS 数据",               _fmt_gps),
    (0x32, "通用位置",               _fmt_gen_pos),
    (0x33, "通用速度(光流)",         _fmt_gen_vel),
    (0x34, "通用测距(激光)",         _fmt_gen_dist),
    (0x40, "遥控器通道",             _fmt_rc),
    (0x41, "实时控制",               _fmt_raw),
    (0xA0, "日志文本",               _fmt_log),
    (0xA1, "日志文本+数字",          _fmt_log_num),
    (0xE0, "CMD 命令",               _fmt_cmd),
    (0xE2, "参数返回",               _fmt_param_back),
)


# ---------------------------------------------------------------------------
# _FrameRow：单帧行 widget
# ---------------------------------------------------------------------------

class _FrameRow(QWidget):
    """一行：折叠头部（活动灯 + CMD + 名称 + 摘要 + Hz）+ 可展开详情区。

    性能要点：帧到达时只 :meth:`note_frame` 缓存最新帧（O(1)，不碰 UI）；
    真正的 setText / 样式更新由父窗口的共享定时器以固定频率调用 :meth:`render`，
    使 UI 刷新率与数据速率（可达 100+Hz）彻底解耦。
    """

    def __init__(
        self,
        cmd: int,
        name: str,
        fmt_fn: Callable,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._name = name
        self._fmt_fn = fmt_fn
        self._expanded = False

        # 数据缓存（不在信号槽里碰 UI）
        self._pending_fr: Optional[Frame] = None   # 待渲染的最新帧
        self._last_fr: Optional[Frame] = None       # 最近一帧（展开时回填详情用）

        # Hz 统计：滑动 1s 窗口内的计数
        self._rx_count = 0
        self._hz_win_start = time.monotonic()

        # 活动灯 / 摘要样式状态（只在翻转时 setStyleSheet）
        self._dot_state = 0          # 0=暗灰 1=亮绿
        self._fresh_until = 0.0
        self._summary_active = False

        self._build_ui()

    # ---- 构建 UI ----

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 2)
        root.setSpacing(0)

        # --- 头部（可点击，点击展开/折叠）---
        self._header = QFrame(self)
        self._header.setFrameShape(QFrame.Shape.StyledPanel)
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.mousePressEvent = lambda _e: self._toggle()

        h_lay = QHBoxLayout(self._header)
        h_lay.setContentsMargins(6, 3, 6, 3)
        h_lay.setSpacing(6)

        self._toggle_lbl = QLabel("▶", self._header)
        self._toggle_lbl.setFixedWidth(14)
        self._toggle_lbl.setStyleSheet("color: #888;")

        # 活动指示灯（替代整块背景闪烁，避免每帧 repolish）
        self._dot = QLabel("●", self._header)
        self._dot.setFixedWidth(14)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot.setStyleSheet(_DOT_IDLE_QSS)

        self._cmd_lbl = QLabel(f"0x{self._cmd:02X}", self._header)
        self._cmd_lbl.setFixedWidth(38)
        self._cmd_lbl.setStyleSheet(
            "font-family: Consolas,'Courier New',monospace; font-weight: bold;"
        )

        self._name_lbl = QLabel(self._name, self._header)
        self._name_lbl.setFixedWidth(130)

        self._summary_lbl = QLabel("— 等待数据 —", self._header)
        self._summary_lbl.setStyleSheet(_SUMMARY_IDLE_QSS)

        self._hz_lbl = QLabel("", self._header)
        self._hz_lbl.setFixedWidth(56)
        self._hz_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._hz_lbl.setStyleSheet("color: #555; font-size: 11px;")

        h_lay.addWidget(self._toggle_lbl)
        h_lay.addWidget(self._dot)
        h_lay.addWidget(self._cmd_lbl)
        h_lay.addWidget(self._name_lbl)
        h_lay.addWidget(self._summary_lbl, 1)
        h_lay.addWidget(self._hz_lbl)
        root.addWidget(self._header)

        # --- 详情区（折叠时隐藏）---
        self._detail = QFrame(self)
        self._detail.setFrameShape(QFrame.Shape.NoFrame)
        self._detail.setVisible(False)

        d_lay = QVBoxLayout(self._detail)
        d_lay.setContentsMargins(62, 2, 6, 4)
        d_lay.setSpacing(0)

        self._detail_lbl = QLabel("", self._detail)
        self._detail_lbl.setStyleSheet(
            "font-family: Consolas,'Courier New',monospace; font-size: 13px; color: #d0d0d0;"
        )
        self._detail_lbl.setWordWrap(True)
        self._detail_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self._raw_lbl = QLabel("", self._detail)
        self._raw_lbl.setStyleSheet(
            "font-family: Consolas,'Courier New',monospace; font-size: 12px; color: #777;"
        )
        self._raw_lbl.setWordWrap(True)
        self._raw_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        d_lay.addWidget(self._detail_lbl)
        d_lay.addWidget(self._raw_lbl)
        root.addWidget(self._detail)

    # ---- 交互逻辑 ----

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self._detail.setVisible(self._expanded)
        self._toggle_lbl.setText("▼" if self._expanded else "▶")
        # 展开瞬间用最近一帧立即回填详情（平时折叠不构建详情字符串，省算力）
        if self._expanded and self._last_fr is not None:
            self._fill_detail(self._last_fr)

    def _fill_detail(self, fr: Frame) -> None:
        try:
            _, detail_text = self._fmt_fn(fr.data)
        except Exception as exc:
            detail_text = f"  Exception: {exc}"
        self._detail_lbl.setText(detail_text)
        raw_hex = fr.raw.hex(" ").upper() if fr.raw else fr.data.hex(" ").upper()
        self._raw_lbl.setText(f"  完整帧: {raw_hex}")

    # ---- 数据入口（信号槽里调用，必须极轻）----

    def note_frame(self, fr: Frame) -> None:
        """缓存最新帧 + 计数；不做任何 UI 操作。"""
        self._pending_fr = fr
        self._rx_count += 1

    # ---- 渲染（父窗口共享定时器以 ~15Hz 调用）----

    def render(self, now: float) -> None:
        fr = self._pending_fr
        if fr is not None:
            self._pending_fr = None
            self._last_fr = fr
            try:
                summary, _detail = self._fmt_fn(fr.data)
            except Exception as exc:
                summary = f"解析错误: {exc}"
            self._summary_lbl.setText(summary)
            if not self._summary_active:
                self._summary_lbl.setStyleSheet(_SUMMARY_LIVE_QSS)
                self._summary_active = True
            # 只有展开的行才构建/更新详情，避免折叠行浪费算力
            if self._expanded:
                self._fill_detail(fr)
            self._fresh_until = now + _DOT_FRESH_SEC
            if self._dot_state != 1:
                self._dot.setStyleSheet(_DOT_LIVE_QSS)
                self._dot_state = 1
        else:
            # 无新帧：绿灯到期后熄灭（只在翻转时改样式）
            if self._dot_state == 1 and now >= self._fresh_until:
                self._dot.setStyleSheet(_DOT_IDLE_QSS)
                self._dot_state = 0

        # Hz：每满 1s 采样一次
        elapsed = now - self._hz_win_start
        if elapsed >= 1.0:
            hz = self._rx_count / elapsed
            self._hz_lbl.setText(f"@ {hz:.0f} Hz" if self._rx_count > 0 else "")
            self._rx_count = 0
            self._hz_win_start = now


# ---------------------------------------------------------------------------
# FrameMonitorWidget：主控件（整屏中央视图）
# ---------------------------------------------------------------------------

class FrameMonitorWidget(QWidget):
    """数据帧监视窗口（整屏中央视图）。

    性能设计（惰性 + 定频）：
    - 仅当本窗口 **可见** 时才处理入站帧（``showEvent``/``hideEvent`` 控制
      ``_active``）；隐藏时 ``on_frame`` 立即返回，不占任何算力。
    - 帧到达只把最新帧缓存到对应行（O(1)）；一个 **共享定时器** 以 ~15Hz
      统一刷新所有行，UI 刷新与数据速率（100+Hz）解耦，杜绝逐帧 setText。
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rows: dict[int, _FrameRow] = {}
        self._active = False

        # 内容：可滚动的行列表
        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(4, 4, 4, 4)
        self._list_layout.setSpacing(2)

        # 按 catalog 顺序预建所有已知帧行
        for cmd, name, fmt_fn in _CATALOG:
            row = _FrameRow(cmd, name, fmt_fn, self._container)
            self._rows[cmd] = row
            self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)  # 行顶对齐

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._container)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        root_lay.addWidget(scroll, 1)

        # 共享刷新定时器：仅在窗口可见时运行
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(_UI_REFRESH_MS)
        self._refresh_timer.timeout.connect(self._on_refresh)

    # ---- 可见性驱动的惰性启停 ----

    def showEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().showEvent(event)
        self._active = True
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        super().hideEvent(event)
        self._active = False
        self._refresh_timer.stop()

    # ---- 数据入口（信号槽，必须极轻）----

    @Slot(object)
    def on_frame(self, fr: Frame) -> None:
        """接收 frame_received；窗口隐藏时直接丢弃（不计算）。"""
        if not self._active:
            return
        cmd = fr.cmd
        row = self._rows.get(cmd)
        if row is None:
            # 动态追加未知帧（插在 stretch 之前）
            name = f"未知 0x{cmd:02X}"
            row = _FrameRow(cmd, name, _fmt_raw, self._container)
            self._rows[cmd] = row
            idx = self._list_layout.count() - 1  # stretch 的 index
            self._list_layout.insertWidget(idx, row)
        row.note_frame(fr)

    # ---- 共享定时刷新 ----

    def _on_refresh(self) -> None:
        now = time.monotonic()
        for row in self._rows.values():
            row.render(now)


# 向后兼容别名（main.py 的旧导入仍可用）
FrameMonitorDock = FrameMonitorWidget
