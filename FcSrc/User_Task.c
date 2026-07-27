#include "User_Task.h"
#include "Ctrl_PID.h"
#include "Ano_Math.h"
#include "Drv_RcIn.h"
#include "ANO_DT_LX.h"
#include "ANO_LX.h"
#include "LX_FC_EXT_Sensor.h"
#include "LX_FC_Fun.h"
#include "LX_FC_State.h"
#include "Drv_Uart.h"
#include "Uplink_Cmd.h" /* 阶段2：运行时目标坐标 Getter */
#include "Auto_Mission.h"

// 通过UART2直接发送0xA0字符串帧到数传（绕过凌霄IMU）
// color: 0=黑 1=红 2=绿
static void Log_Send_Uart2(u8 color, const char *str)
{
    u8 buf[60];
    u8 cnt = 0;
    u8 i = 0;
    u8 sc = 0, ac = 0;

    buf[cnt++] = 0xAA;  // 帧头
    buf[cnt++] = 0xFF;  // 目标地址：广播
    buf[cnt++] = 0xA0;  // 帧ID：字符串信息
    buf[cnt++] = 0;     // LEN占位
    buf[cnt++] = color; // DATA[0]：颜色

    while (str[i] != '\0' && i < 48)
    {
        buf[cnt++] = (u8)str[i++];
    }
    buf[3] = (u8)(cnt - 4); // LEN = COLOR + string字节数

    for (i = 0; i < cnt; i++)
    {
        sc += buf[i];
        ac += sc;
    }
    buf[cnt++] = sc;
    buf[cnt++] = ac;

    DrvUart2SendBuf(buf, cnt);
}

// 周期性发送测试日志，验证UART2→数传→上位机链路
static void user_log_test_task(void)
{
#if LOG_TEST_EN
    static u8 tick_cnt;
    static u8 seq_num;
    char log_str[] = "U2_0 IMU_0"; // 10字符，两路同帧，前缀区分来源

    if (++tick_cnt < LOG_TEST_TICKS)
    {
        return;
    }
    tick_cnt = 0;

    u8 n = seq_num % 10;
    log_str[3] = '0' + n; // U2_0 中的序号
    log_str[9] = '0' + n; // IMU_0 中的序号
    seq_num++;

    // UART2直连数传路径（绿色），已验证可用
    Log_Send_Uart2(STRING_INFO_COLOR_GREEN, log_str);
    // UART5→凌霄IMU路径（红色），测试IMU是否会转发0xA0帧
    String_Info_Send(0xFF, STRING_INFO_COLOR_RED, log_str);
#endif
}

// -----------------------------------------------------------------------
// RC通道诊断 — 辅助函数
// -----------------------------------------------------------------------

// 将 s16 整数转为 ASCII 十进制字符串，写入 buf（至少7字节）
// 返回写入字符数（不含终止符）
static u8 s16_to_str(s16 val, char *buf)
{
    u8 len = 0;
    u16 uval;
    u8 digits[5];
    u8 d = 0;

    if (val < 0)
    {
        buf[len++] = '-';
        uval = (u16)(-val);
    }
    else
    {
        uval = (u16)val;
    }

    if (uval == 0)
    {
        buf[len++] = '0';
    }
    else
    {
        while (uval > 0)
        {
            digits[d++] = (u8)(uval % 10);
            uval /= 10;
        }
        while (d > 0)
        {
            buf[len++] = '0' + digits[--d];
        }
    }
    buf[len] = '\0';
    return len;
}

// 构造 "CHx:NNNN ->描述" 格式字符串写入 out（out至少48字节）
static void make_rc_log(char *out, const char *ch_name, s16 val, const char *desc)
{
    u8 p = 0;
    u8 i;
    for (i = 0; ch_name[i] && p < 11; i++)
        out[p++] = ch_name[i];
    out[p++] = ':';
    p += s16_to_str(val, &out[p]);
    out[p++] = ' ';
    out[p++] = '-';
    out[p++] = '>';
    for (i = 0; desc[i] && p < 47; i++)
        out[p++] = desc[i];
    out[p] = '\0';
}

static const char *rc_channel_name(u8 idx)
{
    static const char *const names[10] = {
        "CH1_ROL", "CH2_PIT", "CH3_THR", "CH4_YAW", "CH5_AUX1",
        "CH6_AUX2", "CH7_AUX3", "CH8_AUX4", "CH9_AUX5", "CH10_AUX6"};
    if (idx < 10)
        return names[idx];
    return "CH?_UNK";
}

static const char *rc_channel_role(u8 idx)
{
    static const char *const roles[10] = {
        "roll", "pitch", "throttle", "yaw", "mode", "task", "aux3", "aux4", "aux5", "aux6"};
    if (idx < 10)
        return roles[idx];
    return "unknown";
}

// -----------------------------------------------------------------------
// RC通道诊断任务
// 运行于50Hz调度，使用边沿检测，仅在状态切换时发送一次绿色LOG。
// 显示通道当前值与代码中对应阈值/变量名的映射关系，方便对照验证。
// 本函数只读数据，不修改任何控制变量，不影响飞行逻辑。
// -----------------------------------------------------------------------
#if PID_TEST_EN
static u8 is_pid_test_channel_active(void)
{
    if (rc_in.fail_safe != 0)
        return 0;
    return (rc_in.rc_ch.st_data.ch_[ch_6_aux2] > 1700 && rc_in.rc_ch.st_data.ch_[ch_6_aux2] < 2200);
}
#endif

#if RC_DIAG_EN
static void rc_diag_task(void)
{
    static u8 prev_fail_safe = 0xFF; // 0xFF=未初始化，保证首次必触发
    static u8 prev_ch5_zone = 0xFF;
    static u8 prev_ch6_zone = 0xFF;
    static u8 prev_fc_mode = 0xFF;
    static u8 prev_unlock = 0xFF;
    static u8 all_ch_inited = 0;
    static u8 prev_ch_zone[10];
    static u8 snapshot_cnt = 0;
    static s16 prev_ch_val[10];

    char msg[48];
    u8 cur_ch5_zone, cur_ch6_zone;
    s16 ch5, ch6;
    u8 i;
    u8 cur_fc_mode, cur_unlock;

    // -------------------------------------------------------------------
    // 1. 失控保护  rc_in.fail_safe: 0=有信号, 1=失控
    // -------------------------------------------------------------------
    u8 cur_fail_safe = rc_in.fail_safe;
    if (cur_fail_safe != prev_fail_safe)
    {
        prev_fail_safe = cur_fail_safe;
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN,
                         cur_fail_safe ? "rc_in.fail_safe=1 LOST"
                                       : "rc_in.fail_safe=0 OK");
    }

    // 失控时通道值无意义，跳过通道区间检测
    if (cur_fail_safe != 0)
        return;

#if PID_TEST_EN
    // 非识别模式下，PID地测期间避免与rc_diag共用缓冲造成覆盖
#if (RC_IDENTIFY_SAFE_MODE == 0)
    if (is_pid_test_channel_active())
        return;
#endif
#endif

