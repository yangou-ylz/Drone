//==引用
#include "Ctrl_PID.h"

//==内部工具
static float _clamp(float v, float lo, float hi)
{
    if (v > hi)
        return hi;
    if (v < lo)
        return lo;
    return v;
}

//==实现

// 初始化为安全默认值（禁用状态，所有增益为 0）
void Pid_Init(_pid_st *pid)
{
    if (pid == 0)
        return;

    pid->kp = 0.0f;
    pid->ki = 0.0f;
    pid->kd = 0.0f;

    pid->out_max = 0.0f;
    pid->out_min = 0.0f;
    pid->i_max = 0.0f;

    pid->d_lpf_alpha = 1.0f; // 默认不滤波，由用户按需调小
    pid->dead_zone = 0.0f;
    pid->d_on_meas = 1; // 默认开启微分先行
    pid->enable = 0;    // 默认禁用，需用户显式 enable=1

    Pid_Reset(pid);
}

// 清零所有运行时状态（保留参数）
// 切换飞行模式、解锁瞬间、目标切换时必调
void Pid_Reset(_pid_st *pid)
{
    if (pid == 0)
        return;

    pid->i_term = 0.0f;
    pid->prev_meas = 0.0f;
    pid->prev_err = 0.0f;
    pid->d_filt = 0.0f;
    pid->last_out = 0.0f;
    pid->first_run = 1;
}

// 设置三个增益。Ki 变化时同步缩放已累积的 i_term，避免输出跳变
void Pid_SetGains(_pid_st *pid, float kp, float ki, float kd)
{
    if (pid == 0)
        return;

    // 如果 ki 改变了，按比例重新换算 i_term，保持当前输出连续
    if (pid->ki > 1e-9f && ki > 1e-9f)
    {
        pid->i_term *= (ki / pid->ki);
    }
    else if (ki <= 1e-9f)
    {
        pid->i_term = 0.0f;
    }

    pid->kp = kp;
    pid->ki = ki;
    pid->kd = kd;
}

// 设置对称输出限幅 + 积分限幅
void Pid_SetLimits(_pid_st *pid, float out_lim_abs, float i_lim_abs)
{
    if (pid == 0)
        return;

    if (out_lim_abs < 0.0f)
        out_lim_abs = -out_lim_abs;
    if (i_lim_abs < 0.0f)
        i_lim_abs = -i_lim_abs;

    pid->out_max = out_lim_abs;
    pid->out_min = -out_lim_abs;
    pid->i_max = i_lim_abs;

    // 收紧积分到新限幅内
    pid->i_term = _clamp(pid->i_term, -pid->i_max, pid->i_max);
}

// 单步 PID 计算，dt 单位秒
float Pid_Update(_pid_st *pid, float setpoint, float measurement, float dt)
{
    float err, p_term, d_input, d_raw, out;

    if (pid == 0)
        return 0.0f;

    // 禁用：清零状态并直接返回 0，避免上次状态污染下次启用
    if (pid->enable == 0)
    {
        Pid_Reset(pid);
        return 0.0f;
    }

    // dt 异常保护
    if (dt < 1e-6f)
        dt = 1e-6f;

    err = setpoint - measurement;

    // ---- P 项 ----
    p_term = pid->kp * err;

    // ---- D 项 ----
    if (pid->first_run)
    {
        d_raw = 0.0f;
        pid->d_filt = 0.0f;
        pid->prev_meas = measurement;
        pid->prev_err = err;
        pid->first_run = 0;
    }
    else
    {
        if (pid->d_on_meas)
        {
            // 微分先行：对测量值求导（负号是因为 d(err)/dt = -d(meas)/dt）
            d_input = -(measurement - pid->prev_meas) / dt;
        }
        else
        {
            d_input = (err - pid->prev_err) / dt;
        }

        d_raw = pid->kd * d_input;

        // D 项一阶低通：y[n] = y[n-1] + alpha*(x[n] - y[n-1])
        pid->d_filt += pid->d_lpf_alpha * (d_raw - pid->d_filt);
    }

    pid->prev_meas = measurement;
    pid->prev_err = err;

    // ---- I 项（带死区、anti-windup） ----
    // 死区：误差很小时冻结积分，避免静态偏置导致缓慢漂移
    if (pid->dead_zone <= 0.0f || (err > pid->dead_zone) || (err < -pid->dead_zone))
    {
        pid->i_term += pid->ki * err * dt;
        pid->i_term = _clamp(pid->i_term, -pid->i_max, pid->i_max);
    }

    // ---- 合成 ----
    out = p_term + pid->i_term + pid->d_filt;

    // ---- Clamp anti-windup ----
    // 若输出饱和且积分还在朝饱和方向继续增大，则回退本次积分增量
    if (out > pid->out_max)
    {
        // 输出上饱和：若 i_term 也在增（同号），扣回去
        if (pid->ki * err > 0.0f)
        {
            pid->i_term -= pid->ki * err * dt;
            pid->i_term = _clamp(pid->i_term, -pid->i_max, pid->i_max);
        }
        out = pid->out_max;
    }
    else if (out < pid->out_min)
    {
        if (pid->ki * err < 0.0f)
        {
            pid->i_term -= pid->ki * err * dt;
            pid->i_term = _clamp(pid->i_term, -pid->i_max, pid->i_max);
        }
        out = pid->out_min;
    }

    pid->last_out = out;
    return out;
}
