# 地面实时PID日志测试任务



## 任务用途

- 目标：不让无人机起飞，仅在地面做 PID 算法与日志链路联调。

- 触发方式：CH6（AUX2）拨到 `1700~2200` 区间。

- 行为：持续向 IMU 发送 `0xA0` 字符串日志帧，在地面站实时可见。

- 安全性：该任务不下发起飞/降落指令，不改飞控运动指令，仅做仿真计算和日志输出。



## 代码位置

- 任务入口：`FcSrc/User_Task.c` 中 `UserTask_OneKeyCmd()`

- 测试任务：`FcSrc/User_Task.c` 中 `pid_ground_test_task()`

- 触发开关：`FcSrc/User_Task.h` 中 `PID_TEST_EN`



## 运行逻辑

- CH6 进入 `1700~2200`：

  1. 初始化 PID（当前参数：`kp=1.27, ki=0.0043, kd=0.03`）

  2. 进入运行态，100ms 周期输出实时日志：`T:xxx m:... o:...`

  3. 收敛后进入保持态，500ms 周期输出：`PID HOLD DONE m:...`

  4. 超时后进入保持态，500ms 周期输出：`PID HOLD TIMEOUT m:...`

- CH6 离开该区间：状态复位；再次拨入会重新开始一轮。



## 测试步骤

1. 编译并烧录，断电重启飞控。

2. 上位机连接日志窗口（确保能显示 `0xA0` 字符串）。

3. 保持 CH6 在中位，确认无 PID 连续日志刷屏。

4. 将 CH6 拨到高位（`1700~2200`），观察日志：

   - 先出现一次参数日志：`PID TEST kp=1.27 ki=0.0043 kd=0.03`

   - 随后持续出现 `T:... m:... o:...`（约每100ms）

   - 收敛后持续出现 `PID HOLD DONE m:...`（约每500ms）

5. 将 CH6 拨回中位，再拨到高位，确认能重新触发完整流程。



## 正常判据

- 触发后 0.2s 内出现 `PID TEST ...`。

- 运行态日志连续、无长时间中断（>1s）。

- `m` 值逐步趋近 5.00 附近，`o` 值逐步减小。

- 收敛后出现 `PID HOLD DONE ...` 心跳；若超时则出现 `PID HOLD TIMEOUT ...`。

- 回中位停止，重新拨高可重复触发。



## 定点模式遥控速度控制（Mode2）



### 实现

- 文件：`FcSrc/ANO_LX.c`

- 位置：`RC_Data_Task()` 的实时控制帧赋值区。

- 行为：

  - 仅当 CH5 切到 Mode2（定点）时启用水平速度映射。

  - CH1(roll) -> `rt_tar.st_data.vel_x`

  - CH2(pitch) -> `rt_tar.st_data.vel_y`

  - CH4(yaw) 继续走原有 `yaw_dps` 赋值。

  - 非 Mode2 时强制 `vel_x=0, vel_y=0`。

- 发送链路：继续使用已有 `rt_tar` 全局和 `dt.fun[0x41].WTS=1`，通过既有 0x41 封装发送。



### 操作

1. 上电后确认遥控信号正常。

2. CH5 切到 Mode2（定点）。

3. 小幅拨动 CH1、CH2，观察无人机水平速度响应。

4. CH4 检查偏航响应是否保持原有逻辑。

5. CH5 切出 Mode2，确认水平速度指令停止。



### 正常现象

- Mode2 下：

  - CH1 拨动时出现 X 向速度动作；

  - CH2 拨动时出现 Y 向速度动作；

  - CH4 拨动时偏航正常。

- 非 Mode2 下：

  - 无水平速度遥控动作（`vel_x/vel_y` 已清零）。



## 当前状态（2026-05-20）



- PID任务流程已升级为两阶段：

  1. 前置定高稳定阶段（PID ALT HOLD/OK）

  2. X轴位移PID阶段（T:xxxx m:... o:...）

- 本轮验证日志已出现 `PID DONE m:30.78 err:-0.78`，说明流程闭环有效。

