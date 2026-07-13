import config
from simulator import run_sim
import numpy as np

kp = 1.27
ki = 0.0043
kd = 0.0332
sim_time = 20.0

cases = [
    {"bias": 1.2, "name": "Case 1: bias=1.2"},
    {"bias": 0.0, "name": "Case 2: bias=0.0"}
]

for case in cases:
    bias = case["bias"]
    disturbance = {
        "vx_obs": {
            "bias": bias,
            "use_integrated_x": True
        }
    }
    
    res = run_sim(config, kp=kp, ki=ki, kd=kd, sim_time=sim_time, disturbance=disturbance)
    
    x_true = res["x_true"]
    x_meas = res["x_meas"]
    v_cmd = res["v_cmd"]
    
    final_x_true = x_true[-1]
    final_x_meas = x_meas[-1]
    final_v_cmd = v_cmd[-1]
    min_x_true = np.min(x_true)
    
    print(f"--- {case['name']} ---")
    print(f"final x_true: {final_x_true:.4f}")
    print(f"final x_meas: {final_x_meas:.4f}")
    print(f"final v_cmd: {final_v_cmd:.4f}")
    print(f"min x_true: {min_x_true:.4f}")
    print()