#if RC_DIAG_ALL_CHANNELS
    for (i = 0; i < 10u; i++)
    {
        s16 cur = rc_in.rc_ch.st_data.ch_[i];
        u8 z = (cur < 1300) ? 1u : ((cur > 1700) ? 3u : 2u);

        if ((all_ch_inited == 0u) || (z != prev_ch_zone[i]))
        {
            make_rc_log(msg, rc_channel_name(i), cur, rc_channel_role(i));
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
            prev_ch_val[i] = cur;
            prev_ch_zone[i] = z;
        }
    }
    all_ch_inited = 1u;
#endif

#if RC_DIAG_SNAPSHOT_EN
    if (++snapshot_cnt >= RC_DIAG_SNAPSHOT_TICKS)
    {
        snapshot_cnt = 0;
        for (i = 0; i < 10u; i++)
        {
            make_rc_log(msg, rc_channel_name(i), rc_in.rc_ch.st_data.ch_[i], "snapshot");
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
        }
    }
#endif

    // -------------------------------------------------------------------
    // 2. CH5(AUX1) 飞行模式  — ANO_LX.c RC_Data_Task 逻辑：
    //    ch_[ch_5_aux1] < 1200        → LX_Change_Mode(1) 自稳+定高
    //    ch_[ch_5_aux1] < 1700        → LX_Change_Mode(2) 定点
    //    ch_[ch_5_aux1] >= 1700       → LX_Change_Mode(3) 程控
    // -------------------------------------------------------------------
    ch5 = rc_in.rc_ch.st_data.ch_[ch_5_aux1];
    cur_ch5_zone = (ch5 < 1200) ? 1 : (ch5 < 1700) ? 2
                                                   : 3;
    if (cur_ch5_zone != prev_ch5_zone)
    {
        const char *desc;
        prev_ch5_zone = cur_ch5_zone;
        if (cur_ch5_zone == 1)
            desc = "<1200 Mode1(ang+alt)";
        else if (cur_ch5_zone == 2)
            desc = ">=1200 <1700 Mode2(pos)";
        else
            desc = ">=1700 Mode3(prog)";
        make_rc_log(msg, "CH5", ch5, desc);
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
    }

    // -------------------------------------------------------------------
    // 3. CH6(AUX2) 一键命令  — User_Task.c UserTask_OneKeyCmd 逻辑：
    //    ch_[ch_6_aux2] > 800  && <1200  → OneKey_Land()
    //    ch_[ch_6_aux2] > 1300 && <1700  → OneKey_Takeoff(100cm)
    //    ch_[ch_6_aux2] > 1700 && <2200  → OneKey_Mission
    //    其余（包括1200~1300）            → 无触发（空档/死区）
    // -------------------------------------------------------------------
    ch6 = rc_in.rc_ch.st_data.ch_[ch_6_aux2];
    if (ch6 > 800 && ch6 < 1200)
        cur_ch6_zone = 1; // Land
    else if (ch6 > 1300 && ch6 < 1700)
        cur_ch6_zone = 2; // Takeoff
    else if (ch6 > 1700 && ch6 < 2200)
        cur_ch6_zone = 3; // Mission
    else
        cur_ch6_zone = 0; // 无触发
    if (cur_ch6_zone != prev_ch6_zone)
    {
        const char *desc;
        prev_ch6_zone = cur_ch6_zone;
        if (cur_ch6_zone == 1)
            desc = ">800 <1200 OneKey_Land";
        else if (cur_ch6_zone == 2)
            desc = ">1300 <1700 OneKey_Takeoff";
        else if (cur_ch6_zone == 3)
            desc = ">1700 <2200 OneKey_Mission";
        else
            desc = "neutral(no cmd)";
        make_rc_log(msg, "CH6", ch6, desc);
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
    }

    // -------------------------------------------------------------------
    // 4. 飞控模式状态  fc_sta.fc_mode_sta: 0=自稳 1=定高 2=定点 3=程控
    // -------------------------------------------------------------------
    cur_fc_mode = fc_sta.fc_mode_sta;
    if (cur_fc_mode != prev_fc_mode)
    {
        const char *s;
        prev_fc_mode = cur_fc_mode;
        if (cur_fc_mode == 0)
            s = "fc_sta.fc_mode_sta=0 Att";
        else if (cur_fc_mode == 1)
            s = "fc_sta.fc_mode_sta=1 Alt";
        else if (cur_fc_mode == 2)
            s = "fc_sta.fc_mode_sta=2 Pos";
        else
            s = "fc_sta.fc_mode_sta=3 Prog";
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, s);
    }

    // -------------------------------------------------------------------
    // 5. 解锁状态  fc_sta.unlock_sta: 0=上锁, 1=已解锁
    // -------------------------------------------------------------------
    cur_unlock = fc_sta.unlock_sta;
    if (cur_unlock != prev_unlock)
    {
        prev_unlock = cur_unlock;
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN,
                         cur_unlock ? "fc_sta.unlock_sta=1 UNLOCK"
                                    : "fc_sta.unlock_sta=0 LOCK");
    }
}
#endif

// -----------------------------------------------------------------------
// PID 地面自测模块
// -----------------------------------------------------------------------
#if PID_TEST_EN

static _pid_st s_pid_test; // PID 实例（全局唯一，enable=0 时安全）
static _pid_st s_pid_test_y;
static _pid_st s_pid_test_z;
static float s_obs_x;      // 当前观测位置x（单位cm）
static float s_obs_x_int;  // 在线串口模式的积分状态
static float s_obs_x_virt; // 混合模式的虚拟被控对象状态
static float s_obs_y;
static float s_obs_z;
static u16 s_replay_idx; // 离线回放下标

// PID3D 三轴联合任务静态变量（pid_3d_task 使用，PID3D_EN=0 时不编译）
#if PID3D_EN
static _pid_st s_3d_pid_x;     // X轴PID实例
static _pid_st s_3d_pid_y;     // Y轴PID实例
static _pid_st s_3d_pid_z;     // Z轴PID实例
static float s_3d_obs_x;       // X轴观测位置（cm）
static float s_3d_obs_y;       // Y轴观测位置（cm）
static float s_3d_obs_z;       // Z轴观测位置（cm）
static u16 s_3d_tick;          // RUNNING阶段tick计数（超时检测）
static u16 s_3d_arrive_cnt;    // 到位持续tick计数（到位确认）
static u8 s_3d_log_cnt;        // LOG间隔计数器
static u8 s_3d_log_toggle;     // LOG交替标志（0=打obs，1=打vel）
static u8 s_3d_gui_active;     // GUI自主位移任务是否正在复用PID3D
static u8 s_3d_gui_step;       // GUI自主位移任务step，传给pid_3d_task
static u8 s_3d_gui_axis_mode;  // GUI自主位移轴模式：0=XYZ,1=X,2=Y,3=Z,4=XY
static s32 s_3d_alt_ref_cm;    // 初始高度参考值（cm）
static u16 s_3d_alt_hold_cnt;  // 定高稳定连续tick数
static u16 s_3d_alt_wait_tick; // 定高等待总tick数
static s32 s_3d_pos_ref_x_cm;  // 任务启动时的fc_pos.pos_x基准（cm）
static s32 s_3d_pos_ref_y_cm;  // 任务启动时的fc_pos.pos_y基准（cm）
#endif