- 当前支持档位化调参（`PID_TUNE_PROFILE`）：

  - 0：更稳（小超调）

  - 1：更快（强起步）

- 当前目标位移参数为 50cm（`PID_TARGET_X_CM=50.0f`）。



## 日志字段释义（飞前/飞后复盘用）



- `PID TEST OBS=online_vx`

  - 含义：当前观测源模式。online_vx 表示用飞控回传速度积分得到 X 观测。



- `CFG p0 t50.00 v25.00 kp1.10 ki0.0043 kd0.03 sx1.55`

  - 含义：任务启动时参数摘要（新增）。

  - `p0/p1`：调参档位（0稳、1快）。

  - `t`：目标位移，单位 cm。

  - `v`：速度命令限幅，单位 cm/s。

  - `kp/ki/kd`：PID三参数。

  - `sx`：在线观测比例系数（速度积分缩放）。



- `PID ALT HOLD h:138.00 ref:139.00`

  - 含义：前置定高阶段进行中。

  - `h`：当前高度（cm，来自通用测距/光流高度）。

  - `ref`：任务开始时锁定的参考高度（cm）。



- `PID ALT OK h:140.00`

  - 含义：高度已在阈值内连续稳定，开始进入X轴PID阶段。



- `T:0065 m:28.58 o:1.72`

  - 含义：X轴PID周期日志（约100ms一条）。

  - `T`：PID运行tick（50Hz基准）。

  - `m`：当前X观测位移（cm）。

  - `o`：当前PID输出速度指令（cm/s）。



- `PID DONE m:30.78 err:-0.78`

  - 含义：收敛完成。

  - `m`：完成时位移（cm）。

  - `err`：目标误差（cm）。



- `PID TIMEOUT m:xx.xx`

  - 含义：在限定时间窗内未满足收敛条件，任务超时结束。



- `PID HOLD DONE ...` / `PID HOLD TIMEOUT ...`

  - 含义：结束后保持心跳日志，便于地面站确认当前终态。



## 全通道识别模式（地面安全）



### 目标



- 尽可能识别遥控器所有可用通道（含双摇杆与多个拨杆）。

- 拨动任一通道时实时输出日志，日志包含“代码中定义的通道名 + 当前通道数值 + 角色说明”。

- 仅用于地面识别，不执行一键起飞/任务动作。



### 开关与参数



- 文件：`FcSrc/User_Task.h`

- 相关宏：

  - `RC_DIAG_EN`：总诊断开关，1=启用。

  - `RC_IDENTIFY_SAFE_MODE`：地面安全识别模式，1=只识别不执行任务。

  - `RC_DIAG_ALL_CHANNELS`：全通道识别开关，1=CH1~CH10全部识别。

  - `RC_DIAG_DELTA_TH`：变化阈值（PWM计数），超过阈值才打印，避免刷屏。



### 通道命名映射（代码内）



- `CH1_ROL` -> `roll`

- `CH2_PIT` -> `pitch`

- `CH3_THR` -> `throttle`

- `CH4_YAW` -> `yaw`

- `CH5_AUX1` -> `mode`

- `CH6_AUX2` -> `task`

- `CH7_AUX3` -> `aux3`

- `CH8_AUX4` -> `aux4`

- `CH9_AUX5` -> `aux5`

- `CH10_AUX6` -> `aux6`



### 日志格式说明



- 示例：`CH7_AUX3:1988 -> aux3`

- 字段含义：

  - `CH7_AUX3`：代码通道名。

  - `1988`：当前通道原始值（PWM计数）。

  - `aux3`：当前通道角色标签（便于识别用途）。



### 安全行为（重要）



- 当 `RC_IDENTIFY_SAFE_MODE=1` 时：

  - `UserTask_OneKeyCmd()` 会提前返回。

  - CH6 的一键起飞/任务流程不会执行。

  - PID任务输出会被立即清零，避免地面误动作。



### 地面识别操作建议



