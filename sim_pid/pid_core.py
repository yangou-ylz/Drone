"""
PID 算法核心。

?? 重要：本文件与 FcSrc/Ctrl_PID.c 必须保持逐行对应。
任何改动须同步两边，否则仿真结果对 MCU 无参考价值。

对应关系：
  Pid.__init__          ← Pid_Init        (Ctrl_PID.c:18)
  Pid.reset             ← Pid_Reset       (Ctrl_PID.c:40)
  Pid.set_gains         ← Pid_SetGains    (Ctrl_PID.c:53)
  Pid.set_limits        ← Pid_SetLimits   (Ctrl_PID.c:73)
  Pid.update            ← Pid_Update      (Ctrl_PID.c:88)
"""


def _clamp(v, lo, hi):
    if v > hi: return hi
    if v < lo: return lo
    return v


class Pid:
    def __init__(self):
        # 增益
        self.kp = 0.0
        self.ki = 0.0
        self.kd = 0.0
        # 限幅
        self.out_max = 0.0
        self.out_min = 0.0
        self.i_max   = 0.0
        # 行为
        self.d_lpf_alpha = 1.0
        self.dead_zone   = 0.0
        self.d_on_meas   = True
        self.enable      = False
        # 运行时状态
        self.reset()

        # 调试用：本步各分量贡献（C 版没有，仅 Python 暴露便于绘图）
        self.last_p = 0.0
        self.last_i = 0.0
        self.last_d = 0.0

    def reset(self):
        self.i_term    = 0.0
        self.prev_meas = 0.0
        self.prev_err  = 0.0
        self.d_filt    = 0.0
        self.last_out  = 0.0
        self.first_run = True

    def set_gains(self, kp, ki, kd):
        # 与 C 版一致：改 Ki 时按比例缩放 i_term，保持输出连续
        if self.ki > 1e-9 and ki > 1e-9:
            self.i_term *= (ki / self.ki)
        elif ki <= 1e-9:
            self.i_term = 0.0
        self.kp = kp
        self.ki = ki
        self.kd = kd

    def set_limits(self, out_lim_abs, i_lim_abs):
        if out_lim_abs < 0.0: out_lim_abs = -out_lim_abs
        if i_lim_abs   < 0.0: i_lim_abs   = -i_lim_abs
        self.out_max = out_lim_abs
        self.out_min = -out_lim_abs
        self.i_max   = i_lim_abs
        self.i_term  = _clamp(self.i_term, -self.i_max, self.i_max)

    def update(self, setpoint, measurement, dt):
        if not self.enable:
            self.reset()
            return 0.0

        if dt < 1e-6:
            dt = 1e-6

        err = setpoint - measurement

        # P 项
        p_term = self.kp * err

        # D 项
        if self.first_run:
            d_raw = 0.0
            self.d_filt = 0.0
            self.prev_meas = measurement
            self.prev_err  = err
            self.first_run = False
        else:
            if self.d_on_meas:
                d_input = -(measurement - self.prev_meas) / dt
            else:
                d_input = (err - self.prev_err) / dt
            d_raw = self.kd * d_input
            self.d_filt += self.d_lpf_alpha * (d_raw - self.d_filt)

        self.prev_meas = measurement
        self.prev_err  = err

        # I 项（带死区 + 限幅）
        if self.dead_zone <= 0.0 or err > self.dead_zone or err < -self.dead_zone:
            self.i_term += self.ki * err * dt
            self.i_term  = _clamp(self.i_term, -self.i_max, self.i_max)

        # 合成
        out = p_term + self.i_term + self.d_filt

        # Clamp anti-windup（与 C 版完全相同的判定）
        if out > self.out_max:
            if self.ki * err > 0.0:
                self.i_term -= self.ki * err * dt
                self.i_term  = _clamp(self.i_term, -self.i_max, self.i_max)
            out = self.out_max
        elif out < self.out_min:
            if self.ki * err < 0.0:
                self.i_term -= self.ki * err * dt
                self.i_term  = _clamp(self.i_term, -self.i_max, self.i_max)
            out = self.out_min

        # 记录分量（绘图用）
        self.last_p   = p_term
        self.last_i   = self.i_term
        self.last_d   = self.d_filt
        self.last_out = out
        return out