static void pid_stop_output_now(void)
{
    // 立即清零实时速度指令，确保拨杆回正后不再输出运动速度
    s_pid_test.enable = 0;
    s_pid_test_y.enable = 0;
    s_pid_test_z.enable = 0;
    Pid_Reset(&s_pid_test);
    Pid_Reset(&s_pid_test_y);
    Pid_Reset(&s_pid_test_z);
    s_obs_y = 0.0f;
    s_obs_z = 0.0f;
#if PID3D_EN
    // 同时复位三轴联合PID状态，防止重新触发时积分残留
    s_3d_pid_x.enable = 0;
    s_3d_pid_y.enable = 0;
    s_3d_pid_z.enable = 0;
    Pid_Reset(&s_3d_pid_x);
    Pid_Reset(&s_3d_pid_y);
    Pid_Reset(&s_3d_pid_z);
    s_3d_obs_x = 0.0f;
    s_3d_obs_y = 0.0f;
    s_3d_obs_z = 0.0f;
    s_3d_gui_active = 0;
    s_3d_gui_step = 0;
    s_3d_gui_axis_mode = 0;
#endif
    rt_tar.st_data.vel_x = 0;
    rt_tar.st_data.vel_y = 0;
    rt_tar.st_data.vel_z = 0;
    dt.fun[0x41].WTS = 1;
}

// 离线回放观测x（单位cm）：用于先离线验证，再切在线串口
static const float s_replay_x_tab[] = {
    0.00f, 0.15f, 0.35f, 0.60f, 0.90f, 1.20f, 1.52f, 1.83f, 2.12f, 2.38f,
    2.62f, 2.84f, 3.03f, 3.20f, 3.36f, 3.50f, 3.63f, 3.74f, 3.85f, 3.95f,
    4.03f, 4.11f, 4.18f, 4.25f, 4.31f, 4.36f, 4.41f, 4.46f, 4.50f, 4.54f,
    4.58f, 4.61f, 4.64f, 4.67f, 4.70f, 4.72f, 4.74f, 4.76f, 4.78f, 4.80f,
    4.82f, 4.83f, 4.85f, 4.86f, 4.87f, 4.88f, 4.89f, 4.90f, 4.91f, 4.92f,
    4.93f, 4.94f, 4.95f, 4.95f, 4.96f, 4.96f, 4.97f, 4.97f, 4.98f, 4.98f,
    4.98f, 4.99f, 4.99f, 4.99f, 5.00f, 5.00f};

static void pid_obs_reset(void)
{
    s_obs_x = 0.0f;
    s_obs_x_int = 0.0f;
    s_obs_x_virt = 0.0f;
    s_replay_idx = 0;
}

// 采样当前观测x：按配置选择模型/离线回放/在线串口
static float pid_get_obs_x(float out, float dt)
{
#if (PID_OBS_MODE == 0)
    // 纯模型：与旧版一致
    s_obs_x += out * dt * 0.8f;
#elif (PID_OBS_MODE == 1)
    // 离线回放：每tick读取一个观测点，末尾保持
    u16 n = (u16)(sizeof(s_replay_x_tab) / sizeof(s_replay_x_tab[0]));
    if (s_replay_idx < n)
    {
        s_obs_x = s_replay_x_tab[s_replay_idx++];
    }
    else
    {
        s_obs_x = s_replay_x_tab[n - 1];
    }
#elif (PID_OBS_MODE == 2)
    // 在线串口：用IMU速度(0x07)积分得到观测x
    // 可通过PID_OBS_VX_BIAS_CMPS做固定偏置补偿
    {
        float vx_meas = (float)fc_vel.st_data.vel_x;
        s_obs_x_int += (vx_meas - PID_OBS_VX_BIAS_CMPS) * dt * PID_OBS_VX_SCALE_X;
        s_obs_x = s_obs_x_int;
    }
#elif (PID_OBS_MODE == 3)
    // 混合半实物：真实在线观测 + 虚拟被控对象
    // 不飞时也能形成闭环收敛，同时保留真实观测扰动影响
    {
        float vx_meas = (float)fc_vel.st_data.vel_x;
        float w_real;

        // 在线观测分量
        s_obs_x_int += (vx_meas - PID_OBS_VX_BIAS_CMPS) * dt * PID_OBS_VX_SCALE_X;
        // 虚拟闭环分量
        s_obs_x_virt += out * dt * PID_OBS_HYB_VIRTUAL_GAIN;

        w_real = PID_OBS_HYB_W_REAL;
        if (w_real < 0.0f)
            w_real = 0.0f;
        if (w_real > 1.0f)
            w_real = 1.0f;
        s_obs_x = w_real * s_obs_x_int + (1.0f - w_real) * s_obs_x_virt;
    }
#else
    s_obs_x += out * dt * 0.8f;
#endif
    return s_obs_x;
}

// 浮点转字符串：[-999.99, 999.99]，2位小数，buf 需 >= 9 字节
// 返回写入字节数（不含 '\0'）
static u8 f2s(float v, char *buf)
{
    s32 vi;
    u8 len = 0;
    s32 ip, fp;

    // 四舍五入到 2 位小数
    if (v >= 0.0f)
        vi = (s32)(v * 100.0f + 0.5f);
    else
        vi = -(s32)((-v) * 100.0f + 0.5f);

    if (vi < 0)
    {
        buf[len++] = '-';
        vi = -vi;
    }

    ip = vi / 100;
    fp = vi % 100;

    if (ip >= 100)
        buf[len++] = '0' + (u8)((ip / 100) % 10);
    if (ip >= 10)
        buf[len++] = '0' + (u8)((ip / 10) % 10);
    buf[len++] = '0' + (u8)(ip % 10);
    buf[len++] = '.';
    buf[len++] = '0' + (u8)(fp / 10);
    buf[len++] = '0' + (u8)(fp % 10);
    buf[len] = '\0';
    return len;
}

// 向 msg[p] 追加字符串，上限 46 字节，返回新的 p
static u8 app(char *msg, u8 p, const char *s)
{
    while (*s && p < 46u)
        msg[p++] = *s++;
    return p;
}