1. 上电后保持桨叶安全（建议拆桨）。

2. 确认模式在地面安全状态，观察是否开始输出通道日志。

3. 每次只拨动一个开关或一个摇杆方向，记录“物理拨杆 -> 通道名/数值变化”。

4. 识别完成后整理表格，作为后续任务编排依据。



### 识别完成后恢复飞行任务



1. 将 `RC_IDENTIFY_SAFE_MODE` 改回 `0`。

2. 重新编译下载。

3. 地面先验证 CH6 触发逻辑恢复，再进行低风险实飞。



## 按实测误差调参指南（已知实际飞行距离时）



### 核心思路



- 先校准“观测比例”（scale），再调控制器（限速和PID）。

- 原因：如果观测尺度不准，PID看到的位移就不是真实位移，后续调Kp/Ki/Kd会被误导。



### 第一步：用实测距离反推观测比例



已知：

- 目标位移：`D_target`（如 50cm）

- 日志完成位移：`m_done`（如 `PID DONE m:51.24`）

- 实际位移：`D_real`（卷尺实测，如 30cm）



计算比例系数：



$$k=\frac{D_{real}}{m_{done}}$$



更新该轴观测scale：



$$scale_{new}=scale_{old}\times k$$



示例：

- `scale_old=1.55`

- `m_done=51.24`

- `D_real=30`

- `k=30/51.24≈0.585`

- `scale_new≈1.55×0.585≈0.91`



说明：

- X轴用 `PID_OBS_VX_SCALE_X`

- Y轴用 `PID_OBS_VX_SCALE_Y`

- Z轴用 `PID_OBS_VX_SCALE_Z`

- 三个轴应分别标定，不建议共用一个scale。



### 第二步：看动态形态再调控制参数



#### 1) 速度限幅 `PID_VEL_LIMIT_CMPS`

- 作用：限制最大输出速度，直接决定“快/稳”风格。

- 调法：

  - 过冲大、动作猛：减小（如 25 -> 22）

  - 响应慢、拖尾长：增大（如 25 -> 28）



#### 2) 比例项 `PID_KP`

- 作用：按误差立即输出，主要影响响应速度。

- 调法：

  - 到目标太慢：小幅增大（每次 +0.05）

  - 过冲明显/来回摆：小幅减小（每次 -0.05）



#### 3) 积分项 `PID_KI`

- 作用：消除稳态残差（长期差一点到不了）。

- 调法：

  - 长期有固定偏差：小幅增大（每次 +0.001）

  - 容易慢性过冲/回不来：减小（每次 -0.001）



#### 4) 微分项 `PID_KD`

- 作用：抑制过冲、增加阻尼。

- 调法：

  - 过冲大：小幅增大（每次 +0.005）

  - 动作发抖、噪声敏感：减小（每次 -0.005）



### 第三步：收敛判据只在“控制已稳定”后再微调



- `PID_DONE_ERR_CM`：允许误差窗（cm）

- `PID_DONE_OUT_CMPS`：允许输出窗（cm/s）

- `PID_DONE_HOLD_TICKS`：持续满足窗口的时间



建议：

- 先把“真实位移=目标位移”校准好，再缩紧判据。

- 如果判据太严会频繁 `TIMEOUT`；太松会过早 `DONE`。



### 推荐调参顺序（每轴独立）



1. 固定 `PID_TARGET_*_CM`，跑 2~3 次同轴测试。

2. 用实测与 `m_done` 计算并更新该轴 `scale`。

3. 再调 `PID_VEL_LIMIT_CMPS` 与 `PID_KP` 到满意动态。

4. 最后微调 `KI/KD` 与 `DONE` 判据。



### 每次改动建议



- 一次只改 1 个参数。

- 每次改动后至少飞 2 次取平均。

- 保留日志中的三类关键行用于复盘：

  - `CFG ... sx/sy/sz ...`

  - `T:xxxx ...`

  - `PID DONE ...` 或 `PID TIMEOUT ...`



---



## 波形自动分析工具



### 工具位置



