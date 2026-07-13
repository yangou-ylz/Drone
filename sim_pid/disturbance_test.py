"""
多干扰测试入口：控制变量法 + 混合测试。

目标：
1) x_ref 噪声（输入预期 x）
2) x' 噪声（观测位置 x_meas）
3) vx 观测偏差/噪声（可选择通过积分 vx_obs 得到位置测量）

用法：
    python disturbance_test.py

输出：
- 终端表格：每个场景指标
- outputs/disturbance_*.png 对比图
- outputs/disturbance_*.csv 时序数据
"""

from pathlib import Path
import matplotlib.pyplot as plt
import config as cfg
from simulator import run_sim
from analyze import (
    plot_compare,
    plot_single,
    export_timeseries_csv,
    compute_drift_metrics,
    setup_chinese_font,
)


def _print_case_result(name, res):
    m = res["metrics"]
    d = compute_drift_metrics(res)
    print(f"\n[{name}]")
    print(
        f"  rise={m['rise_time_s']}s  overshoot={m['overshoot_pct']}%  "
        f"settle={m['settling_time_s']}s  ss_err={m['steady_err_cm']}cm  IAE={m['IAE']}"
    )
    print(
        f"  偏差={d['tail_bias_from_setpoint_cm']}cm  "
        f"漂移斜率={d['tail_drift_slope_cmps']}cm/s  "
        f"抖动std={d['tail_position_std_cm']}cm"
    )


def _case_control_variable():
    """控制变量法：每次只加一种干扰。"""
    return {
        "baseline": {},
        "x_ref_only": {
            "x_ref": {
                "noise_std": 0.20,
                "sin_amp": 0.50,
                "sin_freq_hz": 1.2,
                "spike_prob": 0.015,
                "spike_amp": 2.50,
            }
        },
        "x_meas_only": {
            "x_meas": {
                "noise_std": 0.30,
                "sin_amp": 0.80,
                "sin_freq_hz": 1.0,
                "spike_prob": 0.020,
                "spike_amp": 3.00,
            }
        },
        "vx_obs_only": {
            "vx_obs": {
                "bias": 1.20,
                "noise_std": 0.40,
                "sin_amp": 0.60,
                "sin_freq_hz": 0.8,
                "spike_prob": 0.015,
                "spike_amp": 2.00,
                "use_integrated_x": True,
            }
        },
    }


def _case_mixed():
    """混合测试：三类干扰同时叠加。"""
    return {
        "mixed_all": {
            "x_ref": {
                "noise_std": 0.20,
                "sin_amp": 0.50,
                "sin_freq_hz": 1.2,
                "spike_prob": 0.015,
                "spike_amp": 2.50,
            },
            "x_meas": {
                "noise_std": 0.30,
                "sin_amp": 0.80,
                "sin_freq_hz": 1.0,
                "spike_prob": 0.020,
                "spike_amp": 3.00,
            },
            "vx_obs": {
                "bias": 1.20,
                "noise_std": 0.40,
                "sin_amp": 0.60,
                "sin_freq_hz": 0.8,
                "spike_prob": 0.015,
                "spike_amp": 2.00,
                "use_integrated_x": True,
            },
        }
    }


def _run_cases(cases, sim_time, out_prefix):
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(exist_ok=True)

    results = []
    labels = []

    for i, (name, dis) in enumerate(cases.items()):
        # 每个场景固定不同随机种子，便于复现
        res = run_sim(
            cfg,
            kp=cfg.KP,
            ki=cfg.KI,
            kd=cfg.KD,
            sim_time=sim_time,
            disturbance=dis,
            rng_seed=1000 + i,
            verbose=False,
        )
        _print_case_result(name, res)

        csv_path = out_dir / f"{out_prefix}_{name}.csv"
        export_timeseries_csv(res, csv_path)
        print(f"  CSV: {csv_path}")

        # 导出单场景详细图（与 run.py 同级信息量）
        fig_detail = plot_single(res, title_suffix=f"case={name}, sim_time={sim_time}s")
        detail_png_path = out_dir / f"{out_prefix}_{name}_detail.png"
        fig_detail.savefig(detail_png_path, dpi=150)
        plt.close(fig_detail)
        print(f"  详细图: {detail_png_path}")

        results.append(res)
        labels.append(name)

    setup_chinese_font()
    fig = plot_compare(results, labels)
    fig.suptitle(f"多干扰测试对比（sim_time={sim_time}s）", fontsize=14)
    png_path = out_dir / f"{out_prefix}_compare.png"
    fig.savefig(png_path, dpi=150)
    plt.close(fig)
    print(f"\n[保存] 对比图: {png_path}")


def main():
    sim_time = cfg.LONG_SIM_TIME
    print("=" * 60)
    print("阶段1：控制变量法（每次只加一种干扰）")
    print("=" * 60)
    _run_cases(_case_control_variable(), sim_time, out_prefix="disturbance_cvar")

    print("\n" + "=" * 60)
    print("阶段2：混合测试（三类干扰同时叠加）")
    print("=" * 60)
    _run_cases(_case_mixed(), sim_time, out_prefix="disturbance_mixed")


if __name__ == "__main__":
    main()