// PID 实机任务（50Hz 调用，dt=0.02s）
// step=1：首次激活，初始化；step=2：运行仿真；step=3：已收敛保持；step=4：超时保持
// setpoint = PID_TARGET_X_CM，实时输出vel_x指令给IMU（限幅5cm/s）
static void pid_ground_test_task(u8 *step)
{
    static u16 s_tick;    // 累计 tick 数（最大 65535，足够 10s）
    static u8 s_log_cnt;  // LOG 间隔计数
    static u8 s_conv_cnt; // 连续收敛 tick 数
    static s32 s_alt_ref_cm;
    static u16 s_alt_hold_cnt;
    static u16 s_alt_wait_tick;
    static u8 s_pid_started;
    char msg[48];
    u8 p;
    float out, err, err_abs, out_abs;

    // ---- 初始化（step==1：边沿触发，每次拨杆只执行一次）----
    if (*step == 1)
    {
        pid_obs_reset();
        s_tick = 0;
        s_log_cnt = 0;
        s_conv_cnt = 0;
        s_alt_ref_cm = ext_sens.gen_dis.st_data.distance_cm;
        s_alt_hold_cnt = 0;
        s_alt_wait_tick = 0;
        s_pid_started = 0;

        Pid_Init(&s_pid_test);
        // 参数由User_Task.h中的PID_TUNE_PROFILE选择
        Pid_SetGains(&s_pid_test, PID_KP, PID_KI, PID_KD);
        Pid_SetLimits(&s_pid_test, PID_VEL_LIMIT_CMPS, PID_VEL_LIMIT_CMPS);
        s_pid_test.d_lpf_alpha = 0.3f; // D项低通，抑制观测噪声放大
        s_pid_test.dead_zone = 0.05f;  // 5mm 以内死区
        s_pid_test.enable = 0;

        // 初始化成功LOG（绿色）：打印参数摘要
        {
            const char *mode_str;
#if (PID_OBS_MODE == 0)
            mode_str = "PID TEST OBS=model";
#elif (PID_OBS_MODE == 1)
            mode_str = "PID TEST OBS=replay";
#elif (PID_OBS_MODE == 2)
            mode_str = "PID TEST OBS=online_vx";
#elif (PID_OBS_MODE == 3)
            mode_str = "PID TEST OBS=hybrid_nofly";
#else
            mode_str = "PID TEST OBS=unknown";
#endif
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, mode_str);

            // 启动参数摘要：飞前快速确认当前档位与关键参数
            p = 0;
            p = app(msg, p, "CFG p");
            msg[p++] = '0' + (u8)PID_TUNE_PROFILE;
            p = app(msg, p, " t");
            p += f2s(PID_TARGET_X_CM, &msg[p]);
            p = app(msg, p, " v");
            p += f2s(PID_VEL_LIMIT_CMPS, &msg[p]);
            p = app(msg, p, " kp");
            p += f2s(PID_KP, &msg[p]);
            p = app(msg, p, " ki0.0043 kd");
            p += f2s(PID_KD, &msg[p]);
            p = app(msg, p, " sx");
            p += f2s(PID_OBS_VX_SCALE_X, &msg[p]);
            p = app(msg, p, " sy");
            p += f2s(PID_OBS_VX_SCALE_Y, &msg[p]);
            p = app(msg, p, " sz");
            p += f2s(PID_OBS_VX_SCALE_Z, &msg[p]);
            msg[p] = '\0';
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
        }
        *step = 2;
        return;
    }

#if PID_ALT_PREHOLD_EN
    // ---- 前置定高稳定：先保持高度稳定，再启动X轴PID ----
    if (s_pid_started == 0)
    {
        float alt_cur = (float)ext_sens.gen_dis.st_data.distance_cm;
        float alt_err = alt_cur - (float)s_alt_ref_cm;
        float alt_err_abs = (alt_err < 0.0f) ? -alt_err : alt_err;

        // 预稳定阶段强制不输出水平速度，且不进行X观测积分
        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;

        s_alt_wait_tick++;
        if (alt_err_abs < PID_ALT_STABLE_BAND_CM)
            s_alt_hold_cnt++;
        else
            s_alt_hold_cnt = 0;

        if (s_alt_hold_cnt >= PID_ALT_STABLE_TICKS)
        {
            s_pid_started = 1;
            s_tick = 0;
            s_log_cnt = 0;
            s_conv_cnt = 0;
            pid_obs_reset();
            s_pid_test.enable = 1;

            p = 0;
            p = app(msg, p, "PID ALT OK h:");
            p += f2s(alt_cur, &msg[p]);
            msg[p] = '\0';
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
            return;
        }

        if (s_alt_wait_tick >= PID_ALT_PREHOLD_TIMEOUT_TICKS)
        {
            p = 0;
            p = app(msg, p, "PID ALT TIMEOUT h:");
            p += f2s(alt_cur, &msg[p]);
            msg[p] = '\0';
            String_Info_Send(0xFF, STRING_INFO_COLOR_RED, msg);
            pid_stop_output_now();
            *step = 4;
            return;
        }

        if (++s_log_cnt >= 10u)
        {
            s_log_cnt = 0;
            p = 0;
            p = app(msg, p, "PID ALT HOLD h:");
            p += f2s(alt_cur, &msg[p]);
            p = app(msg, p, " ref:");
            p += f2s((float)s_alt_ref_cm, &msg[p]);
            msg[p] = '\0';
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
        }
        return;
    }
#else
    if (s_pid_started == 0)
    {
        s_pid_started = 1;
        s_pid_test.enable = 1;
    }
#endif

    // ---- 完成/超时状态：通道保持时持续心跳LOG，便于地面实时观察 ----
    if (*step >= 3u)
    {
        if (++s_log_cnt < 25u) // 500ms
            return;
        s_log_cnt = 0;

        p = 0;
        p = app(msg, p, (*step == 3u) ? "PID HOLD DONE m:" : "PID HOLD TIMEOUT m:");
        p += f2s(s_obs_x, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF,
                         (*step == 3u) ? STRING_INFO_COLOR_GREEN : STRING_INFO_COLOR_RED,
                         msg);

        // 保持/超时时也持续下发零速度，保证任务结束后不再驱动
        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;
        return;
    }

    // ---- 超时保护（1500tick = 30s，未收敛则报警）----
    if (s_tick >= 1500u)
    {
        p = 0;
        p = app(msg, p, "PID TIMEOUT m:");
        p += f2s(s_obs_x, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_RED, msg);
        pid_stop_output_now();
        *step = 4;
        return;
    }

    // ---- PID 步进（每 tick 调用一次，dt=0.02s）----
    out = Pid_Update(&s_pid_test, PID_TARGET_X_CM, s_obs_x, 0.02f);
    pid_get_obs_x(out, 0.02f);

    // 将PID输出实时下发为头向速度指令（仅X轴任务）
    rt_tar.st_data.vel_x = (s16)out;
    rt_tar.st_data.vel_y = 0;
    rt_tar.st_data.vel_z = 0;
    dt.fun[0x41].WTS = 1;

    s_tick++;

    // ---- 收敛判定（使用User_Task.h中的实飞阈值）----
    err = PID_TARGET_X_CM - s_obs_x;
    err_abs = err < 0.0f ? -err : err;
    out_abs = out < 0.0f ? -out : out;

    if (err_abs < PID_DONE_ERR_CM && out_abs < PID_DONE_OUT_CMPS)
        s_conv_cnt++;
    else
        s_conv_cnt = 0;

    if (s_conv_cnt >= PID_DONE_HOLD_TICKS)
    {
        p = 0;
        p = app(msg, p, "PID DONE m:");
        p += f2s(s_obs_x, &msg[p]);
        p = app(msg, p, " err:");
        p += f2s(err, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
        pid_stop_output_now();
        *step = 3;
        return;
    }

    // ---- 周期性 LOG（每5tick=100ms一条，格式："T:050 m:3.12 o:1.88"）----
    if (++s_log_cnt < 5u)
        return;
    s_log_cnt = 0;

    p = 0;
    msg[p++] = 'T';
    msg[p++] = ':';
    msg[p++] = '0' + (u8)((s_tick / 1000u) % 10u);
    msg[p++] = '0' + (u8)((s_tick / 100u) % 10u);
    msg[p++] = '0' + (u8)((s_tick / 10u) % 10u);
    msg[p++] = '0' + (u8)(s_tick % 10u);
    msg[p++] = ' ';
    msg[p++] = 'm';
    msg[p++] = ':';
    p += f2s(s_obs_x, &msg[p]);
    msg[p++] = ' ';
    msg[p++] = 'o';
    msg[p++] = ':';
    p += f2s(out, &msg[p]);
    msg[p] = '\0';
    String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
}