- 脚本：`wave/analyze_wave.py`

- 输入：`wave/` 目录下所有 `*.csv`（匿名上位机录波导出）

- 输出：`wave/out/` 目录



### 使用方法



```

cd wave

python analyze_wave.py

```



把上位机录的 CSV 放进 `wave/` 目录，一条命令全自动处理，无需任何参数。  

依赖：`pip install pandas matplotlib scipy`（scipy 用于 FFT/频谱，若缺失则自动跳过频谱分析）。



### 输出目录结构



```

wave/out/

  ├─ <文件名>/

  │    ├─ basic/          总览图、姿态、IMU、高度波形

  │    ├─ fft/            ACC/GYR 功率谱密度图 + 主峰频率列表

  │    ├─ spectrogram/    时频图（振动随时间变化）

  │    ├─ distribution/   各通道分布直方图

  │    ├─ pid/            自动检测阶跃响应，估算 rise/overshoot/settle

  │    ├─ coupling/       轴间互相关 Pearson 柱状图

  │    ├─ anomaly/        异常事件清单（突变/卡死/离群）

  │    ├─ summary.txt     完整文字报告（告警+调参建议+统计）

  │    └─ metrics.json    机器可读指标（可用于多版本回归对比）

  ├─ _compare_summary.csv  多文件横向指标汇总

  └─ _compare_overview.png 多文件对比柱状图

```



### 分析方法说明



#### 1. 总览图（basic/overview.png）

- 三行：姿态角（ROL/PIT/YAW）、加速度（X/Y/Z）、融合高度 vs 气压高度。

- 橙色背景区域 = 自动检测到的任务活动段（静止准备段不算）。

- 看什么：

  - 姿态波动是否在合理范围（±5° 以内为优）。

  - 高度是否在任务期间保持稳定（无明显上升/下降趋势）。

  - 加速度是否有明显毛刺（突然大幅冲击 → 碰撞/控制振荡）。



#### 2. PSD 频谱（fft/psd_acc.png、psd_gyr.png）

- X 轴：频率（Hz），Y 轴：功率谱密度（对数坐标）。

- 看什么：

  - 是否有尖峰（电机转频/桨叶谐波）。能量/中位比 >6× 时自动告警并建议加 notch 滤波器。

  - 健康状态：频谱在低频平缓衰落，无明显尖峰。

  - 典型问题频率：

    - ~10-30Hz 尖峰 → 电机振动（当前已检测到 19.3Hz）。

    - ~1-3Hz 能量高 → 飞行机动/低频晃动。

- 调参依据：如某频率尖峰能量极高，在飞控陀螺 notch 参数中配置对应频率。



#### 3. 时频图（spectrogram/）

- 热图：横轴时间、纵轴频率、颜色亮度为能量。

- 看什么：振动频率是否在任务期间突然变化（如起飞前后电机频率变化，或某时刻发生撞击）。



#### 4. PID 阶跃响应（pid/step_*.png）

- 自动找信号最大阶跃处，计算标准响应指标：



| 指标 | 含义 | 正常参考 |

|------|------|---------|

| `rise_s` | 上升时间 10%→90% | <0.5s |

| `overshoot_pct` | 超调百分比 | <20% |

| `settle_s` | 稳态时间 ±5% | <2s |

| `ss_err` | 稳态残差 | 接近 0 |



- 调参建议自动写入 `summary.txt`：

  - 超调大 → 减小 `PID_KP` 或增大 `PID_KD`

  - 响应慢 → 增大 `PID_KP`

  - 稳态时间长 → 增大 `PID_KI` 或 `PID_KD`



#### 5. 轴间耦合（coupling/pearson.png）

- Pearson 相关系数：|r| < 0.5 正常，|r| > 0.7 告警。

- 高耦合表示某轴动作会带动另一轴，需检查机架对称性或控制混合矩阵。



#### 6. 分布直方图（distribution/）

- 看通道数值的统计分布是否为正态/对称。

- 双峰 → 飞控在两个状态间切换。

