"""
单次仿真主入口。

用法：
    python run.py                 # 长时仿真（默认 LONG_SIM_TIME）
    python run.py 2.5 0.3 0.15    # 覆盖 kp ki kd
    python run.py 2.5 0.3 0.15 30 # 覆盖 kp ki kd sim_time
"""

import sys
from pathlib import Path
import config as cfg
from simulator import run_sim
from analyze   import plot_single, export_timeseries_csv, compute_drift_metrics
import matplotlib.pyplot as plt


def main():
    kp = ki = kd = None
    sim_time = cfg.LONG_SIM_TIME

    if len(sys.argv) >= 4:
        kp, ki, kd = map(float, sys.argv[1:4])
    if len(sys.argv) >= 5:
        sim_time = float(sys.argv[4])

    res = run_sim(cfg, kp=kp, ki=ki, kd=kd, sim_time=sim_time, verbose=True)
    drift = compute_drift_metrics(res)

    print("[DRIFT]")
    print(f"  {'尾段位置均值(cm)':20s} = {drift['tail_position_mean_cm']}")
    print(f"  {'尾段相对目标偏差(cm)':20s} = {drift['tail_bias_from_setpoint_cm']}")
    print(f"  {'尾段标准差(cm)':20s} = {drift['tail_position_std_cm']}")
    print(f"  {'尾段峰峰值(cm)':20s} = {drift['tail_position_p2p_cm']}")
    print(f"  {'尾段漂移斜率(cm/s)':20s} = {drift['tail_drift_slope_cmps']}")

    fig = plot_single(res, title_suffix=f"sim_time={sim_time}s")

    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    stem = f"kp{res['kp']:.2f}_ki{res['ki']:.2f}_kd{res['kd']:.2f}_T{sim_time:.0f}"
    fig_path = out_dir / f"{stem}.png"
    csv_path = out_dir / f"{stem}.csv"
    fig.savefig(fig_path, dpi=150)
    export_timeseries_csv(res, csv_path)
    print(f"[SAVE] figure: {fig_path}")
    print(f"[SAVE] csv   : {csv_path}")

    plt.show()


if __name__ == "__main__":
    main()
