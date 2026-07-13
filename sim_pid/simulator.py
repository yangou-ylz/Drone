"""
闭环仿真器 + 性能指标。
"""

import numpy as np
from pid_core import Pid
from plant   import DronePlant


def _disturbance_at_step(k, dt, rng, cfg):
    """生成单步干扰值：高斯 + 正弦波动 + 随机尖峰。"""
    if cfg is None:
        return 0.0

    n_std = float(cfg.get("noise_std", 0.0))
    s_amp = float(cfg.get("sin_amp", 0.0))
    s_f_hz = float(cfg.get("sin_freq_hz", 0.0))
    p_spk = float(cfg.get("spike_prob", 0.0))
    s_spk = float(cfg.get("spike_amp", 0.0))

    t = k * dt
    val = 0.0

    if n_std > 0.0:
        val += rng.normal(0.0, n_std)
    if s_amp != 0.0 and s_f_hz > 0.0:
        val += s_amp * np.sin(2.0 * np.pi * s_f_hz * t)
    if p_spk > 0.0 and rng.random() < p_spk:
        sign = -1.0 if rng.random() < 0.5 else 1.0
        val += sign * s_spk

    return float(val)


def run_sim(cfg, *,
            kp=None, ki=None, kd=None,
            setpoint=None, sim_time=None,
            plant=None, disturbance=None,
            rng_seed=123, verbose=False):
    """
    跑一次闭环仿真。返回 dict 含 numpy 数组（时间序列）+ 性能指标。

    cfg      : config 模块（含默认参数）
    kp/ki/kd : 可覆盖 cfg 的默认增益，便于扫参
    plant    : 可传入已构造的 plant，便于复用 RNG 种子
    """
    # ---- 参数解析 ----
    kp       = cfg.KP if kp is None else kp
    ki       = cfg.KI if ki is None else ki
    kd       = cfg.KD if kd is None else kd
    sp       = cfg.SETPOINT if setpoint is None else setpoint
    duration = cfg.SIM_TIME if sim_time is None else sim_time
    dt       = cfg.DT
    n_steps  = int(duration / dt) + 1
    rng      = np.random.default_rng(rng_seed)

    # 干扰配置（可选）
    # disturbance = {
    #   "x_ref":  {noise_std,sin_amp,sin_freq_hz,spike_prob,spike_amp},
    #   "x_meas": {noise_std,sin_amp,sin_freq_hz,spike_prob,spike_amp},
    #   "vx_obs": {bias,noise_std,sin_amp,sin_freq_hz,spike_prob,spike_amp,
    #              "use_integrated_x": True/False}
    # }
    disturbance = {} if disturbance is None else disturbance
    dis_ref = disturbance.get("x_ref", None)
    dis_meas = disturbance.get("x_meas", None)
    dis_vx = disturbance.get("vx_obs", None)
    use_integrated_x = bool((dis_vx or {}).get("use_integrated_x", False))
    vx_bias = float((dis_vx or {}).get("bias", 0.0))

    # ---- 构造 PID（参数与 MCU 完全一致）----
    pid = Pid()
    pid.set_gains(kp, ki, kd)
    pid.set_limits(cfg.OUT_LIM, cfg.I_LIM)
    pid.d_lpf_alpha = cfg.D_LPF_ALPHA
    pid.dead_zone   = cfg.DEAD_ZONE
    pid.d_on_meas   = cfg.D_ON_MEAS
    pid.enable      = True

    # ---- 构造被控对象 ----
    if plant is None:
        plant = DronePlant(tau=cfg.PLANT_TAU, v_max=cfg.PLANT_V_MAX,
                           a_max=cfg.PLANT_A_MAX, noise_std=cfg.PLANT_NOISE_STD)
    plant.reset()

    # ---- 数据缓冲 ----
    t       = np.zeros(n_steps)
    x_ref   = np.zeros(n_steps)  # PID 实际使用的参考输入（含噪）
    x_meas  = np.zeros(n_steps)  # 测量位置（含噪）
    x_meas_raw = np.zeros(n_steps)  # 植物输出原始位置（无额外观测噪声）
    x_true  = np.zeros(n_steps)  # 真实位置
    v_true  = np.zeros(n_steps)  # 真实速度
    v_obs   = np.zeros(n_steps)  # 观测速度（用于集成位置时）
    v_cmd   = np.zeros(n_steps)  # PID 输出（速度指令）
    err     = np.zeros(n_steps)
    p_arr   = np.zeros(n_steps)
    i_arr   = np.zeros(n_steps)
    d_arr   = np.zeros(n_steps)

    meas = 0.0
    x_from_v = 0.0
    for k in range(n_steps):
        # 1) 生成参考输入干扰（x_ref）
        ref_noise = _disturbance_at_step(k, dt, rng, dis_ref)
        sp_k = sp + ref_noise

        # 2) PID 计算
        out = pid.update(sp_k, meas, dt)

        # 3) 植物推进，得到原始位置/真实速度
        meas_raw = plant.step(out, dt)
        xt, vt = plant.true_state()

        # 4) 生成观测噪声（x'）
        meas_noise = _disturbance_at_step(k, dt, rng, dis_meas)

        # 5) 生成观测速度噪声/偏差（vx_obs）
        vx_noise = _disturbance_at_step(k, dt, rng, dis_vx)
        v_obs_k = vt + vx_bias + vx_noise

        # 6) 选择测量链路：直接位置测量 或 用观测速度积分成位置
        if use_integrated_x:
            x_from_v += v_obs_k * dt
            meas = x_from_v + meas_noise
        else:
            meas = meas_raw + meas_noise

        t[k]      = k * dt
        x_ref[k]  = sp_k
        x_meas[k] = meas
        x_meas_raw[k] = meas_raw
        x_true[k] = xt
        v_true[k] = vt
        v_obs[k]  = v_obs_k
        v_cmd[k]  = out
        err[k]    = sp_k - meas
        p_arr[k]  = pid.last_p
        i_arr[k]  = pid.last_i
        d_arr[k]  = pid.last_d

    # ---- 性能指标 ----
    metrics = compute_metrics(t, x_true, sp, cfg)

    if verbose:
        print(f"[SIM] kp={kp:.3f} ki={ki:.3f} kd={kd:.3f}")
        for k, v in metrics.items():
            print(f"      {k:18s} = {v}")

    return {
        "t": t,
        "x_ref": x_ref,
        "x_meas": x_meas,
        "x_meas_raw": x_meas_raw,
        "x_true": x_true,
        "v_true": v_true,
        "v_obs": v_obs,
        "v_cmd": v_cmd, "err": err,
        "p": p_arr, "i": i_arr, "d": d_arr,
        "setpoint": sp,
        "kp": kp, "ki": ki, "kd": kd,
        "disturbance": disturbance,
        "metrics": metrics,
    }


