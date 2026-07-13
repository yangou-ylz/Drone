"""
Robust PID tuning under disturbance scenarios.

Usage:
    python tune_robust.py

It performs random search on (kp, ki, kd), evaluates each candidate on:
- baseline
- x_ref_only
- x_meas_only
- mixed_all

Note:
The vx_obs_only / mixed_all with integrated biased vx can introduce
estimation bias that PID alone cannot fully eliminate. This script still
reports metrics, but the final recommendation focuses on practical
stability and low oscillation.
"""

from pathlib import Path
import csv
import random

import config as cfg
from simulator import run_sim
from analyze import compute_drift_metrics


def _cases_for_tuning():
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
        },
    }


def _score_one_case(res):
    m = res["metrics"]
    d = compute_drift_metrics(res)

    settle_penalty = 0.0 if m["settling_time_s"] is not None else 25.0
    settle_time = 0.0 if m["settling_time_s"] is None else float(m["settling_time_s"])

    # Weighted sum: lower is better.
    score = 0.0
    score += 1.0 * float(m["IAE"])
    score += 1.8 * float(m["overshoot_pct"])
    score += 2.0 * float(settle_time)
    score += 20.0 * abs(float(d["tail_bias_from_setpoint_cm"]))
    score += 40.0 * abs(float(d["tail_drift_slope_cmps"]))
    score += settle_penalty
    return score


def _aggregate_score(case_results):
    # Give higher importance to baseline/x_ref/x_meas practical stability.
    weights = {
        "baseline": 1.0,
        "x_ref_only": 1.1,
        "x_meas_only": 1.2,
        "mixed_all": 0.6,
    }
    total = 0.0
    for name, res in case_results.items():
        total += weights[name] * _score_one_case(res)
    return total


def evaluate_candidate(kp, ki, kd, sim_time, cases):
    per_case = {}
    for i, (name, dis) in enumerate(cases.items()):
        res = run_sim(
            cfg,
            kp=kp,
            ki=ki,
            kd=kd,
            sim_time=sim_time,
            disturbance=dis,
            rng_seed=2000 + i,
            verbose=False,
        )
        per_case[name] = res
    return per_case, _aggregate_score(per_case)


def random_search(n_trials=200, sim_time=20.0, seed=7):
    random.seed(seed)
    cases = _cases_for_tuning()

    records = []

    for i in range(n_trials):
        # Search ranges chosen for this plant and safety-oriented response.
        kp = random.uniform(0.6, 3.0)
        ki = random.uniform(0.0, 0.6)
        kd = random.uniform(0.0, 0.25)

        per_case, score = evaluate_candidate(kp, ki, kd, sim_time, cases)

        rec = {
            "kp": round(kp, 4),
            "ki": round(ki, 4),
            "kd": round(kd, 4),
            "score": round(score, 4),
        }
        for name, res in per_case.items():
            m = res["metrics"]
            d = compute_drift_metrics(res)
            rec[f"{name}_overshoot"] = m["overshoot_pct"]
            rec[f"{name}_settle"] = -1 if m["settling_time_s"] is None else m["settling_time_s"]
            rec[f"{name}_iae"] = m["IAE"]
            rec[f"{name}_bias"] = d["tail_bias_from_setpoint_cm"]

        records.append(rec)

        if (i + 1) % 25 == 0:
            print(f"progress: {i + 1}/{n_trials}")

    records.sort(key=lambda r: r["score"])
    return records


def save_csv(records, out_csv):
    if not records:
        return
    keys = list(records[0].keys())
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(records)


def main():
    out_dir = Path(__file__).resolve().parent / "outputs"
    out_dir.mkdir(exist_ok=True)

    n_trials = 220
    sim_time = cfg.LONG_SIM_TIME

    print("=" * 60)
    print(f"Robust tuning start: trials={n_trials}, sim_time={sim_time}s")
    print("=" * 60)

    records = random_search(n_trials=n_trials, sim_time=sim_time, seed=7)

    out_csv = out_dir / "robust_tuning_ranking.csv"
    save_csv(records, out_csv)

    print("\nTop 10 candidates:")
    for i, r in enumerate(records[:10], 1):
        print(
            f"{i:2d}. kp={r['kp']:.4f} ki={r['ki']:.4f} kd={r['kd']:.4f} "
            f"score={r['score']:.3f} | "
            f"base_ov={r['baseline_overshoot']}% base_settle={r['baseline_settle']}s "
            f"meas_settle={r['x_meas_only_settle']}s"
        )

    best = records[0]
    print("\nRecommended (robust):")
    print(f"kp={best['kp']:.4f}, ki={best['ki']:.4f}, kd={best['kd']:.4f}")
    print(f"ranking csv: {out_csv}")


if __name__ == "__main__":
    main()
