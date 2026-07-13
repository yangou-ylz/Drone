"""
绘图与对比分析。
"""

import matplotlib.pyplot as plt
import numpy as np


def setup_chinese_font():
    """设置中文字体，避免中文标题/标签显示为方框。"""
    plt.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False


def compute_drift_metrics(res):
    """计算长时漂移指标，便于观察收敛后的慢漂。"""
    t = res["t"]
    x = res["x_true"]
    sp = res["setpoint"]
    n = len(t)

    # 统计后 40% 时间段，避免初始过渡态干扰
    tail_n = max(2, int(0.4 * n))
    x_tail = x[-tail_n:]
    t_tail = t[-tail_n:]

    x_mean = float(np.mean(x_tail))
    x_std = float(np.std(x_tail))
    peak_to_peak = float(np.max(x_tail) - np.min(x_tail))

    # 用一阶线性拟合估计趋势斜率（cm/s）；绝对值越小，长期漂移越小
    coeff = np.polyfit(t_tail, x_tail, 1)
    drift_slope = float(coeff[0])

    return {
        # 尾段绝对位置均值（用于看系统最终停在什么位置）
        "tail_position_mean_cm": round(x_mean, 4),
        # 尾段相对目标偏差均值（真正的长期偏差/漂移量）
        "tail_bias_from_setpoint_cm": round(x_mean - sp, 4),
        # 尾段抖动强度
        "tail_position_std_cm": round(x_std, 4),
        # 尾段峰峰值抖动
        "tail_position_p2p_cm": round(peak_to_peak, 4),
        # 尾段趋势斜率（绝对值越小越不漂）
        "tail_drift_slope_cmps": round(drift_slope, 6),
    }


def export_timeseries_csv(res, out_csv):
    """导出时序数据 CSV，便于后期离线分析。"""
    header = (
        "t_s,x_ref_cm,x_meas_cm,x_meas_raw_cm,x_true_cm,"
        "v_true_cmps,v_obs_cmps,v_cmd_cmps,err_cm,p_term,i_term,d_term"
    )
    data = np.column_stack(
        [
            res["t"],
            res["x_ref"],
            res["x_meas"],
            res["x_meas_raw"],
            res["x_true"],
            res["v_true"],
            res["v_obs"],
            res["v_cmd"],
            res["err"],
            res["p"],
            res["i"],
            res["d"],
        ]
    )
    np.savetxt(out_csv, data, delimiter=",", header=header, comments="")


