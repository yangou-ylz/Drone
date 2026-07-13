#ifndef __USER_TASK_H
#define __USER_TASK_H

#include "SysConfig.h"

// 0xA0日志测试开关：1=使能，0=关闭
#define LOG_TEST_EN 0
// UserTask运行在50Hz，25表示每500ms发送一次
#define LOG_TEST_TICKS 25

// RC通道诊断开关：1=使能，0=关闭
// 仅在通道状态切换时发送绿色LOG，不周期刷屏
#define RC_DIAG_EN 1

// 全通道识别模式（地面安全识别）
// 1: 启用后只做通道识别日志，不执行CH6一键起飞/任务逻辑
#define RC_IDENTIFY_SAFE_MODE 0
// 1: 打印CH1~CH10所有通道变化日志
#define RC_DIAG_ALL_CHANNELS 1
// 通道值变化阈值（单位: PWM计数）
#define RC_DIAG_DELTA_TH 12
// 全通道快照日志（用于排查“拨动但未触发变化日志”的通道）
#define RC_DIAG_SNAPSHOT_EN 0
#define RC_DIAG_SNAPSHOT_TICKS 25

// PID地面自测开关：1=使能，0=关闭
// CH6拨到最高档(>1700)时触发一次，仿真位置→速度PID环，每100ms打一条LOG
// 所有输出走String_Info_Send→上位机，不影响任何飞行控制
#define PID_TEST_EN 1

// PID观测输入源选择（半实物）
// 0: 纯模型（旧方案，s_fake_meas由out积分）
// 1: 离线回放（固定数组回放观测x）
// 2: 真实光流速度（使用IMU速度fc_vel_x积分为观测x）
// 3: 混合半实物（在线vx观测 + 虚拟被控对象，可不飞判收敛）
#define PID_OBS_MODE 2

// PID调参档位
// 0: 更稳（小超调）  1: 更快（强起步）
#define PID_TUNE_PROFILE 0

// 真实环境任务目标与安全限幅
#define PID_TARGET_X_CM 50.0f
#define PID_TARGET_Y_CM 50.0f
#define PID_TARGET_Z_CM 0.0f

#if (PID_TUNE_PROFILE == 0)
#define PID_VEL_LIMIT_CMPS 25.0f
#define PID_KP 1.10f
#define PID_KI 0.0043f
#define PID_KD 0.03f
#else
#define PID_VEL_LIMIT_CMPS 30.0f
#define PID_KP 1.35f
#define PID_KI 0.0043f
#define PID_KD 0.03f
#endif

// 实飞收敛判定阈值（在线观测含噪声/漂移，阈值不宜过严）
#define PID_DONE_ERR_CM 2.0f
#define PID_DONE_OUT_CMPS 5.0f
#define PID_DONE_HOLD_TICKS 25u

// PID任务前置高度稳定阶段（50Hz）
// 先锁定当前高度并保持稳定，再启动X轴积分与PID，降低高度漂移干扰
#define PID_ALT_PREHOLD_EN 1
#define PID_ALT_STABLE_BAND_CM 8.0f
#define PID_ALT_STABLE_TICKS 50u
#define PID_ALT_PREHOLD_TIMEOUT_TICKS 400u

// 真实光流速度模式参数：obs += vel * dt * scale（按轴独立标定）
// 现阶段实测X/Y目标50cm时实际约30cm，先将X/Y scale调到0.90后再微调
#define PID_OBS_VX_SCALE_X 0.90f
#define PID_OBS_VX_SCALE_Y 0.90f
#define PID_OBS_VX_SCALE_Z 1.00f
#define PID_OBS_VX_BIAS_CMPS 0.0f

// 混合半实物模式参数（PID_OBS_MODE=3）
// x_obs = W_REAL * x_online + (1-W_REAL) * x_virtual
// x_virtual由控制输出积分得到，用于不飞时形成闭环可收敛特性
#define PID_OBS_HYB_W_REAL 0.35f
#define PID_OBS_HYB_VIRTUAL_GAIN 0.8f

void UserTask_OneKeyCmd(void);

