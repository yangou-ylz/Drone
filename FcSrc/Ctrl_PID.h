#ifndef __CTRL_PID_H
#define __CTRL_PID_H

//==引用
#include "SysConfig.h"

//==说明
// 通用单环 PID 控制器
// 特性：
//   1. 微分先行（D-on-Measurement），避免 setpoint 阶跃引起 D 项尖峰
//   2. D 项一阶低通滤波，抑制测量噪声放大
//   3. 积分独立限幅 + Clamp 式 anti-windup，防止积分饱和
//   4. 输出对称限幅
//   5. 死区抑制（|err|<dz 时不累加积分）
//   6. enable 开关：禁用时输出强制为 0，状态自动清零
//   7. 状态与参数分离，运行时调参不破坏内部状态
//
// 使用步骤：
//   1) 定义实例：   _pid_st pid_x;
//   2) 初始化：     Pid_Init(&pid_x);
//   3) 配参数：     Pid_SetGains(&pid_x, kp, ki, kd);
//                  Pid_SetLimits(&pid_x, out_lim, i_lim);
//                  pid_x.d_lpf_alpha = 0.2f;   // 0~1, 越小越平滑
//                  pid_x.dead_zone   = 0.0f;
//                  pid_x.enable      = 1;
//   4) 每个控制周期调用一次：
//        out = Pid_Update(&pid_x, setpoint, measurement, dt);

//==数据声明
typedef struct
{
    // —— 增益 ——
    float kp;
    float ki;
    float kd;

    // —— 限幅 ——
    float out_max; // 输出正向限幅（>=0）
    float out_min; // 输出负向限幅（<=0）
    float i_max;   // 积分项绝对值限幅（>=0）

    // —— 行为参数 ——
    float d_lpf_alpha; // D 项一阶 LPF 系数，范围 (0,1]，1=不滤波
    float dead_zone;   // 误差死区（|err|<dz 时积分冻结）
    u8 d_on_meas;      // 1=微分先行（用测量值），0=用误差。默认 1
    u8 enable;         // 0=禁用，输出强制 0，状态清零

    // —— 运行时状态（外部不要写）——
    float i_term;    // 积分累积（已乘 ki）
    float prev_meas; // 上次测量值（用于微分先行）
    float prev_err;  // 上次误差（用于 d_on_meas=0 时）
    float d_filt;    // 滤波后的 D 项
    float last_out;  // 上次输出（调试用）
    u8 first_run;    // 1=首次调用，跳过 D 项计算
} _pid_st;

//==函数声明
void Pid_Init(_pid_st *pid);
void Pid_Reset(_pid_st *pid);
void Pid_SetGains(_pid_st *pid, float kp, float ki, float kd);
void Pid_SetLimits(_pid_st *pid, float out_lim_abs, float i_lim_abs);
float Pid_Update(_pid_st *pid, float setpoint, float measurement, float dt);

#endif
