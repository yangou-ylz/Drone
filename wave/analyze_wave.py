# -*- coding: utf-8 -*-
"""
凌霄飞控波形自动分析框架（多方法库版）
================================================
输入: 本目录下所有 *.csv (匿名上位机导出 / 本工程 logger 导出)
输出: out/<文件名>/...
              basic/     总览/姿态/IMU/高度
              fft/       PSD 频谱 + 主峰表
              spectrogram/  时频图(看振动随时间变化)
              distribution/ 分布直方图
              pid/       阶跃响应/跟踪误差(自动检测)
              coupling/  轴间互相关
              anomaly/   异常事件清单
            summary.txt      文字报告
            metrics.json     机器可读指标(便于回归对比)
        out/_compare_summary.csv     多文件指标汇总
        out/_compare_overview.png    多文件横向对比柱状图

设计目标:
- 模块化方法库, 每个分析器独立可关闭, 易于追加新方法
- 全自动: 任务窗自动检测、阶跃自动检测、噪声主峰自动识别
- 输出供 PID 调参 / 振动诊断 / 异常发现 / 横向回归

可扩展接口: 在底部 ANALYZERS 列表添加 (name, func) 即可加入新方法。

使用:
    cd wave
    python analyze_wave.py
"""

from __future__ import annotations

import os
import json
import glob
import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# 中文字体
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False

try:
    from scipy import signal as scisig
    HAVE_SCIPY = True
except Exception:
    HAVE_SCIPY = False


# ============================================================
# 全局配置
# ============================================================
SAMPLE_RATE_HZ = 200.0  # 匿名上位机默认 200Hz, 不一致请改

# 启用开关(关掉某项即可跳过该分析)
ENABLE_BASIC = True
ENABLE_FFT = True
ENABLE_SPECTROGRAM = True
ENABLE_DISTRIBUTION = True
ENABLE_PID_RESPONSE = True
ENABLE_COUPLING = True
ENABLE_DRIFT = True
ENABLE_ANOMALY = True
ENABLE_VIBRATION_SCORE = True

# 关键通道
USE_COLS = [
    "FC_ACC_X", "FC_ACC_Y", "FC_ACC_Z",
    "FC_GYR_X", "FC_GYR_Y", "FC_GYR_Z",
    "FC_MAG_X", "FC_MAG_Y", "FC_MAG_Z",
    "FC_ALT_BAR", "FC_ALT_FU",
    "FC_ATT_ROL", "FC_ATT_PIT", "FC_ATT_YAW",
    "FC_Votage", "FC_SenserTMP",
    "FC_CTRLOUT_PWM1", "FC_CTRLOUT_PWM2",
    "FC_CTRLOUT_PWM3", "FC_CTRLOUT_PWM4",
]

ACC_CHANNELS = ["FC_ACC_X", "FC_ACC_Y", "FC_ACC_Z"]
GYR_CHANNELS = ["FC_GYR_X", "FC_GYR_Y", "FC_GYR_Z"]
ATT_CHANNELS = ["FC_ATT_ROL", "FC_ATT_PIT", "FC_ATT_YAW"]
PWM_CHANNELS = ["FC_CTRLOUT_PWM1", "FC_CTRLOUT_PWM2",
                "FC_CTRLOUT_PWM3", "FC_CTRLOUT_PWM4"]

# 阈值
TH_ATT_DEG = 15.0
TH_GYR_PEAK = 200.0
TH_ACC_PEAK = 4096
TH_ALT_DRIFT_CM = 30.0
TH_VBAT_MIN = 9.5
TH_TMP_MAX = 70.0
TH_VIB_RMS = 200          # ACC 振动 RMS 告警
TH_NOTCH_PEAK_RATIO = 6.0  # 主峰能量 / 中位数 比值告警

# 任务窗检测
ACTIVE_ACC_TH = 80
ACTIVE_MIN_LEN_S = 1.0
PRE_ROLL_S = 1.0
POST_ROLL_S = 1.5

OUT_DIR_NAME = "out"


# ============================================================
# 数据加载与筛选
# ============================================================
def load_csv(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, header=1, skip_blank_lines=True)
    df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed")]
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(how="all").reset_index(drop=True)
    df["t_s"] = np.arange(len(df)) / SAMPLE_RATE_HZ
    return df


def filter_columns(df: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in USE_COLS if c in df.columns]
    out = df[["t_s"] + cols].copy()
    drop = [c for c in cols
            if out[c].abs().max() == 0 or out[c].nunique() <= 1]
    if drop:
        out = out.drop(columns=drop)
    return out