- 长尾 → 存在偶发冲击。

- 橙色虚线 = ±3σ 边界，超出点为离群。



#### 7. 静态零偏与漂移（drift）

- 任务开始前的静止段自动提取。

- 陀螺零偏 `bias`：绝对值 >5 建议重新校准 IMU。

- 静态高度漂移率 `alt_static_drift_per_s`：>5cm/s 说明气压计受地面气流干扰。



#### 8. 异常事件（anomaly/events.txt）

- 自动标记三类异常：

  - `jump`：单帧差分 >6σ（电气毛刺/碰撞/控制暴走）。

  - 连续不变平台：>0.3s 数值不更新（传感器卡死/通信丢帧）。

  - 3σ 离群率（`*_outlier_3s_pct`）：占比 >5% 时值得关注。



### 如何利用报告调参



#### 调参流程（配合 summary.txt）



1. **先看"异常告警"**：有告警先解决硬件/配置问题，再调 PID。

2. **看频谱主峰**：若存在高比率尖峰，优先在飞控中加 notch，消除振动再调 PID。

3. **看 PID 阶跃响应**：

   - 超调 >20% → 减 `KP`，增 `KD`。

   - rise >1s → 增 `KP` 或放宽 `VEL_LIMIT`。

   - settle >3s → 增 `KI`。

4. **看高度漂移**：`alt_drift_cm` 大说明 Z 轴保高不稳，检查 thr 固定逻辑。

5. **横向对比**：`_compare_overview.png` 一眼看多次飞行哪次最稳，`_compare_summary.csv` 可用 Excel 排序筛选最优参数组。



#### 单次迭代流程



```

飞行/录波

    ↓

python analyze_wave.py

    ↓

看 summary.txt 告警与建议

    ↓

改 1 个参数（User_Task.h）

    ↓

重新编译烧录 → 再飞一次

```



### 脚本顶部可配置项



| 参数 | 含义 | 默认 |

|------|------|------|

| `SAMPLE_RATE_HZ` | 录波采样率 | 200 |

| `ENABLE_FFT` | 开启频谱分析 | True |

| `ENABLE_SPECTROGRAM` | 开启时频图 | True |

| `ENABLE_PID_RESPONSE` | 开启阶跃响应 | True |

| `TH_ATT_DEG` | 姿态峰值告警阈值(°) | 15 |

| `TH_ALT_DRIFT_CM` | 高度漂移告警(cm) | 30 |

| `TH_NOTCH_PEAK_RATIO` | 频谱尖峰告警比率 | 6.0 |



要关掉某项分析（如样本少不适合跑 FFT），在脚本顶部把对应 `ENABLE_xxx` 改为 `False` 即可。


---

## 阶段4：分轴飞行验证 + X+Y 联动测试（2026-05-24）

### 4.1 遥控器手感优化（已验证）

**文件**：`FcSrc/ANO_LX.c`

- `MAX_VELOCITY` 由 100 改为 **25 cm/s**（满杆=25，半杆≈12，更适合室内）
- CH1/CH2 死区 40 → **80**（消除粘杆抖动），补偿系数 0.00217 → 0.00238 保持线性
- 油门 CH3 **不缩放**，沿用 `MAX_VER_VEL_P=300` / `MAX_VER_VEL_N=200`
- vx 方向最终取负：`vel_x = -tmp_ch_dz[ch_1_rol] * 0.00238f * MAX_VELOCITY`（实测定点模式下 vx 与摇杆反向，加负号才同向）

### 4.2 拨杆触发架构

| 通道 | 阈值 | 触发任务 | 默认目标 |
|------|------|---------|---------|
| CH5_AUX1 | 1200~1700 | 进入定点模式（PID 任务前置条件） | - |
| CH6_AUX2 | >1700 && <2200 | **X+Y 联动**（axis_mode=4） | x=50, y=50 |
| CH10_AUX6 | >1700 && <2200 | 仅 Y 轴（axis_mode=2） | y=50 |
| CH7_AUX3 | >1700 && <2200 | 仅 Z 轴 | z=变量 |

