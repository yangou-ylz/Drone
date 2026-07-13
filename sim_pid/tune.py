"""
参数扫描调参工具。

策略：两阶段
  1) 粗扫：网格扫 Kp，Ki=Kd=0 找出"无振荡的最大 Kp"
  2) 细调：固定 Kp，扫 Kd 抑制超调，再加小 Ki 消稳态误差

最终按综合得分排序输出 top N，绘对比图。

得分函数（越小越好）：
  score = IAE + 5*overshoot_pct + 10*steady_err + (settling_time 缺失时罚分)
"""

import numpy as np
import matplotlib.pyplot as plt
import config as cfg
from simulator import run_sim
from analyze   import plot_compare, print_metrics_table


def score(res):
    m  = res["metrics"]
    s  = m["IAE"]
    s += 5.0 * m["overshoot_pct"]
    s += 10.0 * m["steady_err_cm"]
    if m["settling_time_s"] is None:
        s += 100.0   # 未收敛重罚
    else:
        s += m["settling_time_s"] * 2.0
    return s


def grid_search(kp_list, ki_list, kd_list):
    results = []
    total = len(kp_list) * len(ki_list) * len(kd_list)
    i = 0
    for kp in kp_list:
        for ki in ki_list:
            for kd in kd_list:
                i += 1
                res = run_sim(cfg, kp=kp, ki=ki, kd=kd)
                res["score"] = score(res)
                results.append(res)
                if i % 10 == 0 or i == total:
                    print(f"  progress {i}/{total}")
    results.sort(key=lambda r: r["score"])
    return results


def main():
    print("=" * 60)
    print("Stage 1: Kp 粗扫 (Ki=0, Kd=0)")
    print("=" * 60)
    s1 = grid_search(
        kp_list=[0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0],
        ki_list=[0.0],
        kd_list=[0.0],
    )
    print_metrics_table(s1[:5])
    best_kp = s1[0]["kp"]
    print(f"\n>> Best Kp (stage 1) = {best_kp}")

    print("\n" + "=" * 60)
    print(f"Stage 2: 固定 Kp={best_kp}, 扫 Kd")
    print("=" * 60)
    s2 = grid_search(
        kp_list=[best_kp],
        ki_list=[0.0],
        kd_list=[0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.50],
    )
    print_metrics_table(s2[:5])
    best_kd = s2[0]["kd"]
    print(f"\n>> Best Kd (stage 2) = {best_kd}")

    print("\n" + "=" * 60)
    print(f"Stage 3: 固定 Kp={best_kp} Kd={best_kd}, 加 Ki")
    print("=" * 60)
    s3 = grid_search(
        kp_list=[best_kp],
        ki_list=[0.0, 0.1, 0.2, 0.5, 1.0, 2.0],
        kd_list=[best_kd],
    )
    print_metrics_table(s3[:5])

    print("\n" + "=" * 60)
    print("TOP 5 综合最优（用于绘图对比）")
    print("=" * 60)
    top = s3[:5]
    print_metrics_table(top)

    print(f"\n>>> 推荐参数：kp={top[0]['kp']:.3f}  ki={top[0]['ki']:.3f}  kd={top[0]['kd']:.3f}")
    print(f"    把这三个数填回 sim_pid/config.py 或直接搬到 MCU 测试任务。")

    plot_compare(top)
    plt.show()


if __name__ == "__main__":
    main()