// Y/Z解耦PID任务（50Hz）
// axis: 1->Y, 2->Z
static void pid_ground_test_task_yz(u8 *step, u8 axis)
{
    static u16 s_tick[2];
    static u8 s_log_cnt[2];
    static u8 s_conv_cnt[2];
    _pid_st *pid;
    float *obs;
    float target;
    float vel_meas;
    float out, err, err_abs, out_abs;
    char msg[48];
    u8 p;
    u8 idx;
    char axis_ch;

    if (axis == 1u)
    {
        idx = 0u;
        pid = &s_pid_test_y;
        obs = &s_obs_y;
        target = PID_TARGET_Y_CM;
        vel_meas = (float)fc_vel.st_data.vel_y;
        axis_ch = 'Y';
    }
    else
    {
        idx = 1u;
        pid = &s_pid_test_z;
        obs = &s_obs_z;
        target = PID_TARGET_Z_CM;
        vel_meas = (float)fc_vel.st_data.vel_z;
        axis_ch = 'Z';
    }

    if (*step == 1u)
    {
        s_tick[idx] = 0;
        s_log_cnt[idx] = 0;
        s_conv_cnt[idx] = 0;
        *obs = 0.0f;

        Pid_Init(pid);
        Pid_SetGains(pid, PID_KP, PID_KI, PID_KD);
        Pid_SetLimits(pid, PID_VEL_LIMIT_CMPS, PID_VEL_LIMIT_CMPS);
        pid->d_lpf_alpha = 0.3f;
        pid->dead_zone = 0.05f;
        pid->enable = 1;

        p = 0;
        p = app(msg, p, "PID ");
        msg[p++] = axis_ch;
        p = app(msg, p, " START t:");
        p += f2s(target, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);

        *step = 2u;
        return;
    }

    if (*step >= 3u)
    {
        if (++s_log_cnt[idx] < 25u)
            return;
        s_log_cnt[idx] = 0;

        p = 0;
        p = app(msg, p, (*step == 3u) ? "PID HOLD DONE " : "PID HOLD TIMEOUT ");
        msg[p++] = axis_ch;
        p = app(msg, p, " m:");
        p += f2s(*obs, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, (*step == 3u) ? STRING_INFO_COLOR_GREEN : STRING_INFO_COLOR_RED, msg);

        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;
        return;
    }

    if (s_tick[idx] >= 1500u)
    {
        p = 0;
        p = app(msg, p, "PID TIMEOUT ");
        msg[p++] = axis_ch;
        p = app(msg, p, " m:");
        p += f2s(*obs, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_RED, msg);

        pid->enable = 0;
        Pid_Reset(pid);
        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;
        *step = 4u;
        return;
    }

    out = Pid_Update(pid, target, *obs, 0.02f);
    if (axis == 1u)
        *obs += vel_meas * 0.02f * PID_OBS_VX_SCALE_Y;
    else
        *obs += vel_meas * 0.02f * PID_OBS_VX_SCALE_Z;

    rt_tar.st_data.vel_x = 0;
    rt_tar.st_data.vel_y = 0;
    rt_tar.st_data.vel_z = 0;
    if (axis == 1u)
        rt_tar.st_data.vel_y = (s16)out;
    else
        rt_tar.st_data.vel_z = (s16)out;
    dt.fun[0x41].WTS = 1;

    s_tick[idx]++;

    err = target - *obs;
    err_abs = (err < 0.0f) ? -err : err;
    out_abs = (out < 0.0f) ? -out : out;

    if (err_abs < PID_DONE_ERR_CM && out_abs < PID_DONE_OUT_CMPS)
        s_conv_cnt[idx]++;
    else
        s_conv_cnt[idx] = 0;

    if (s_conv_cnt[idx] >= PID_DONE_HOLD_TICKS)
    {
        p = 0;
        p = app(msg, p, "PID DONE ");
        msg[p++] = axis_ch;
        p = app(msg, p, " m:");
        p += f2s(*obs, &msg[p]);
        p = app(msg, p, " err:");
        p += f2s(err, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);

        pid->enable = 0;
        Pid_Reset(pid);
        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;
        *step = 3u;
        return;
    }

    if (++s_log_cnt[idx] < 5u)
        return;
    s_log_cnt[idx] = 0;

    p = 0;
    p = app(msg, p, "T:");
    msg[p++] = '0' + (u8)((s_tick[idx] / 1000u) % 10u);
    msg[p++] = '0' + (u8)((s_tick[idx] / 100u) % 10u);
    msg[p++] = '0' + (u8)((s_tick[idx] / 10u) % 10u);
    msg[p++] = '0' + (u8)(s_tick[idx] % 10u);
    msg[p++] = ' ';
    msg[p++] = axis_ch;
    p = app(msg, p, " m:");
    p += f2s(*obs, &msg[p]);
    p = app(msg, p, " o:");
    p += f2s(out, &msg[p]);
    msg[p] = '\0';
    String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
}