# ============================================================
# 任务窗 / 静态窗自动检测
# ============================================================
def detect_active_window(df: pd.DataFrame) -> tuple[float, float]:
    cands = [c for c in ("FC_ACC_X", "FC_ACC_Y") if c in df.columns]
    if not cands:
        return float(df["t_s"].iloc[0]), float(df["t_s"].iloc[-1])
    sig = np.zeros(len(df))
    for c in cands:
        s = df[c].to_numpy(float)
        n_warm = int(min(len(s), SAMPLE_RATE_HZ * 2))
        base = np.median(s[:n_warm])
        sig = np.maximum(sig, np.abs(s - base))
    active = sig > ACTIVE_ACC_TH
    if not active.any():
        return float(df["t_s"].iloc[0]), float(df["t_s"].iloc[-1])
    idx = np.where(active)[0]
    i0 = max(0, idx[0] - int(PRE_ROLL_S * SAMPLE_RATE_HZ))
    i1 = min(len(df) - 1, idx[-1] + int(POST_ROLL_S * SAMPLE_RATE_HZ))
    t0, t1 = float(df["t_s"].iloc[i0]), float(df["t_s"].iloc[i1])
    if (t1 - t0) < ACTIVE_MIN_LEN_S:
        return float(df["t_s"].iloc[0]), float(df["t_s"].iloc[-1])
    return t0, t1


def detect_static_window(df: pd.DataFrame, active: tuple[float, float]) -> tuple[float, float] | None:
    """活动段之前的静止段, 用于陀螺零偏估计与振动基线。"""
    t0 = float(df["t_s"].iloc[0])
    if active[0] - t0 < 0.5:
        return None
    return (t0, max(t0, active[0] - 0.3))


# ============================================================
# 数据结构
# ============================================================
@dataclass
class ChannelStat:
    name: str
    mean: float
    std: float
    vmin: float
    vmax: float
    peak_abs: float
    rms: float


@dataclass
class Report:
    file: str
    n_rows: int
    duration_s: float
    active_t0: float
    active_t1: float
    static_t0: float | None = None
    static_t1: float | None = None
    stats: dict = field(default_factory=dict)         # ChannelStat
    warnings: list = field(default_factory=list)
    tips: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)       # 数字指标
    fft_peaks: dict = field(default_factory=dict)     # 主峰列表
    pid_response: dict = field(default_factory=dict)  # rise/overshoot/...
    coupling: dict = field(default_factory=dict)
    drift: dict = field(default_factory=dict)
    anomaly_events: list = field(default_factory=list)


def _stat(name, s: pd.Series) -> ChannelStat:
    s = s.dropna().to_numpy(float)
    if len(s) == 0:
        return ChannelStat(name, 0, 0, 0, 0, 0, 0)
    return ChannelStat(
        name=name,
        mean=float(np.mean(s)),
        std=float(np.std(s)),
        vmin=float(np.min(s)),
        vmax=float(np.max(s)),
        peak_abs=float(np.max(np.abs(s))),
        rms=float(np.sqrt(np.mean(s * s))),
    )


def _annotate_active(ax, rep: Report):
    ax.axvspan(rep.active_t0, rep.active_t1, color="orange", alpha=0.08)