- `pid_active_axis` 互斥状态机（0/1/2/3），**多杆同时拨高会被拒绝**并红字 LOG `PID multi-axis abort`
- 触发前置：必须 mode2，且 `RC_IDENTIFY_SAFE_MODE=0`

### 4.3 `pid_3d_task` axis_mode 扩展

位于 `FcSrc/User_Task.c::pid_3d_task(u8 *step, u8 axis_mode)`：

```c
const float goal_x = (axis_mode==0u || axis_mode==1u || axis_mode==4u) ? Uplink_GetGoalX_Cm() : 0.0f;
const float goal_y = (axis_mode==0u || axis_mode==2u || axis_mode==4u) ? Uplink_GetGoalY_Cm() : 0.0f;
const float goal_z = (axis_mode==0u || axis_mode==3u) ? Uplink_GetGoalZ_Cm() : 0.0f;
```

- `0` = 三轴 / `1` = 仅X / `2` = 仅Y / `3` = 仅Z / **`4` = X+Y（Z 悬停）**
- 合速度 `PID3D_VEL_TOTAL_CMPS=30` 限制：X+Y 同步满速时 vx=vy ≈ 21 cm/s（√2 缩放）

### 4.4 关键调参（迭代记录）

| 参数 | 初值 | 现值 | 调整原因 |
|------|------|------|---------|
| `PID3D_SCALE_Y` | 0.90 | **1.30** | Y=50 任务实飞 75 cm，超调 +25；scale 放大让 obs 更早达 goal、提前刹车 |
| `PID3D_VY_XCOUPLE_GAIN` | -0.10 | **-0.17** | X=50 任务 Y 残漂 +5cm（初版 +12 用 -0.10 减到 +5），线性外推到 0 |
| `PID3D_GOAL_Y_CM` | 0 | **50** | CH10 Y 任务默认目标 |
| `RC_IDENTIFY_SAFE_MODE` | 1 | **0** | =1 时 `UserTask_OneKeyCmd` 早 return，所有触发失效 |

### 4.5 已知物理现象（重要）

- **Y 轴超调**：纯 Y 任务存在严重惯性超调（goal 50 → 实飞 75），说明 PID 减速段太短或电机响应滞后。当前靠 `SCALE_Y` 放大 obs 缓解，根因未除（可考虑降 `PID3D_VEL_Y_CMPS=25` 或加 D 项）
- **X→Y 串扰**：纯 X 飞行时 Y 正向漂移 ~12 cm，开环补偿 `vy += vx * (-0.17)` 修正。物理来源推测为机架/电机不对称或重心偏移
- **0x08 位置帧不可用于闭环**：静止时漂移 ~5 cm，确认 `PID3D_OBS_X/Y_MODE=2`（速度积分）作为唯一可用反馈

### 4.6 X+Y 联动测试流程（CH6 当前行为）

1. 烧录后断电重启，遥控器先把 CH6/CH10/CH7 全部回中位
2. 起飞 → CH5 切到 Mode2（定点）
3. **CH6 拨高位** → 同时触发 X=50 & Y=50
   - 期望：合速度限幅在 30 cm/s，单轴满速 ≈ 21 cm/s
   - 期望终点：(50, 50)，允许 ±10 cm 偏差
   - 串扰补偿仍生效（`VY_XCOUPLE_GAIN=-0.17`）
4. 飞完 CH6 回中复位
5. 若 Y 仍超调 ≥ 60，下一轮把 `PID3D_SCALE_Y` 从 1.30 → 1.45
6. 若 Y 反到 30 左右，说明耦合补偿过量，把 `VY_XCOUPLE_GAIN` 改为 -0.08

### 4.7 踩坑

- **[2026-05-24] CH6/CH10 单独拨高都不触发任务**
  - 原因：`RC_IDENTIFY_SAFE_MODE=1` 导致 `UserTask_OneKeyCmd` 早 return（地面通道识别模式）
  - 解决：改回 0
  - **教训**：地面识别开关用完必关，否则所有 PID 任务静默失效，无任何日志提示