// -----------------------------------------------------------------------
// 三轴联合位置控制任务（50Hz，dt=0.02s）
// 输入：PID3D_GOAL_X/Y/Z_CM（增量模式，各轴从观测0开始到目标坐标）
//      axis_mode：1=仅X飞行(只用goal_x，gy=gz=0)
//                 2=仅Y飞行(只用goal_y，gx=gz=0)
//                 3=仅Z飞行(只用goal_z，gx=gy=0)
//                 0=三轴全开(gx,gy,gz均使用Uplink目标，三轴联合控制)
// 输出：rt_tar.vel_x/y/z 同帧发送（合速度小于PID3D_VEL_TOTAL_CMPS）
// step=1:初始化  step=2:等高度稳定  step=3:PID运行  step=4:到位维持  step=5:超时停止
// -----------------------------------------------------------------------
#if PID3D_EN
static void pid_3d_task(u8 *step, u8 axis_mode)
{
    char msg[48];
    u8 p;
    float vx, vy, vz;
    float err_x, err_y, err_z;
    float err_x_abs, err_y_abs, err_z_abs;
    float v_sq, v_max_sq;
    s32 alt_err_cm;

    // 目标坐标（增量模式：各轴观测均初始化为0，目标即位移量）
    // 阶段2：默认值取自 PID3D_GOAL_X/Y/Z_CM 宏；运行中可通过 0xF2 帧改写
    // RAM 副本，但本任务每次启动（step=1）时拍一次照锁定为 const，
    // 飞行过程中不会突变（更换目标流程：落地 → 写参 → 再起飞）。
    // axis_mode 选择本次任务实际使用的目标轴（未启用轴的 goal 直接置 0）
    // 0=三轴 1=X轴 2=Y轴 3=Z轴 4=X+Y（Z保持悬停）
    const float goal_x = (axis_mode == 0u || axis_mode == 1u || axis_mode == 4u) ? Uplink_GetGoalX_Cm() : 0.0f;
    const float goal_y = (axis_mode == 0u || axis_mode == 2u || axis_mode == 4u) ? Uplink_GetGoalY_Cm() : 0.0f;
    const float goal_z = (axis_mode == 0u || axis_mode == 3u) ? Uplink_GetGoalZ_Cm() : 0.0f;

    // -----------------------------------------------------------------
    // step=1: 初始化，复位所有状态和三个PID实例
    // -----------------------------------------------------------------
    if (*step == 1u)
    {
        s_3d_obs_x = 0.0f;
        s_3d_obs_y = 0.0f;
        s_3d_obs_z = 0.0f;
        s_3d_tick = 0;
        s_3d_arrive_cnt = 0;
        s_3d_log_cnt = 0;
        s_3d_log_toggle = 0;
        s_3d_alt_hold_cnt = 0;
        s_3d_alt_wait_tick = 0;
        // 记录当前高度作为前置定高的参考基准
        s_3d_alt_ref_cm = ext_sens.gen_dis.st_data.distance_cm;
        // 记录当前XY位置作为增量PID的基准（0x08帧位置）
        s_3d_pos_ref_x_cm = fc_pos.st_data.pos_x;
        s_3d_pos_ref_y_cm = fc_pos.st_data.pos_y;

        // 初始化三个独立PID（各轴参数独立，方便分轴调参）
        Pid_Init(&s_3d_pid_x);
        Pid_SetGains(&s_3d_pid_x, PID3D_KP_X, PID3D_KI_X, PID3D_KD_X);
        Pid_SetLimits(&s_3d_pid_x, PID3D_VEL_X_CMPS, PID3D_VEL_X_CMPS);
        s_3d_pid_x.d_lpf_alpha = 0.3f;
        s_3d_pid_x.dead_zone = 0.05f;
        s_3d_pid_x.enable = 0; // 等高度稳定后才使能

        Pid_Init(&s_3d_pid_y);
        Pid_SetGains(&s_3d_pid_y, PID3D_KP_Y, PID3D_KI_Y, PID3D_KD_Y);
        Pid_SetLimits(&s_3d_pid_y, PID3D_VEL_Y_CMPS, PID3D_VEL_Y_CMPS);
        s_3d_pid_y.d_lpf_alpha = 0.3f;
        s_3d_pid_y.dead_zone = 0.05f;
        s_3d_pid_y.enable = 0;

        Pid_Init(&s_3d_pid_z);
        Pid_SetGains(&s_3d_pid_z, PID3D_KP_Z, PID3D_KI_Z, PID3D_KD_Z);
        Pid_SetLimits(&s_3d_pid_z, PID3D_VEL_Z_CMPS, PID3D_VEL_Z_CMPS);
        s_3d_pid_z.d_lpf_alpha = 0.3f;
        s_3d_pid_z.dead_zone = 0.05f;
        s_3d_pid_z.enable = 0;

        // 打印初始化日志：目标坐标
        p = 0;
        p = app(msg, p, "3D INIT gx:");
        p += f2s(goal_x, &msg[p]);
        p = app(msg, p, " gy:");
        p += f2s(goal_y, &msg[p]);
        p = app(msg, p, " gz:");
        p += f2s(goal_z, &msg[p]);
        msg[p] = '\0';
        String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);

#if PID3D_ALT_PREHOLD_EN
        *step = 2u; // 进入前置高度稳定等待
#else
        // 跳过定高等待，直接启动三轴PID
        s_3d_pid_x.enable = 1;
        s_3d_pid_y.enable = 1;
        s_3d_pid_z.enable = 1;
        *step = 3u;
#endif
        return;
    }

    // -----------------------------------------------------------------
    // step=2: 前置高度稳定等待
    // 三轴vel全为0，等待高度在 ±ALT_STABLE_BAND_CM 内保持 ALT_STABLE_TICKS
    // -----------------------------------------------------------------
#if PID3D_ALT_PREHOLD_EN
    if (*step == 2u)
    {
        rt_tar.st_data.vel_x = 0;
        rt_tar.st_data.vel_y = 0;
        rt_tar.st_data.vel_z = 0;
        dt.fun[0x41].WTS = 1;

        s_3d_alt_wait_tick++;
        if (s_3d_alt_wait_tick >= PID3D_ALT_PREHOLD_TIMEOUT_TICKS)
        {
            // 超时：高度始终不稳，放弃任务
            String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "3D ALT TIMEOUT");
            *step = 5u;
            return;
        }

        alt_err_cm = ext_sens.gen_dis.st_data.distance_cm - s_3d_alt_ref_cm;
        if (alt_err_cm < 0)
            alt_err_cm = -alt_err_cm;

        if (alt_err_cm < (s32)PID3D_ALT_STABLE_BAND_CM)
            s_3d_alt_hold_cnt++;
        else
            s_3d_alt_hold_cnt = 0;

        if (s_3d_alt_hold_cnt >= PID3D_ALT_STABLE_TICKS)
        {
            // 高度已稳定，启动三轴PID
            s_3d_pid_x.enable = 1;
            s_3d_pid_y.enable = 1;
            s_3d_pid_z.enable = 1;
            String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, "3D ALT OK->RUN");
            *step = 3u;
        }
        return;
    }
#endif

    // -----------------------------------------------------------------
    // step=3(RUNNING)：PID运行，到位后切step=4
    // step=4(ARRIVED)：到位，持续PID修正维持位置，不关闭PID
    // -----------------------------------------------------------------
    if (*step == 3u || *step == 4u)
    {
        // 超时保护（仅RUNNING阶段计时，ARRIVED后不计时）
        if (*step == 3u)
        {
            if (s_3d_tick >= PID3D_TIMEOUT_TICKS)
            {
                String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "3D TIMEOUT");
                Pid_Reset(&s_3d_pid_x);
                Pid_Reset(&s_3d_pid_y);
                Pid_Reset(&s_3d_pid_z);
                rt_tar.st_data.vel_x = 0;
                rt_tar.st_data.vel_y = 0;
                rt_tar.st_data.vel_z = 0;
                dt.fun[0x41].WTS = 1;
                *step = 5u;
                return;
            }
            s_3d_tick++;
        }

        // 观测更新：各轴独立，MODE=2 速度积分 / MODE=3 直接读0x08位置帧
#if (PID3D_OBS_X_MODE == 2)
        s_3d_obs_x += (float)fc_vel.st_data.vel_x * 0.02f * PID3D_SCALE_X;
#elif (PID3D_OBS_X_MODE == 3)
        s_3d_obs_x = (float)(fc_pos.st_data.pos_x - s_3d_pos_ref_x_cm) * PID3D_SCALE_X;
#endif
#if (PID3D_OBS_Y_MODE == 2)
        s_3d_obs_y += (float)fc_vel.st_data.vel_y * 0.02f * PID3D_SCALE_Y;
#elif (PID3D_OBS_Y_MODE == 3)
        s_3d_obs_y = (float)(fc_pos.st_data.pos_y - s_3d_pos_ref_y_cm) * PID3D_SCALE_Y;