# ============================================================
# 分析器: 基础统计与总览图
# ============================================================
def analyzer_basic(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_BASIC:
        return
    sub = os.path.join(outdir, "basic")
    os.makedirs(sub, exist_ok=True)
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)]

    for c in df.columns:
        if c == "t_s":
            continue
        rep.stats[c] = _stat(c, win[c])

    # 异常 / 阈值
    for c in ("FC_ATT_ROL", "FC_ATT_PIT"):
        if c in rep.stats and rep.stats[c].peak_abs > TH_ATT_DEG:
            rep.warnings.append(f"{c} 峰值 {rep.stats[c].peak_abs:.1f}° > {TH_ATT_DEG}°")
    for c in GYR_CHANNELS:
        if c in rep.stats and rep.stats[c].peak_abs > TH_GYR_PEAK:
            rep.warnings.append(f"{c} 峰值 {rep.stats[c].peak_abs:.0f} > {TH_GYR_PEAK}")
    for c in ACC_CHANNELS:
        if c in rep.stats and rep.stats[c].peak_abs > TH_ACC_PEAK:
            rep.warnings.append(f"{c} 峰值 {rep.stats[c].peak_abs:.0f} > {TH_ACC_PEAK}")
    if "FC_ALT_FU" in rep.stats:
        drift = rep.stats["FC_ALT_FU"].vmax - rep.stats["FC_ALT_FU"].vmin
        rep.metrics["alt_drift_cm"] = drift
        if drift > TH_ALT_DRIFT_CM:
            rep.warnings.append(f"FC_ALT_FU 漂移 {drift:.1f}cm > {TH_ALT_DRIFT_CM}cm")
    if "FC_Votage" in rep.stats:
        v = rep.stats["FC_Votage"].vmin
        if v > 0 and v < TH_VBAT_MIN:
            rep.warnings.append(f"电压 {v:.2f}V < {TH_VBAT_MIN}V")
    if "FC_SenserTMP" in rep.stats:
        t = rep.stats["FC_SenserTMP"].vmax
        if t > TH_TMP_MAX:
            rep.warnings.append(f"温度 {t:.1f}℃ > {TH_TMP_MAX}℃")

    # 关键 metric
    for c in ATT_CHANNELS:
        if c in rep.stats:
            rep.metrics[f"{c}_peak"] = rep.stats[c].peak_abs
            rep.metrics[f"{c}_std"] = rep.stats[c].std
    for c in ACC_CHANNELS + GYR_CHANNELS:
        if c in rep.stats:
            rep.metrics[f"{c}_std"] = rep.stats[c].std
            rep.metrics[f"{c}_rms"] = rep.stats[c].rms
    rep.metrics["active_dur_s"] = rep.active_t1 - rep.active_t0

    # 总览图
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)
    t = df["t_s"]
    ax = axes[0]
    for c in ATT_CHANNELS:
        if c in df.columns:
            ax.plot(t, df[c], lw=1.0, label=c)
    ax.set_ylabel("Attitude (deg)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    _annotate_active(ax, rep)

    ax = axes[1]
    for c in ACC_CHANNELS:
        if c in df.columns:
            ax.plot(t, df[c], lw=0.8, label=c)
    ax.set_ylabel("ACC"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    _annotate_active(ax, rep)

    ax = axes[2]
    for c in ("FC_ALT_FU", "FC_ALT_BAR"):
        if c in df.columns:
            ax.plot(t, df[c], lw=1.0, label=c)
    ax.set_ylabel("Alt"); ax.set_xlabel("t(s)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
    _annotate_active(ax, rep)

    fig.suptitle(f"Overview - {os.path.basename(rep.file)}")
    fig.tight_layout()
    fig.savefig(os.path.join(sub, "overview.png"), dpi=130)
    plt.close(fig)

    # 姿态/IMU/高度 单图
    _save_lines(df, ATT_CHANNELS, "Attitude (deg)", os.path.join(sub, "attitude.png"), rep)
    _save_lines(df, ACC_CHANNELS + GYR_CHANNELS, "IMU", os.path.join(sub, "imu.png"), rep)
    _save_lines(df, ["FC_ALT_FU", "FC_ALT_BAR"], "Altitude", os.path.join(sub, "altitude.png"), rep)


def _save_lines(df, cols, ylabel, path, rep):
    cols = [c for c in cols if c in df.columns]
    if not cols:
        return
    fig, ax = plt.subplots(figsize=(12, 4))
    for c in cols:
        ax.plot(df["t_s"], df[c], lw=0.9, label=c)
    ax.set_xlabel("t(s)"); ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)
    _annotate_active(ax, rep)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


# ============================================================
# 分析器: FFT / PSD 频谱
# ============================================================
def analyzer_fft(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_FFT or not HAVE_SCIPY:
        return
    sub = os.path.join(outdir, "fft")
    os.makedirs(sub, exist_ok=True)

    win_mask = (df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)
    win = df[win_mask].reset_index(drop=True)
    if len(win) < 256:
        return

    def _psd(channels, title, fname):
        fig, ax = plt.subplots(figsize=(11, 4.5))
        peaks_for_ch = {}
        for c in channels:
            if c not in win.columns:
                continue
            x = win[c].to_numpy(float)
            x = x - np.mean(x)
            nperseg = min(1024, len(x))
            f, Pxx = scisig.welch(x, fs=SAMPLE_RATE_HZ, nperseg=nperseg)
            ax.semilogy(f, Pxx + 1e-12, lw=1.0, label=c)
            # 主峰 top3
            mask = f > 1.0
            ff, pp = f[mask], Pxx[mask]
            if len(pp) > 5:
                idx = np.argsort(pp)[-3:][::-1]
                peaks_for_ch[c] = [(float(ff[i]), float(pp[i])) for i in idx]
                med = float(np.median(pp))
                ratio = float(pp[idx[0]] / max(med, 1e-12))
                if ratio > TH_NOTCH_PEAK_RATIO:
                    rep.warnings.append(
                        f"{c} 频谱主峰 {ff[idx[0]]:.1f}Hz 能量/中位 {ratio:.1f}x, 建议 notch")
        ax.set_xlabel("Hz"); ax.set_ylabel("PSD")
        ax.set_title(f"PSD - {title}")
        ax.grid(alpha=0.3, which="both"); ax.legend(fontsize=8)
        fig.tight_layout(); fig.savefig(os.path.join(sub, fname), dpi=130)
        plt.close(fig)
        return peaks_for_ch

    rep.fft_peaks["acc"] = _psd(ACC_CHANNELS, "Accelerometer", "psd_acc.png")
    rep.fft_peaks["gyr"] = _psd(GYR_CHANNELS, "Gyroscope", "psd_gyr.png")

    # 主峰列表写文本
    with open(os.path.join(sub, "peaks.txt"), "w", encoding="utf-8") as f:
        for grp, d in rep.fft_peaks.items():
            f.write(f"=== {grp} ===\n")
            for c, peaks in d.items():
                f.write(f"  {c}:\n")
                for fr, p in peaks:
                    f.write(f"    {fr:7.2f} Hz   PSD={p:.3e}\n")


# ============================================================
# 分析器: 时频图 (Spectrogram)
# ============================================================
def analyzer_spectrogram(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_SPECTROGRAM or not HAVE_SCIPY:
        return
    sub = os.path.join(outdir, "spectrogram")
    os.makedirs(sub, exist_ok=True)

    targets = [c for c in ("FC_ACC_Z", "FC_GYR_Z", "FC_ACC_X", "FC_GYR_Y")
               if c in df.columns]
    for c in targets:
        x = df[c].to_numpy(float)
        x = x - np.mean(x)
        if len(x) < 256:
            continue
        nperseg = min(512, len(x) // 4)
        if nperseg < 64:
            continue
        f, t, Sxx = scisig.spectrogram(x, fs=SAMPLE_RATE_HZ, nperseg=nperseg,
                                       noverlap=nperseg // 2)
        fig, ax = plt.subplots(figsize=(11, 4))
        Sdb = 10 * np.log10(Sxx + 1e-12)
        im = ax.pcolormesh(t, f, Sdb, shading="auto", cmap="viridis")
        ax.axvline(rep.active_t0, color="w", lw=0.8, alpha=0.6)
        ax.axvline(rep.active_t1, color="w", lw=0.8, alpha=0.6)
        ax.set_ylabel("Hz"); ax.set_xlabel("t(s)")
        ax.set_title(f"Spectrogram - {c}")
        plt.colorbar(im, ax=ax, label="dB")
        fig.tight_layout()
        fig.savefig(os.path.join(sub, f"spec_{c}.png"), dpi=130)
        plt.close(fig)


# ============================================================
# 分析器: 分布直方图
# ============================================================
def analyzer_distribution(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_DISTRIBUTION:
        return
    sub = os.path.join(outdir, "distribution")
    os.makedirs(sub, exist_ok=True)
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)]
    targets = ATT_CHANNELS + ACC_CHANNELS + GYR_CHANNELS
    for c in targets:
        if c not in win.columns:
            continue
        x = win[c].dropna().to_numpy(float)
        if len(x) < 30:
            continue
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.hist(x, bins=60, alpha=0.85, color="tab:blue")
        m, sd = np.mean(x), np.std(x)
        ax.axvline(m, color="r", lw=1.0, label=f"mean={m:.2f}")
        ax.axvline(m + 3 * sd, color="orange", lw=0.8, ls="--",
                   label=f"3σ={3*sd:.2f}")
        ax.axvline(m - 3 * sd, color="orange", lw=0.8, ls="--")
        ax.set_title(f"{c} 分布 (N={len(x)})"); ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(sub, f"hist_{c}.png"), dpi=130)
        plt.close(fig)


# ============================================================
# 分析器: PID 阶跃响应自动检测
# ============================================================
def analyzer_pid_response(df: pd.DataFrame, rep: Report, outdir: str):
    """
    自动找姿态/高度信号在活动窗内的最大阶跃, 估算:
        rise_time   10%->90%
        peak_time
        overshoot_pct  超调 (%)
        settling_time  ±5%
        ss_error       稳态残差
    无目标值则用阶跃后稳态的均值作为 setpoint 近似。
    """
    if not ENABLE_PID_RESPONSE:
        return
    sub = os.path.join(outdir, "pid")
    os.makedirs(sub, exist_ok=True)
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)].reset_index(drop=True)
    if len(win) < int(SAMPLE_RATE_HZ * 1.5):
        return

    candidates = [c for c in ATT_CHANNELS + ["FC_ALT_FU"] if c in win.columns]
    for c in candidates:
        x = win[c].to_numpy(float)
        t = win["t_s"].to_numpy(float)

        # 找最大阶跃: 一阶差分滑动均值最大处
        kw = max(5, int(SAMPLE_RATE_HZ * 0.1))
        if len(x) < kw * 4:
            continue
        dx = np.convolve(np.diff(x), np.ones(kw) / kw, mode="same")
        if not np.any(np.abs(dx) > 1e-6):
            continue
        i_step = int(np.argmax(np.abs(dx))) + 1
        if i_step < kw or i_step > len(x) - kw * 2:
            continue

        # 阶跃幅值 (设定: 阶跃后 0.5s 平稳段平均 - 阶跃前 0.3s 平均)
        pre = x[max(0, i_step - int(SAMPLE_RATE_HZ * 0.3)): i_step]
        post = x[min(len(x) - 1, i_step + int(SAMPLE_RATE_HZ * 1.0)):]
        if len(pre) == 0 or len(post) < 5:
            continue
        y0 = float(np.mean(pre))
        ss = float(np.mean(post))
        amp = ss - y0
        if abs(amp) < 1e-3:
            continue

        # 归一化响应
        norm = (x - y0) / amp  # 到 1.0 为目标
        seg = norm[i_step:]
        seg_t = t[i_step:] - t[i_step]

        # 上升时间 10% -> 90%
        try:
            i10 = int(np.where(seg >= 0.1)[0][0])
            i90 = int(np.where(seg >= 0.9)[0][0])
            rise = float(seg_t[i90] - seg_t[i10])
        except Exception:
            rise = float("nan")

        # 峰值与超调
        i_peak = int(np.argmax(np.abs(seg - 1.0) + (seg > 1.0) * 1e6))
        # 上面式子只在 seg>1 的时候奖励超调位置, 避免下冲被当作峰
        if np.any(seg > 1.0):
            i_peak = int(np.argmax(seg))
            overshoot = float((seg[i_peak] - 1.0) * 100.0)
            t_peak = float(seg_t[i_peak])
        else:
            overshoot = 0.0
            t_peak = float("nan")

        # 稳态时间 ±5%
        tol = 0.05
        in_band = np.abs(seg - 1.0) <= tol
        # 找最后一次出带的位置, 再之后就稳态
        if np.any(~in_band):
            last_out = int(np.where(~in_band)[0][-1])
            if last_out < len(seg) - 1:
                settle = float(seg_t[last_out + 1])
            else:
                settle = float("nan")
        else:
            settle = 0.0

        ss_err = float((1.0 - np.mean(seg[-int(SAMPLE_RATE_HZ * 0.3):])) * amp)

        rep.pid_response[c] = dict(
            step_amp=amp, rise_s=rise, peak_t_s=t_peak,
            overshoot_pct=overshoot, settle_s=settle, ss_err=ss_err,
        )

        # 调参建议
        if not math.isnan(overshoot) and overshoot > 25:
            rep.tips.append(f"{c} 超调 {overshoot:.1f}% 偏大, 建议减小 Kp 或增大 Kd")
        if not math.isnan(rise) and rise > 1.0:
            rep.tips.append(f"{c} 上升 {rise:.2f}s 偏慢, 可适当增大 Kp")
        if not math.isnan(settle) and settle > 3.0:
            rep.tips.append(f"{c} 稳态时间 {settle:.2f}s 偏长, 建议增大 Ki 或 Kd")

        # 绘图
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(t, x, lw=1.0, label=c)
        ax.axhline(ss, color="g", ls="--", lw=0.8, label=f"setpoint≈{ss:.2f}")
        ax.axhline(y0, color="gray", ls=":", lw=0.8, label=f"start={y0:.2f}")
        ax.axvline(t[i_step], color="r", lw=0.8, alpha=0.6, label="step")
        ax.set_title(
            f"{c} step | amp={amp:.2f}  rise={rise:.2f}s  "
            f"OS={overshoot:.1f}%  settle={settle:.2f}s  ssErr={ss_err:.2f}"
        )
        ax.set_xlabel("t(s)"); ax.grid(alpha=0.3); ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(sub, f"step_{c}.png"), dpi=130)
        plt.close(fig)


# ============================================================
# 分析器: 轴间互相关 (耦合检测)
# ============================================================
def analyzer_coupling(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_COUPLING:
        return
    sub = os.path.join(outdir, "coupling")
    os.makedirs(sub, exist_ok=True)
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)]
    pairs = [
        ("FC_ATT_ROL", "FC_ATT_PIT"),
        ("FC_GYR_X", "FC_GYR_Y"),
        ("FC_ACC_X", "FC_ACC_Y"),
    ]
    matrix = []
    labels = []
    for a, b in pairs:
        if a in win.columns and b in win.columns:
            x = win[a].to_numpy(float); y = win[b].to_numpy(float)
            x = x - np.mean(x); y = y - np.mean(y)
            denom = (np.std(x) * np.std(y))
            if denom < 1e-9:
                r = 0.0
            else:
                r = float(np.mean(x * y) / denom)
            rep.coupling[f"{a}~{b}"] = r
            matrix.append(r); labels.append(f"{a[3:]}~{b[3:]}")
            if abs(r) > 0.7:
                rep.warnings.append(f"轴耦合 {a}~{b} r={r:.2f}, 检查机架/控制混合")
    if matrix:
        fig, ax = plt.subplots(figsize=(7, 3.5))
        ax.bar(labels, matrix, color=["tab:blue", "tab:orange", "tab:green"][: len(matrix)])
        ax.axhline(0.7, ls="--", color="r", lw=0.8)
        ax.axhline(-0.7, ls="--", color="r", lw=0.8)
        ax.set_ylabel("Pearson r"); ax.set_ylim(-1.05, 1.05)
        ax.grid(alpha=0.3, axis="y"); ax.set_title("轴间耦合")
        fig.tight_layout()
        fig.savefig(os.path.join(sub, "pearson.png"), dpi=130)
        plt.close(fig)


