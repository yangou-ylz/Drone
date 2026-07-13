import sys
from pathlib import Path
import config as cfg
from simulator import run_sim
from analyze import compute_drift_metrics

kp, ki, kd = 1.27, 0.0043, 0.03
sim_time = 20.0

# Define local noise constants since they are missing from config
REF_NOISE_STD = 0.5
MEAS_NOISE_STD = 0.8

scenarios = [
    ("baseline", {}),
    ("x_ref_only", {"x_ref": {"noise_std": REF_NOISE_STD}}),
    ("x_meas_only", {"x_meas": {"noise_std": MEAS_NOISE_STD}}),
    ("vx_obs_only", {"vx_obs": {"bias": 1.2, "use_integrated_x": True}}),
    ("mixed_all", {
        "x_ref": {"noise_std": REF_NOISE_STD},
        "x_meas": {"noise_std": MEAS_NOISE_STD},
        "vx_obs": {"bias": 1.2, "use_integrated_x": True}
    })
]

results = []
for name, dist in scenarios:
    res = run_sim(cfg, kp=kp, ki=ki, kd=kd, sim_time=sim_time, disturbance=dist, verbose=False)
    res['label'] = name
    results.append(res)

header = f"{'Scenario':15} {'RiseT':>7} {'Over%':>7} {'SettlT':>7} {'S-Err':>8} {'IAE':>10} {'T-Bias':>8} {'T-Slope':>9} {'Final X':>8}"
print(header)
print("-" * len(header))

for r in results:
    m = r['metrics']
    dm = compute_drift_metrics(r)
    final_x = r['x_true'][-1]
    
    rt = f"{m['rise_time_s']:.2f}" if m['rise_time_s'] is not None else "None"
    st = f"{m['settling_time_s']:.2f}" if m['settling_time_s'] is not None else "None"
    
    line = (f"{r['label']:15} {rt:>7} {m['overshoot_pct']:>7} "
            f"{st:>7} {m['steady_err_cm']:>8} {m['IAE']:>10} "
            f"{dm['tail_bias_from_setpoint_cm']:>8} {dm['tail_drift_slope_cmps']:>9} {final_x:>8.2f}")
    print(line)