#endif
#if (PID3D_OBS_Z_MODE == 2)
        s_3d_obs_z += (float)fc_vel.st_data.vel_z * 0.02f * PID3D_SCALE_Z;
#endif

        // 各轴独立PID计算（已在Pid_SetLimits中限幅至±VEL_X/Y/Z_CMPS）
        vx = Pid_Update(&s_3d_pid_x, goal_x, s_3d_obs_x, 0.02f);
        vy = Pid_Update(&s_3d_pid_y, goal_y, s_3d_obs_y, 0.02f);
        vz = Pid_Update(&s_3d_pid_z, goal_z, s_3d_obs_z, 0.02f);

        // 合速度限制：超出PID3D_VEL_TOTAL_CMPS时等比缩放各轴
        // 使用项目内置my_sqrt（STM32F407 FPU支持，50Hz调用安全）
        v_sq = vx * vx + vy * vy + vz * vz;
        v_max_sq = PID3D_VEL_TOTAL_CMPS * PID3D_VEL_TOTAL_CMPS;
        if (v_sq > v_max_sq && v_sq > 0.001f)
        {
            float k = PID3D_VEL_TOTAL_CMPS / my_sqrt(v_sq);
            vx *= k;
            vy *= k;
            vz *= k;
        }

        // 开环串扰补偿：放在合速度限制之后，避免补偿被等比缩放削弱
        // 现象修正：vx 正向飞行时 Y 正向漂移，加 vx*(-0.1) 反向拉回
        // 补偿后总速度增幅极小（vx=25 时 vy_comp=-2.5，合速度 25.12 cm/s）
        vy += vx * PID3D_VY_XCOUPLE_GAIN;
        vx += vy * PID3D_VX_YCOUPLE_GAIN;

        // 写入实时控制帧（vel字段为s16，速度≤±30cm/s不会溢出）
        rt_tar.st_data.vel_x = (s16)vx;
        rt_tar.st_data.vel_y = (s16)vy;
        rt_tar.st_data.vel_z = (s16)vz;
        dt.fun[0x41].WTS = 1;

        // 误差计算（用于到位判定和LOG）
        err_x = goal_x - s_3d_obs_x;
        err_y = goal_y - s_3d_obs_y;
        err_z = goal_z - s_3d_obs_z;
        err_x_abs = (err_x < 0.0f) ? -err_x : err_x;
        err_y_abs = (err_y < 0.0f) ? -err_y : err_y;
        err_z_abs = (err_z < 0.0f) ? -err_z : err_z;

        // 到位判定（仅RUNNING阶段，ARRIVED后仅维持不再判定）
        if (*step == 3u)
        {
            if (err_x_abs < PID3D_ARRIVE_ERR_CM &&
                err_y_abs < PID3D_ARRIVE_ERR_CM &&
                err_z_abs < PID3D_ARRIVE_ERR_CM)
            {
                s_3d_arrive_cnt++;
            }
            else
            {
                s_3d_arrive_cnt = 0;
            }
            if (s_3d_arrive_cnt >= PID3D_ARRIVE_HOLD_TICKS)
            {
                p = 0;
                p = app(msg, p, "3D ARRIVED ex:");
                p += f2s(err_x, &msg[p]);
                p = app(msg, p, " ey:");
                p += f2s(err_y, &msg[p]);
                p = app(msg, p, " ez:");
                p += f2s(err_z, &msg[p]);
                msg[p] = '\0';
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
                *step = 4u; // 切到ARRIVED，继续维持PID修正
            }
        }

        // LOG：遥控/PID自测保持原100ms节奏；GUI自主位移只保留低频摘要。
        // F9飞行时主要依赖0xF8状态帧，避免A0字符串日志占用数传带宽。
        if (s_3d_gui_active != 0u && *step == 4u)
        {
            return;
        }
        if (++s_3d_log_cnt >= ((s_3d_gui_active != 0u) ? 50u : 5u))
        {
            s_3d_log_cnt = 0;
            if (s_3d_log_toggle == 0u)
            {
                p = 0;
                p = app(msg, p, "3D ox:");
                p += f2s(s_3d_obs_x, &msg[p]);
                p = app(msg, p, " oy:");
                p += f2s(s_3d_obs_y, &msg[p]);
                p = app(msg, p, " oz:");
                p += f2s(s_3d_obs_z, &msg[p]);
                msg[p] = '\0';
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
            }
            else
            {
                p = 0;
                p = app(msg, p, "3D vx:");
                p += f2s(vx, &msg[p]);
                p = app(msg, p, " vy:");
                p += f2s(vy, &msg[p]);
                p = app(msg, p, " vz:");
                p += f2s(vz, &msg[p]);
                msg[p] = '\0';
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, msg);
            }
            s_3d_log_toggle ^= 1u;
        }
        return;
    }

    // -----------------------------------------------------------------
    // step=5: 超时/异常终态，不再输出速度，每500ms打印提醒
    // -----------------------------------------------------------------
    if (*step == 5u)
    {
        if (++s_3d_log_cnt >= 25u)
        {
            s_3d_log_cnt = 0;
            String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "3D STOPPED");
        }
    }
}
#endif // PID3D_EN

#endif // PID_TEST_EN

#if (PID_TEST_EN && PID3D_EN)
u8 UserTask_Pid3dStartFromGui(u8 axis_mode)
{
    if (axis_mode > 4u)
    {
        return 0;
    }
    if (s_3d_gui_active != 0u && s_3d_gui_step == 3u)
    {
        return 0;
    }

    pid_stop_output_now();
    s_3d_gui_axis_mode = axis_mode;
    s_3d_gui_step = 1u;
    s_3d_gui_active = 1u;
    return 1;
}

void UserTask_Pid3dTickFromGui(void)
{
    if (s_3d_gui_active == 0u)
    {
        return;
    }
    pid_3d_task(&s_3d_gui_step, s_3d_gui_axis_mode);
    if (s_3d_gui_step == 5u)
    {
        s_3d_gui_active = 0u;
    }
}

void UserTask_Pid3dStopFromGui(void)
{
    s_3d_gui_active = 0u;
    s_3d_gui_step = 0u;
    s_3d_gui_axis_mode = 0u;
    pid_stop_output_now();
}

u8 UserTask_Pid3dGuiActive(void)
{
    return s_3d_gui_active;
}

u8 UserTask_Pid3dGuiStep(void)
{
    return s_3d_gui_step;
}
#else
u8 UserTask_Pid3dStartFromGui(u8 axis_mode)
{
    (void)axis_mode;
    return 0;
}

void UserTask_Pid3dTickFromGui(void) {}
void UserTask_Pid3dStopFromGui(void) {}
u8 UserTask_Pid3dGuiActive(void) { return 0; }
u8 UserTask_Pid3dGuiStep(void) { return 0; }
#endif

#if PID_TEST_EN
/* 前向声明：ARMCC V5(C90模式)在函数外调用时需要可见的static原型，否则生成extern引用导致链接失败 */
static void pid_stop_output_now(void);
#endif