# ============================================================
# 分析器: 漂移 / 陀螺零偏
# ============================================================
def analyzer_drift(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_DRIFT:
        return
    if rep.static_t0 is None:
        return
    sub = os.path.join(outdir, "drift")
    os.makedirs(sub, exist_ok=True)
    s = df[(df["t_s"] >= rep.static_t0) & (df["t_s"] <= rep.static_t1)]
    if len(s) < 10:
        return
    for c in GYR_CHANNELS:
        if c in s.columns:
            bias = float(np.mean(s[c]))
            noise = float(np.std(s[c]))
            rep.drift[c] = dict(bias=bias, noise_std=noise)
            if abs(bias) > 5:
                rep.warnings.append(f"{c} 静态零偏 {bias:.1f} 偏大")
    if "FC_ALT_FU" in s.columns and len(s) > int(SAMPLE_RATE_HZ * 1.0):
        x = s["FC_ALT_FU"].to_numpy(float)
        t = s["t_s"].to_numpy(float)
        slope = float(np.polyfit(t, x, 1)[0])
        rep.drift["alt_static_drift_per_s"] = slope
        if abs(slope) > 5:
            rep.warnings.append(f"静态高度漂移 {slope:.1f}cm/s")


# ============================================================
# 分析器: 异常事件检测 (跳变/卡顿/3σ离群)
# ============================================================
def analyzer_anomaly(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_ANOMALY:
        return
    sub = os.path.join(outdir, "anomaly")
    os.makedirs(sub, exist_ok=True)
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)].reset_index(drop=True)
    events = []

    for c in ATT_CHANNELS + ACC_CHANNELS + GYR_CHANNELS:
        if c not in win.columns:
            continue
        x = win[c].to_numpy(float)
        if len(x) < 10:
            continue
        # 1) 突变(jerk): 单点差分超过 6σ
        d = np.diff(x)
        sd = float(np.std(d) + 1e-9)
        idx = np.where(np.abs(d) > 6 * sd)[0]
        for i in idx[:20]:
            events.append((float(win["t_s"].iloc[i + 1]), c, "jump",
                           float(d[i]), f"{d[i]:+.2f}"))
        # 2) 平台(连续 N 点完全不变, 可能是数据卡死)
        n_const = 0
        max_const = 0
        for i in range(1, len(x)):
            if x[i] == x[i - 1]:
                n_const += 1
                max_const = max(max_const, n_const)
            else:
                n_const = 0
        if max_const > SAMPLE_RATE_HZ * 0.3:
            rep.warnings.append(f"{c} 出现 {max_const} 点连续不变, 可能卡死")
        # 3) 3σ 离群计数
        m, s = float(np.mean(x)), float(np.std(x))
        if s > 1e-9:
            n_out = int(np.sum(np.abs(x - m) > 3 * s))
            rep.metrics[f"{c}_outlier_3s_pct"] = float(n_out) / len(x) * 100.0

    events.sort()
    rep.anomaly_events = events
    if events:
        with open(os.path.join(sub, "events.txt"), "w", encoding="utf-8") as f:
            f.write(f"{'time(s)':>10s}  {'chan':<14s} {'type':<8s} {'delta':>10s}\n")
            for t, c, k, d, _ in events:
                f.write(f"{t:>10.3f}  {c:<14s} {k:<8s} {d:>10.3f}\n")