- **[2026-05-24] vx 方向反复确认两次**
  - ANO_LX.c 内 `tmp_ch_dz` 计算用 `ch-1500`（左推杆为负值），定点模式下 IMU 期望"右推=vx+"，需取负
  - **教训**：方向问题必须以实飞为准，注释要写明结论

---

## 阶段5：上行命令链路（PC → 飞控 自定义CMD）

> 目标：在不依赖匿名上位机录波/调参界面的前提下，由 PC 直接发自定义协议帧调参、调试。
> 协议详见 [数据帧.md](数据帧.md)。

### 5.1 总体架构

```
PC (Python) ──┐
              │ 0xAA dest CMD LEN DATA SC AC
              ▼
        匿名数传 COM11 (USB-CDC, 500000baud)
              │ 2.4G
              ▼
        凌霄 IMU (0x60) ── 透传 dest=0xFF/0x61 ──? STM32 飞控
                                                        │
                       Drv_Uart RX → ANO_DT_LX::Anl() ──┤
                       SC/AC 校验 → Uplink_Cmd_Dispatch │
                                                        ▼
                                             0xF1 链路回显 / 0xF2 写参数
                                                        │
                       Uplink_Cmd_Tick() @50Hz 组 0xA0 ──┤
                                                        ▼
                          String_Info_Send → UART → IMU → 2.4G → PC
```

- 关键文件：
  - `FcSrc/Uplink_Cmd.h/.c`：新增模块，承载所有 CMD 解析 + 异步回显队列
  - `FcSrc/ANO_DT_LX.c`：在主分发处增 `0xF1/0xF2` 两个分支转给 `Uplink_Cmd_Dispatch`
  - `FcSrc/User_Task.c::pid_3d_task`：目标坐标由宏改为 `Uplink_GetGoalX/Y/Z_Cm()` getter
  - `groundTest/send_f1.py`、`groundTest/send_param.py`：地面发帧脚本
- 私有 CMD 空间：`0xFx` 全部预留给本项目；**禁用 0xE2**（凌霄 CK_Back 协议占用，会冲突）

### 5.2 阶段1：0xF1 链路验证帧（? 已硬件验证）

**用途**：只发不改状态，用于验证 PC?数传?IMU?飞控 双向链路通畅、不丢包率统计。

| 字段 | 字节 | 内容 |
|------|------|------|
| DATA[0..1] | s16 LE | X（任意 int16） |
| DATA[2..3] | s16 LE | Y（任意 int16） |

- 飞控行为：仅缓存 + 经异步队列回显 `0xA0` 字符串 `F1: X=.. Y=..`
- 实测：500000 baud 下 2Hz 发送，单帧到达率 **88%**（数传 2.4G 物理层丢包）
- 工具：`groundTest/send_f1.py --port COM11 --x 1234 --y -4562 --listen`

### 5.3 阶段2：0xF2 参数写入帧（? 已硬件验证，2026-05-24）

**用途**：运行时改 PID3D 目标坐标，免烧录、免遥控器。

| 字段 | 字节 | 内容 |
|------|------|------|
| DATA[0] | u8 | param_id（白名单见下） |
| DATA[1..4] | float LE | value（cm） |

**白名单与限幅**（`FcSrc/Uplink_Cmd.c::param_apply`）：

| param_id | 写入静态 RAM | 对应原宏 | 限幅 |
|----------|------------|---------|------|
| `0x01` | `s_goal_x_cm` | `PID3D_GOAL_X_CM` | ±500 cm |
| `0x02` | `s_goal_y_cm` | `PID3D_GOAL_Y_CM` | ±500 cm |
| `0x03` | `s_goal_z_cm` | `PID3D_GOAL_Z_CM` | ±500 cm |
| 其他 | 拒绝 | — | 红字 `Pxx UNK` |

**生效时机（关键）**：