void UserTask_OneKeyCmd(void)
{
    //////////////////////////////////////////////////////////////////////
    // 一键起飞/降落例程
    //////////////////////////////////////////////////////////////////////
    // UART2日志测试入口：验证数传直连→上位机链路
    // user_log_test_task();

#if RC_DIAG_EN
    // RC通道诊断：状态切换时发绿色LOG，显示通道值与代码阈值对应关系
    rc_diag_task();
#endif

#if RC_IDENTIFY_SAFE_MODE
    // 地面识别模式：只做通道识别日志，屏蔽一键起飞/任务动作。
#if PID_TEST_EN
    if (UserTask_Pid3dGuiActive() == 0u)
    {
        pid_stop_output_now();
    }
#endif
    return;
#endif

    // 用静态变量记录一键起飞/任务指令已经执行。
    static u8 one_key_takeoff_f = 1, one_key_mission_f = 0;
    static u8 one_key_mission_y_f = 0, one_key_mission_z_f = 0;
    static u8 pid_need_mode2_warned = 0;
    static u8 mission_step;
    static u8 mission_step_y;
    static u8 mission_step_z;
    static u8 pid_active_axis;
    static u8 pid_multi_axis_warned;

    if (Auto_Mission_RcControlAllowed() == 0u)
    {
        one_key_takeoff_f = 1;
        one_key_mission_f = 0;
        one_key_mission_y_f = 0;
        one_key_mission_z_f = 0;
        mission_step = 0;
        mission_step_y = 0;
        mission_step_z = 0;
        pid_active_axis = 0;
#if PID_TEST_EN
        if (UserTask_Pid3dGuiActive() == 0u)
        {
            pid_stop_output_now();
        }
#endif
        return;
    }

    // 判断有遥控信号才执行
    if (rc_in.fail_safe == 0)
    {
        // 判断第6通道拨杆位置 1300<CH_6<1700
        if (rc_in.rc_ch.st_data.ch_[ch_6_aux2] > 1300 && rc_in.rc_ch.st_data.ch_[ch_6_aux2] < 1700)
        {
            // 还没有执行
            if (one_key_takeoff_f == 0)
            {
                // 标记已经执行
                one_key_takeoff_f =
                    // 执行一键起飞
                    OneKey_Takeoff(100); // 参数单位：厘米； 0：默认上位机设置的高度。
            }
        }
        else
        {
            // 复位标记，以便再次执行
            one_key_takeoff_f = 0;
        }
        //
        // PID解耦触发：
        // CH6高档 -> X轴PID
        // CH10高档 -> Y轴PID
        // CH7高档 -> Z轴PID
        {
            u8 trig_x = (rc_in.rc_ch.st_data.ch_[ch_6_aux2] > 1700 && rc_in.rc_ch.st_data.ch_[ch_6_aux2] < 2200) ? 1u : 0u;
            u8 trig_y = (rc_in.rc_ch.st_data.ch_[ch_10_aux6] > 1700 && rc_in.rc_ch.st_data.ch_[ch_10_aux6] < 2200) ? 1u : 0u;
            u8 trig_z = (rc_in.rc_ch.st_data.ch_[ch_7_aux3] > 1700 && rc_in.rc_ch.st_data.ch_[ch_7_aux3] < 2200) ? 1u : 0u;
            u8 trig_sum = (u8)(trig_x + trig_y + trig_z);
            u8 new_axis = trig_x ? 1u : (trig_y ? 2u : (trig_z ? 3u : 0u));

            // 同时触发多个轴时不执行，避免速度指令抢写
            if (trig_sum > 1u)
            {
                if (pid_multi_axis_warned == 0u)
                {
                    pid_multi_axis_warned = 1u;
                    String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "PID: multi-axis trigger");
                }
                one_key_mission_f = 0;
                one_key_mission_y_f = 0;
                one_key_mission_z_f = 0;
                mission_step = 0;
                mission_step_y = 0;
                mission_step_z = 0;
                pid_active_axis = 0;
                pid_stop_output_now();
                return;
            }
            else
            {
                pid_multi_axis_warned = 0u;
            }

            // 仅允许定点模式触发，避免非定点误触
            if (new_axis != 0u && fc_sta.fc_mode_sta != 2)
            {
                if (pid_need_mode2_warned == 0)
                {
                    pid_need_mode2_warned = 1;
                    String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "PID need Mode2(Pos)");
                }
                one_key_mission_f = 0;
                one_key_mission_y_f = 0;
                one_key_mission_z_f = 0;
                mission_step = 0;
                mission_step_y = 0;
                mission_step_z = 0;
                pid_active_axis = 0;
                pid_stop_output_now();
                return;
            }

            pid_need_mode2_warned = 0;

            // 轴切换时先停再切，避免残留状态串轴
            if (new_axis != pid_active_axis)
            {
                one_key_mission_f = 0;
                one_key_mission_y_f = 0;
                one_key_mission_z_f = 0;
                mission_step = 0;
                mission_step_y = 0;
                mission_step_z = 0;
                pid_stop_output_now();
                pid_active_axis = new_axis;
            }

            if (new_axis == 0u)
            {
                return;
            }

            if (new_axis == 1u && one_key_mission_f == 0)
            {
                one_key_mission_f = 1;
                mission_step = 1;
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, "PID X ARM (CH6)");
            }
            else if (new_axis == 2u && one_key_mission_y_f == 0)
            {
                one_key_mission_y_f = 1;
                mission_step_y = 1;
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, "PID Y ARM (CH10)");
            }
            else if (new_axis == 3u && one_key_mission_z_f == 0)
            {
                one_key_mission_z_f = 1;
                mission_step_z = 1;
                String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, "PID Z ARM (CH7)");
            }
        }

        if (pid_active_axis != 0u)
        {
#if PID_TEST_EN
            // 运行期间若离开定点模式，立即停任务便于遥控急停
            if (fc_sta.fc_mode_sta != 2)
            {
                one_key_mission_f = 0;
                one_key_mission_y_f = 0;
                one_key_mission_z_f = 0;
                mission_step = 0;
                mission_step_y = 0;
                mission_step_z = 0;
                pid_active_axis = 0;
                pid_stop_output_now();
                String_Info_Send(0xFF, STRING_INFO_COLOR_RED, "PID abort: Mode2 lost");
                return;
            }

            if (pid_active_axis == 1u)
            {
#if PID3D_EN
                pid_3d_task(&mission_step, 4u); /* PID3D: CH6 同时 X+Y（测试vx/vy联动稳定性） */
#else
                pid_ground_test_task(&mission_step);
#endif
            }
            else if (pid_active_axis == 2u)
            {
#if PID3D_EN
                pid_3d_task(&mission_step_y, 2u); /* PID3D: CH10 Y-axis only (gx=gz=0, gy=PID3D_GOAL_Y_CM) */
#else
                pid_ground_test_task_yz(&mission_step_y, 1u);
#endif
            }
            else if (pid_active_axis == 3u)
            {
                pid_ground_test_task_yz(&mission_step_z, 2u);
            }
#endif
        }
        else
        {
            mission_step = 0;
            mission_step_y = 0;
            mission_step_z = 0;
        }
    }
    ////////////////////////////////////////////////////////////////////////
}