# ============================================================
# 分析器: 振动评分 (类 Betaflight)
# ============================================================
def analyzer_vibration(df: pd.DataFrame, rep: Report, outdir: str):
    if not ENABLE_VIBRATION_SCORE:
        return
    win = df[(df["t_s"] >= rep.active_t0) & (df["t_s"] <= rep.active_t1)]
    rms_total = 0.0
    n = 0
    for c in ACC_CHANNELS:
        if c in win.columns:
            x = win[c].to_numpy(float)
            x = x - np.mean(x)
            rms_total += float(np.sqrt(np.mean(x * x)))
            n += 1
    if n == 0:
        return
    rms_avg = rms_total / n
    rep.metrics["vib_acc_rms_avg"] = rms_avg
    if rms_avg > TH_VIB_RMS:
        rep.warnings.append(f"加速度振动 RMS={rms_avg:.0f} 偏高")
        rep.tips.append("振动偏高: 检查电机/桨叶平衡, 减速器避震, 必要时启用陀螺 notch")


# ============================================================
# 报告写出
# ============================================================
def write_summary(rep: Report, outdir: str):
    p = os.path.join(outdir, "summary.txt")
    L = []
    L.append(f"文件: {rep.file}")
    L.append(f"采样率: {SAMPLE_RATE_HZ:.0f} Hz | 点数: {rep.n_rows} | 总时长: {rep.duration_s:.2f}s")
    L.append(f"活动窗: [{rep.active_t0:.2f}, {rep.active_t1:.2f}]s "
             f"= {rep.active_t1 - rep.active_t0:.2f}s")
    if rep.static_t0 is not None:
        L.append(f"静态窗: [{rep.static_t0:.2f}, {rep.static_t1:.2f}]s")

    L.append("\n== 关键指标 ==")
    for k, v in rep.metrics.items():
        L.append(f"  {k:>28s} = {v:.3f}")

    L.append("\n== 通道统计 (活动窗内) ==")
    L.append(f"{'通道':<18s} {'mean':>10s} {'std':>10s} {'min':>10s} "
             f"{'max':>10s} {'|peak|':>10s} {'rms':>10s}")
    for c, st in rep.stats.items():
        L.append(f"{c:<18s} {st.mean:>10.3f} {st.std:>10.3f} "
                 f"{st.vmin:>10.3f} {st.vmax:>10.3f} {st.peak_abs:>10.3f} "
                 f"{st.rms:>10.3f}")

    if rep.fft_peaks:
        L.append("\n== 频谱主峰 (top3) ==")
        for grp, d in rep.fft_peaks.items():
            for c, peaks in d.items():
                pp = ", ".join(f"{f:.1f}Hz" for f, _ in peaks)
                L.append(f"  {c:<14s} {pp}")

    if rep.pid_response:
        L.append("\n== PID 阶跃响应 ==")
        for c, m in rep.pid_response.items():
            L.append(f"  {c}: amp={m['step_amp']:.2f}  rise={m['rise_s']:.2f}s  "
                     f"OS={m['overshoot_pct']:.1f}%  settle={m['settle_s']:.2f}s  "
                     f"ssErr={m['ss_err']:.2f}")

    if rep.coupling:
        L.append("\n== 轴耦合(Pearson r) ==")
        for k, v in rep.coupling.items():
            L.append(f"  {k:<24s} = {v:+.3f}")

    if rep.drift:
        L.append("\n== 静态漂移 / 零偏 ==")
        for k, v in rep.drift.items():
            if isinstance(v, dict):
                L.append(f"  {k}: bias={v['bias']:+.3f}  noise_std={v['noise_std']:.3f}")
            else:
                L.append(f"  {k} = {v:+.3f}")

    L.append("\n== 异常告警 ==")
    if rep.warnings:
        for w in rep.warnings:
            L.append(f"  [!] {w}")
    else:
        L.append("  无")

    L.append("\n== 调参建议 ==")
    if rep.tips:
        for t in rep.tips:
            L.append(f"  - {t}")
    else:
        L.append("  指标平稳, 无明显建议")

    if rep.anomaly_events:
        L.append(f"\n== 异常事件 ({len(rep.anomaly_events)}) ==  详见 anomaly/events.txt")
        for ev in rep.anomaly_events[:10]:
            L.append(f"  t={ev[0]:.3f}s  {ev[1]} {ev[2]} delta={ev[3]:+.2f}")
        if len(rep.anomaly_events) > 10:
            L.append(f"  ... ({len(rep.anomaly_events) - 10} more)")

    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


