# PID 闭环仿真测试系统

把 STM32 上的 `Ctrl_PID.c` 算法**逐字段**用 Python 复刻，加上无人机位置-速度环的物理模型，
形成闭环仿真。先在 PC 上把参数调到满意，再把同一组参数搬到 MCU 上烧录，省去飞行调参成本。

## 文件结构

| 文件 | 作用 |
|---|---|
| `pid_core.py` | PID 算法（与 `FcSrc/Ctrl_PID.c` 逐行对应，验证过的 1:1 移植） |
| `plant.py` | 无人机被控对象模型：vx 指令 → IMU 速度环（一阶惯性） → 位置积分 |
| `simulator.py` | 闭环仿真器，输出 numpy 数据 + 性能指标 |
| `analyze.py` | matplotlib 绘图：阶跃响应、误差、PID 分量、参数对比 |
| `config.py` | 所有参数集中（控制频率、限幅、被控对象时间常数） |
| `run.py` | 主入口，一行命令跑单次仿真 |
| `tune.py` | 参数扫描（grid search），自动找最优 Kp/Ki/Kd |

## 快速开始

```powershell
# 1. 安装依赖
pip install numpy matplotlib

# 2. 单次仿真（用 config.py 里的默认参数）
python run.py

# 3. 参数扫描
python tune.py
```

## 与 STM32 的一致性保证

| 维度 | MCU 实际 | Python 仿真 |
|---|---|---|
| 控制周期 | 50 Hz, dt=0.02s | 50 Hz, dt=0.02s |
| 数值精度 | float32 (FPU) | float64，差异 < 1e-6，可忽略 |
| 算法逻辑 | `Ctrl_PID.c` 微分先行 + LPF + Clamp AW | **逐行对应** |
| 输入输出 | float | float |
| 限幅顺序 | i_term clamp → output clamp → anti-windup | 完全一致 |

## 调参后如何同步到 MCU

仿真满意后，把 `config.py` 中的 `KP/KI/KD/OUT_LIM/I_LIM/D_LPF_ALPHA/DEAD_ZONE`
直接复制到 MCU 测试任务的 `Pid_SetGains/Pid_SetLimits/d_lpf_alpha/dead_zone` 调用即可。
