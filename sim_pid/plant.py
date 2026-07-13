"""
无人机被控对象模型。

控制链：
  外环 (本仿真测试对象)       内环 (IMU 黑盒，本模型逼近)        物理
  位置PID → vx_cmd  ───────? [一阶速度环 1/(τs+1)] ──? v_actual ──? 位置积分 ──? x

一阶惯性环节假设的物理依据：
  IMU 内部用 PID 让 v_actual 跟踪 v_cmd，整体响应近似一阶。
  τ 越小响应越快（典型 0.15~0.4s 对小四旋翼）。
"""

import numpy as np


class DronePlant:
    def __init__(self, tau=0.20, v_max=80.0, a_max=200.0, noise_std=0.0, seed=42):
        """
        tau       速度环时间常数 (s)
        v_max     物理速度限幅 (cm/s)
        a_max     物理加速度限幅 (cm/s^2)，反映电机/姿态环响应上限
        noise_std 位置测量噪声标准差 (cm)，0=无噪声
        """
        self.tau       = tau
        self.v_max     = v_max
        self.a_max     = a_max
        self.noise_std = noise_std
        self.rng       = np.random.default_rng(seed)
        self.reset()

    def reset(self, x0=0.0, v0=0.0):
        self.x = x0       # 真实位置 (cm)
        self.v = v0       # 真实速度 (cm/s)

    def step(self, v_cmd, dt):
        """单步前进。输入速度指令，返回当前位置（含噪声）。"""
        # 1. 速度指令限幅
        v_cmd = max(-self.v_max, min(self.v_max, v_cmd))

        # 2. 一阶惯性逼近：dv/dt = (v_cmd - v) / tau
        a = (v_cmd - self.v) / self.tau

        # 3. 加速度限幅（电机响应能力）
        a = max(-self.a_max, min(self.a_max, a))

        # 4. 积分更新
        self.v += a * dt
        # 速度物理限幅（电机/电池能力）
        self.v = max(-self.v_max, min(self.v_max, self.v))
        self.x += self.v * dt

        # 5. 测量噪声（模拟摄像头/视觉里程计抖动）
        if self.noise_std > 0.0:
            return self.x + self.rng.normal(0.0, self.noise_std)
        return self.x

    def true_state(self):
        return self.x, self.v