def write_metrics_json(rep: Report, outdir: str):
    payload = dict(
        file=rep.file,
        active=[rep.active_t0, rep.active_t1],
        metrics=rep.metrics,
        pid_response=rep.pid_response,
        coupling=rep.coupling,
        drift=rep.drift,
        warnings=rep.warnings,
        tips=rep.tips,
        n_anomaly=len(rep.anomaly_events),
    )
    with open(os.path.join(outdir, "metrics.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


# ============================================================
# 分析器注册表 (顺序执行)
# ============================================================
ANALYZERS = [
    ("basic", analyzer_basic),
    ("vibration", analyzer_vibration),
    ("fft", analyzer_fft),
    ("spectrogram", analyzer_spectrogram),
    ("distribution", analyzer_distribution),
    ("pid_response", analyzer_pid_response),
    ("coupling", analyzer_coupling),
    ("drift", analyzer_drift),
    ("anomaly", analyzer_anomaly),
]


# ============================================================
# 主流程
# ============================================================
def process_one(path: str, out_root: str) -> Report:
    name = os.path.splitext(os.path.basename(path))[0]
    outdir = os.path.join(out_root, name)
    os.makedirs(outdir, exist_ok=True)

    df_raw = load_csv(path)
    df = filter_columns(df_raw)
    t0, t1 = detect_active_window(df)
    static = detect_static_window(df, (t0, t1))

    rep = Report(
        file=path,
        n_rows=len(df),
        duration_s=float(df["t_s"].iloc[-1] - df["t_s"].iloc[0]),
        active_t0=t0, active_t1=t1,
        static_t0=static[0] if static else None,
        static_t1=static[1] if static else None,
    )

    for name_, fn in ANALYZERS:
        try:
            fn(df, rep, outdir)
        except Exception as e:
            rep.warnings.append(f"[analyzer:{name_}] {type(e).__name__}: {e}")

    write_summary(rep, outdir)
    write_metrics_json(rep, outdir)
    return rep


def write_compare(reports: list, out_root: str):
    if not reports:
        return
    rows = []
    for r in reports:
        row = {"file": os.path.basename(r.file)}
        row.update(r.metrics)
        rows.append(row)
    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(out_root, "_compare_summary.csv"),
              index=False, encoding="utf-8-sig")

    keys = [k for k in (
        "FC_ATT_ROL_peak", "FC_ATT_PIT_peak",
        "FC_ACC_X_rms", "FC_ACC_Y_rms",
        "alt_drift_cm", "vib_acc_rms_avg")
        if k in df.columns]
    if not keys:
        return
    fig, ax = plt.subplots(figsize=(11, max(3, 0.6 * len(keys) + 2)))
    x = np.arange(len(df))
    w = 0.8 / max(1, len(keys))
    for i, k in enumerate(keys):
        ax.bar(x + i * w, df[k], width=w, label=k)
    ax.set_xticks(x + (len(keys) - 1) * w / 2)
    ax.set_xticklabels([os.path.splitext(n)[0] for n in df["file"]],
                       rotation=15, fontsize=9)
    ax.set_ylabel("value"); ax.legend(fontsize=8)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(os.path.join(out_root, "_compare_overview.png"), dpi=130)
    plt.close(fig)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    csvs = sorted(glob.glob(os.path.join(here, "*.csv")))
    if not csvs:
        print("[ERR] 当前目录没有 CSV")
        return
    out_root = os.path.join(here, OUT_DIR_NAME)
    os.makedirs(out_root, exist_ok=True)

    reports = []
    for p in csvs:
        print(f"[INFO] 处理: {os.path.basename(p)}")
        try:
            rep = process_one(p, out_root)
            reports.append(rep)
        except Exception as e:
            print(f"[ERR] {p}: {type(e).__name__}: {e}")

    write_compare(reports, out_root)
    print(f"[DONE] 输出: {out_root}")


if __name__ == "__main__":
    main()