- 在 `pid_3d_task` 的 `step=1` 启动时调用 getter，把 RAM 值拍照锁定为函数内 `const`
- **飞行过程中改 0xF2 不会改变正在跑的任务**，需 CH6 回中位再拨高重启任务
- 断电丢值（不写 Flash）

**回显字符串约定**（飞控 → PC，0xA0）：

| 字符串 | 颜色 | 含义 |
|--------|------|------|
| `P01=30.0` | ? 绿 | 写入成功 |
| `P01=500.0 CLP` | ? 绿 | 越界被限幅 |
| `P09 UNK` | ? 红 | param_id 不在白名单 |
| `3D INIT gx:.. gy:.. gz:..` | ? 绿 | （阶段5扩展点）任务启动快照，待 Layer2 加 |

**硬件验证**（5/5 通过）：

| 用例 | 发送 | 飞控回显 | 结论 |
|------|------|---------|------|
| 1 | id=1 val=30 | `P01=30.0` 绿 | RAM 写入正常 |
| 2 | id=2 val=-50 | `P02=-50.0` 绿 | 负数正常 |
| 3 | id=3 val=80 | `P03=80.0` 绿 | Z 轴正常 |
| 4 | id=1 val=800 | `P01=500.0 CLP` 绿 | 限幅生效 |
| 5 | id=9 val=0 | `P09 UNK` 红 | 白名单生效 |

**最终 RAM 状态**：GOAL_X=33, GOAL_Y=44, GOAL_Z=55

### 5.4 地面工具

| 脚本 | 用途 | 示例 |
|------|------|------|
| `groundTest/send_f1.py` | 阶段1 链路验证 | `python send_f1.py --port COM11 --x 1234 --y -4562 --listen` |
| `groundTest/send_param.py` | 阶段2 写参数 | `python send_param.py --port COM11 --id 1 --value 30 --listen` |
| `groundTest/monitor.py` | 纯监听飞控回显 | `python monitor.py --port COM11` |

- 底层串口：`win_serial.py` 直接 Win32 `CreateFile`，绕开 pyserial 在 Python 3.14 上 `SetCommState` 报 31 的兼容问题
- 单帧丢包率 ~12-20%，**写参数务必加 `--retry 5` 或脚本内重发**

### 5.5 踩坑

- **[初版] 选 CMD=0xE2 冲突**：发出后飞控回 CK_Back 而非自定义响应。查 `ANO_DT_LX.c::L334-345` 确认 0xE2 是凌霄保留帧。改用 `0xF2`（私有空间）解决
- **[初版] 第一次 5 连发只收到 1 条 F2 回显**：是 monitor.py 与 send_param.py 同时打开 COM11 互抢；改为 `send_param.py --listen` 由发送进程自己收，命中率回到 4-5/5
- **[2026-05-24] COM11 突然消失**：匿名上位机V7 后台进程占用 + USB 重枚举。先关上位机进程，再拔插数传即可
- **教训**：CMD 选取前一定先在 `ANO_DT_LX.c` 全文搜对应 `0xXX` 字面量，确认没冲突再用

### 5.6 后续扩展点（未实施）

- **Layer2**：CH6 触发任务时，发一条 `3D INIT gx:.. gy:.. gz:..` 把 getter 拍到的目标点回显出来（便于地面在起飞前确认参数确实生效）
- **新 param_id**：扩 `0x04~0x08` 给 `PID3D_KP/KI/KD/SCALE_*/VEL_LIMIT`，做飞行中调 PID 参数（需考虑飞行中改参数的风险，建议加 mode2/未起飞 守门）
- **Flash 持久化**：现在 RAM 写入断电丢；若后续实现，需重新分配未占用私有帧ID，不得复用已占用的 `0xF1`/`0xF2`/`0xF3`，并需核对 `0xF5` 树莓派位置帧规划（要写 STM32 内部 Flash 扇区）
- **下行参数读回**：后续可另分配未占用读回帧ID → 飞控回 `0xA0` `P01=30.0` 形式，让 PC 主动查询当前值