def compute_metrics(t, x, sp, cfg):
    """计算上升时间、超调、调节时间、稳态误差、IAE。"""
    n = len(t)
    band   = cfg.SETTLING_BAND
    hold_n = int(cfg.SETTLING_HOLD / cfg.DT)

    # 上升时间：x 首次到达 90% setpoint
    target90 = 0.9 * sp
    rise_t = None
    for k in range(n):
        if (sp >= 0 and x[k] >= target90) or (sp < 0 and x[k] <= target90):
            rise_t = t[k]; break

    # 超调：max(x - sp) / sp
    if sp != 0:
        peak = np.max(x) if sp > 0 else np.min(x)
        overshoot = (peak - sp) / sp * 100.0 if sp > 0 else (sp - peak) / abs(sp) * 100.0
        overshoot = max(0.0, overshoot)
    else:
        overshoot = 0.0

    # 调节时间：最后一次进入调节带且保持的起点
    settle_t = None
    in_band  = 0
    settle_idx = None
    for k in range(n):
        if abs(x[k] - sp) < band:
            if in_band == 0:
                settle_idx = k
            in_band += 1
            if in_band >= hold_n and settle_t is None:
                settle_t = t[settle_idx]
                break
        else:
            in_band = 0
            settle_idx = None

    # 稳态误差：最后 10% 时间的平均误差
    tail = max(1, n // 10)
    ss_err = float(np.mean(np.abs(x[-tail:] - sp)))

    # IAE：积分绝对误差
    iae = float(np.sum(np.abs(x - sp)) * cfg.DT)

    return {
        "rise_time_s":     rise_t,
        "overshoot_pct":   round(overshoot, 2),
        "settling_time_s": settle_t,
        "steady_err_cm":   round(ss_err, 4),
        "IAE":             round(iae, 3),
    }