def plot_single(res, title_suffix=""):
    """单次仿真：4 张子图。"""
    setup_chinese_font()
    t  = res["t"]
    sp = res["setpoint"]
    m  = res["metrics"]
    dm = compute_drift_metrics(res)

    fig, axes = plt.subplots(3, 2, figsize=(14, 10))
    fig.suptitle(
        f"PID 闭环响应  kp={res['kp']:.2f} ki={res['ki']:.2f} kd={res['kd']:.2f}  "
        f"{title_suffix}\n"
        f"rise={m['rise_time_s']}s  overshoot={m['overshoot_pct']}%  "
        f"settle={m['settling_time_s']}s  ss_err={m['steady_err_cm']}cm  IAE={m['IAE']}  "
        f"drift={dm['tail_drift_slope_cmps']}cm/s"
    )

    # 1. 位置响应（全时段）
    ax = axes[0, 0]
    ax.plot(t, res["x_true"], "b-",  label="x_true")
    if not np.allclose(res["x_meas"], res["x_true"]):
        ax.plot(t, res["x_meas"], "c.", markersize=2, alpha=0.5, label="x_meas (with noise)")
    ax.axhline(sp, color="r", ls="--", label=f"setpoint={sp}cm")
    ax.set_xlabel("t (s)"); ax.set_ylabel("x (cm)")
    ax.set_title("位置响应（全时段）"); ax.legend(); ax.grid(True)

    # 2. 速度指令 vs 真实速度
    ax = axes[0, 1]
    ax.plot(t, res["v_cmd"],  "g-", label="v_cmd (PID out)")
    ax.plot(t, res["v_true"], "b-", label="v_actual (plant)", alpha=0.7)
    ax.set_xlabel("t (s)"); ax.set_ylabel("v (cm/s)")
    ax.set_title("速度指令与真实速度"); ax.legend(); ax.grid(True)

    # 3. 误差
    ax = axes[1, 0]
    ax.plot(t, res["err"], "r-")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_xlabel("t (s)"); ax.set_ylabel("err (cm)")
    ax.set_title("跟踪误差"); ax.grid(True)

    # 4. P / I / D 分量
    ax = axes[1, 1]
    ax.plot(t, res["p"], label="P term")
    ax.plot(t, res["i"], label="I term")
    ax.plot(t, res["d"], label="D term")
    ax.plot(t, res["v_cmd"], "k--", label="sum (=v_cmd)", lw=1)
    ax.set_xlabel("t (s)"); ax.set_ylabel("term")
    ax.set_title("PID 分量分解"); ax.legend(); ax.grid(True)

    # 5. 尾段漂移放大图（后 40%）
    tail_n = max(2, int(0.4 * len(t)))
    t_tail = t[-tail_n:]
    x_tail = res["x_true"][-tail_n:]
    ax = axes[2, 0]
    ax.plot(t_tail, x_tail, "b-", label="x_true tail")
    ax.axhline(sp, color="r", ls="--", lw=1, label="setpoint")
    ax.set_xlabel("t (s)"); ax.set_ylabel("x (cm)")
    ax.set_title("尾段漂移放大图（后40%）")
    ax.legend(); ax.grid(True)

    # 6. 漂移指标文本面板
    ax = axes[2, 1]
    ax.axis("off")
    txt = (
        "漂移指标（后40%时段）\n"
        f"尾段位置均值(cm)      = {dm['tail_position_mean_cm']}\n"
        f"尾段相对目标偏差(cm)  = {dm['tail_bias_from_setpoint_cm']}\n"
        f"尾段标准差(cm)        = {dm['tail_position_std_cm']}\n"
        f"尾段峰峰值(cm)        = {dm['tail_position_p2p_cm']}\n"
        f"尾段漂移斜率(cm/s)    = {dm['tail_drift_slope_cmps']}\n"
    )
    ax.text(0.02, 0.95, txt, va="top", ha="left", fontsize=11)

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    return fig


def plot_compare(results, labels=None):
    """对比多次仿真（参数扫描时用）。"""
    setup_chinese_font()
    if labels is None:
        labels = [f"kp={r['kp']:.1f} ki={r['ki']:.1f} kd={r['kd']:.2f}" for r in results]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    sp = results[0]["setpoint"]

    for r, lab in zip(results, labels):
        axes[0].plot(r["t"], r["x_true"], label=lab)
        axes[1].plot(r["t"], r["v_cmd"],  label=lab)

    axes[0].axhline(sp, color="r", ls="--", lw=1)
    axes[0].set_ylabel("x (cm)"); axes[0].set_title("位置响应对比")
    axes[0].legend(fontsize=8); axes[0].grid(True)

    axes[1].set_ylabel("v_cmd (cm/s)"); axes[1].set_xlabel("t (s)")
    axes[1].set_title("速度指令对比")
    axes[1].legend(fontsize=8); axes[1].grid(True)
    plt.tight_layout()
    return fig


def print_metrics_table(results, labels=None):
    """把多次仿真的指标打成表。"""
    if labels is None:
        labels = [f"kp={r['kp']:.2f} ki={r['ki']:.2f} kd={r['kd']:.2f}" for r in results]
    cols = ["rise_time_s", "overshoot_pct", "settling_time_s", "steady_err_cm", "IAE"]
    head = f"{'config':40s} " + " ".join(f"{c:>16s}" for c in cols)
    print(head); print("-" * len(head))
    for r, lab in zip(results, labels):
        m = r["metrics"]
        line = f"{lab:40s} " + " ".join(f"{str(m[c]):>16s}" for c in cols)
        print(line)