// =====================================================================
// PID3D — 三轴联合位置控制配置
// 三个独立PID(x/y/z)同时运行，各自参数，输出vx/vy/vz合成后一帧发送
// 主开关 PID3D_EN=0 时整段代码不编译；=1 时由 CH6 高档(>1700)触发
// 注意：PID3D_EN=1 时必须同时保持 PID_TEST_EN=1（共用底层辅助函数）
// =====================================================================

// 主开关：0=整段代码不编译，1=使能
#define PID3D_EN 1

// 目标坐标（单位 cm，增量模式=相对任务启动时的观测值，初始均为0）
// CH6 → X 单轴任务：使用 GOAL_X_CM，GOAL_Y/Z 此时强制为 0
// CH10 → Y 单轴任务：使用 GOAL_Y_CM，GOAL_X/Z 此时强制为 0
// CH7 → Z 单轴任务（暂仍走 pid_ground_test_task_yz 单轴函数，未接入PID3D）
#define PID3D_GOAL_X_CM 50.0f
#define PID3D_GOAL_Y_CM 50.0f
#define PID3D_GOAL_Z_CM 0.0f

// 各轴单轴速度上限（cm/s）
#define PID3D_VEL_X_CMPS 25.0f
#define PID3D_VEL_Y_CMPS 25.0f
#define PID3D_VEL_Z_CMPS 25.0f
// 三轴合速度上限（cm/s）：超出时等比缩放各轴
#define PID3D_VEL_TOTAL_CMPS 30.0f

// 到位判定
#define PID3D_ARRIVE_ERR_CM 5.0f    // 三轴误差均小于此值才算到位
#define PID3D_ARRIVE_HOLD_TICKS 25u // 连续25tick(0.5s)保持到位才确认

// 超时保护（50Hz，1500tick=20s）：超时后停止输出
#define PID3D_TIMEOUT_TICKS 1000

// 前置高度稳定阶段（启动PID前先等高度稳定，减少高度漂移干扰）
#define PID3D_ALT_PREHOLD_EN 1
#define PID3D_ALT_STABLE_BAND_CM 8.0f        // 高度误差在此范围内视为稳定
#define PID3D_ALT_STABLE_TICKS 50u           // 连续稳定50tick(1s)才启动PID
#define PID3D_ALT_PREHOLD_TIMEOUT_TICKS 400u // 等待超时8s则放弃任务

// 各轴独立PID参数（飞行验证后按轴分别调整，初始沿用单轴验证结果）
#define PID3D_KP_X 1.10f
#define PID3D_KI_X 0.0043f
#define PID3D_KD_X 0.03f

#define PID3D_KP_Y 1.10f
#define PID3D_KI_Y 0.0043f
#define PID3D_KD_Y 0.03f

#define PID3D_KP_Z 1.10f
#define PID3D_KI_Z 0.0043f
#define PID3D_KD_Z 0.03f

// 各轴速度观测缩放（obs += fc_vel * dt * scale）
// 沿用单轴飞行验证标定值，后续按轴独立标定
#define PID3D_SCALE_X 0.90f
#define PID3D_SCALE_Y 1.30f // Y轴超调严重(goal50实飞75)，放大obs让PID提前减速
#define PID3D_SCALE_Z 1.00f

// 各轴观测模式（各轴独立配置）
// 2 = 速度积分（用 fc_vel 积分，飞行验证可用）
// 3 = 直接读0x08位置帧（已验证有方向耦合问题，禁用）
#define PID3D_OBS_X_MODE 2
#define PID3D_OBS_Y_MODE 2
#define PID3D_OBS_Z_MODE 2

// =====================================================================
// 串扰开环补偿（方案A）：抵消 X 飞行时 Y 方向的系统性漂移
// 现象：vx=+25 cm/s 飞 2s 后 Y 正方向漂 ~12cm（每次 X=50 任务漂 ~12cm）
// 原理：在 PID 输出 vy 上叠加 (vx * GAIN)，与 PID 反馈解耦的开环修正
// 调参：先用 -0.10f 试飞，若残留正漂调到 -0.15f；若反方向漂调到 -0.05f
// 0 = 关闭补偿
// =====================================================================
#define PID3D_VY_XCOUPLE_GAIN -0.17f // vy_out += vx_out * GAIN  X任务y残漂从12→5cm，再加力
#define PID3D_VX_YCOUPLE_GAIN 0.0f   // 预留：Y 飞行对 X 的耦合（暂未观测到）

#endif
