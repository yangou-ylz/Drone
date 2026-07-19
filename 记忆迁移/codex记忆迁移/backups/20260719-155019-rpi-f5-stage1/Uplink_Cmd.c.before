/******************************************************************************
 * 上行指令模块（阶段1 + 阶段2 实现）
 * 详细说明见 Uplink_Cmd.h
 ******************************************************************************/

#include "Uplink_Cmd.h"
#include "ANO_DT_LX.h"
#include "User_Task.h" /* 提供 PID3D_GOAL_X/Y/Z_CM 宏作为默认值 */
#include "McuConfig.h" /* 提供 UartSendLXIMU 宏 */

#if UPLINK_CMD_EN

/* ---------- 内部状态：阶段1 F1 ---------- */

static s16 s_last_f1_x;
static s16 s_last_f1_y;
static u32 s_f1_rx_cnt;

/* ---------- 内部状态：阶段2 参数写入 ---------- */

#if PARAM_WRITE_EN
/* RAM 中保存的目标坐标（cm）。默认值在 Init 时取自 PID3D_GOAL_X/Y/Z_CM 宏。
 * 任务运行时不被本模块直接修改 PID 状态，只是被 User_Task 通过 Getter 拍照。 */
static float s_goal_x_cm;
static float s_goal_y_cm;
static float s_goal_z_cm;

/* 最近一次参数写入回显信息（供 Tick 异步发送） */
static u8 s_last_param_id;       /* 0 = 未知 ID */
static float s_last_param_value; /* 限幅后的值 */
static u8 s_last_param_clamped;  /* 1 = 写入时触发了限幅 */
static u8 s_last_param_unknown;  /* 1 = ID 不在白名单 */

/* 0xF3 三轴同时写入的回显状态（与 0xF2 状态不冲突） */
static float s_last_p3_x;    /* 限幅后的 X */
static float s_last_p3_y;    /* 限幅后的 Y */
static float s_last_p3_z;    /* 限幅后的 Z */
static u8 s_last_p3_clamped; /* 1 = 任一轴被限幅 */
#endif

/* ---------- 回显调度：两种内容共用一个队列 ---------- */

#define ECHO_KIND_NONE 0
#define ECHO_KIND_F1 1
#define ECHO_KIND_PARAM 2
#define ECHO_KIND_PARAM3 3 /* 0xF3 三轴同时写入的回显 */
static u8 s_echo_kind;

#define ECHO_MIN_TICK_GAP 5 /* 50Hz × 5tick = 100ms，最高 10Hz 回显 */
static u8 s_echo_gap_cnt;

/* ---------- 工具：把 s16 转十进制 ASCII ---------- */
static u8 s16_to_dec(s16 v, char *buf)
{
    u8 i = 0, j;
    u16 u;
    char tmp[6];

    if (v < 0)
    {
        buf[i++] = '-';
        u = (u16)(-(s32)v);
    }
    else
    {
        u = (u16)v;
    }

    j = 0;
    do
    {
        tmp[j++] = (char)('0' + (u % 10));
        u /= 10;
    } while (u > 0 && j < sizeof(tmp));

    while (j > 0)
    {
        buf[i++] = tmp[--j];
    }
    buf[i] = '\0';
    return i;
}

/* ---------- 工具：把 float 转 "<整数>.<一位小数>" ---------- */
#if PARAM_WRITE_EN
static u8 float_to_dec1(float v, char *buf)
{
    s32 v_int, v_frac;
    u8 idx = 0;
    u8 j;
    char tmp[12];

    if (v < 0.0f)
    {
        buf[idx++] = '-';
        v = -v;
    }
    v_int = (s32)v;
    v_frac = (s32)((v - (float)v_int) * 10.0f + 0.5f);
    if (v_frac >= 10)
    {
        v_int++;
        v_frac = 0;
    }
    j = 0;
    do
    {
        tmp[j++] = (char)('0' + (v_int % 10));
        v_int /= 10;
    } while (v_int > 0 && j < sizeof(tmp));
    while (j > 0)
    {
        buf[idx++] = tmp[--j];
    }
    buf[idx++] = '.';
    buf[idx++] = (char)('0' + v_frac);
    buf[idx] = '\0';
    return idx;
}
#endif

/* ---------- 阶段2 工具：参数 ID → 内部存储槽 ---------- */
#if PARAM_WRITE_EN
/* 返回 1=已写入（含限幅），0=ID 不在白名单 */
static u8 param_apply(u8 id, float value, float *out_clamped_value, u8 *out_clamped_flag)
{
    float v = value;
    u8 clamped = 0;

    /* 通用限幅（三个目标点共用同一阈值） */
    if (v > PARAM_GOAL_LIMIT_CM)
    {
        v = PARAM_GOAL_LIMIT_CM;
        clamped = 1;
    }
    else if (v < -PARAM_GOAL_LIMIT_CM)
    {
        v = -PARAM_GOAL_LIMIT_CM;
        clamped = 1;
    }

    switch (id)
    {
    case PARAM_ID_GOAL_X:
        s_goal_x_cm = v;
        break;
    case PARAM_ID_GOAL_Y:
        s_goal_y_cm = v;
        break;
    case PARAM_ID_GOAL_Z:
        s_goal_z_cm = v;
        break;
    default:
        return 0; /* 白名单外，拒绝 */
    }

    *out_clamped_value = v;
    *out_clamped_flag = clamped;
    return 1;
}
#endif

/* ---------- 公共接口 ---------- */

void Uplink_Cmd_Init(void)
{
    s_last_f1_x = 0;
    s_last_f1_y = 0;
    s_echo_kind = ECHO_KIND_NONE;
    s_echo_gap_cnt = 0;
    s_f1_rx_cnt = 0;

#if PARAM_WRITE_EN
    /* 默认值取自编译期宏；上电后保持不变直到收到 0xF2 帧 */
    s_goal_x_cm = (float)PID3D_GOAL_X_CM;
    s_goal_y_cm = (float)PID3D_GOAL_Y_CM;
    s_goal_z_cm = (float)PID3D_GOAL_Z_CM;
    s_last_param_id = 0;
    s_last_param_value = 0.0f;
    s_last_param_clamped = 0;
    s_last_param_unknown = 0;
    s_last_p3_x = 0.0f;
    s_last_p3_y = 0.0f;
    s_last_p3_z = 0.0f;
    s_last_p3_clamped = 0;
#endif
}

#if PARAM_WRITE_EN
float Uplink_GetGoalX_Cm(void) { return s_goal_x_cm; }
float Uplink_GetGoalY_Cm(void) { return s_goal_y_cm; }
float Uplink_GetGoalZ_Cm(void) { return s_goal_z_cm; }
#else
float Uplink_GetGoalX_Cm(void) { return (float)PID3D_GOAL_X_CM; }
float Uplink_GetGoalY_Cm(void) { return (float)PID3D_GOAL_Y_CM; }
float Uplink_GetGoalZ_Cm(void) { return (float)PID3D_GOAL_Z_CM; }
#endif

void Uplink_Cmd_Dispatch(u8 *data, u8 len)
{
    u8 cmd;
    u8 data_len;

    if (data == 0 || len < 6)
    {
        return;
    }

    cmd = *(data + 2);
    data_len = *(data + 3);

    /* ---------- 阶段1：0xF1 灵活帧 ---------- */
    if (cmd == 0xF1)
    {
        if (data_len >= 4)
        {
            s_last_f1_x = (s16)((u16)(*(data + 4)) | ((u16)(*(data + 5)) << 8));
            s_last_f1_y = (s16)((u16)(*(data + 6)) | ((u16)(*(data + 7)) << 8));
            s_f1_rx_cnt++;
            /* F1 优先级低于 PARAM：只在 PARAM 未排队时占位 */
            if (s_echo_kind == ECHO_KIND_NONE)
            {
                s_echo_kind = ECHO_KIND_F1;
            }
        }
        return;
    }

#if PARAM_WRITE_EN
    /* ---------- 阶段2：0xF2 参数写入 ---------- */
    if (cmd == 0xF2)
    {
        u8 id;
        union
        {
            u8 bytes[4];
            float f;
        } cvt;
        float applied;
        u8 clamped_flag;

        /* DATA 必须至少 1+4 = 5 字节 */
        if (data_len < 5)
        {
            return;
        }
        id = *(data + 4);
        cvt.bytes[0] = *(data + 5);
        cvt.bytes[1] = *(data + 6);
        cvt.bytes[2] = *(data + 7);
        cvt.bytes[3] = *(data + 8);

        applied = 0.0f;
        clamped_flag = 0;
        if (param_apply(id, cvt.f, &applied, &clamped_flag))
        {
            s_last_param_id = id;
            s_last_param_value = applied;
            s_last_param_clamped = clamped_flag;
            s_last_param_unknown = 0;
        }
        else
        {
            s_last_param_id = id; /* 仍记录原始 ID 用于回显 */
            s_last_param_value = 0.0f;
            s_last_param_clamped = 0;
            s_last_param_unknown = 1;
        }
        /* PARAM 优先级高于 F1：直接覆盖 */
        s_echo_kind = ECHO_KIND_PARAM;
        return;
    }

    /* ---------- 阶段2b：0xF3 三轴同时写入 ---------- */
    if (cmd == 0xF3)
    {
        union
        {
            u8 bytes[4];
            float f;
        } cx, cy, cz;
        float ax, ay, az;
        u8 cf_x, cf_y, cf_z;

        /* DATA 必须 3*4 = 12 字节 */
        if (data_len < 12)
        {
            return;
        }
        cx.bytes[0] = *(data + 4);
        cx.bytes[1] = *(data + 5);
        cx.bytes[2] = *(data + 6);
        cx.bytes[3] = *(data + 7);
        cy.bytes[0] = *(data + 8);
        cy.bytes[1] = *(data + 9);
        cy.bytes[2] = *(data + 10);
        cy.bytes[3] = *(data + 11);
        cz.bytes[0] = *(data + 12);
        cz.bytes[1] = *(data + 13);
        cz.bytes[2] = *(data + 14);
        cz.bytes[3] = *(data + 15);

        /* 复用 param_apply，保证三轴使用同一限幅/存储逻辑 */
        ax = 0.0f;
        ay = 0.0f;
        az = 0.0f;
        cf_x = 0;
        cf_y = 0;
        cf_z = 0;
        (void)param_apply(PARAM_ID_GOAL_X, cx.f, &ax, &cf_x);
        (void)param_apply(PARAM_ID_GOAL_Y, cy.f, &ay, &cf_y);
        (void)param_apply(PARAM_ID_GOAL_Z, cz.f, &az, &cf_z);

        s_last_p3_x = ax;
        s_last_p3_y = ay;
        s_last_p3_z = az;
        s_last_p3_clamped = (u8)(cf_x | cf_y | cf_z);
        s_echo_kind = ECHO_KIND_PARAM3;
        return;
    }
#endif
}

void Uplink_Cmd_Tick(void)
{
    char buf[STRING_INFO_MAX_LEN + 1];
    u8 idx;
    u8 color;
    u8 i;

    /* 限频计数 */
    if (s_echo_gap_cnt < 0xFF)
    {
        s_echo_gap_cnt++;
    }

    if (s_echo_kind == ECHO_KIND_NONE || s_echo_gap_cnt < ECHO_MIN_TICK_GAP)
    {
        return;
    }

    idx = 0;
    color = STRING_INFO_COLOR_GREEN;

    if (s_echo_kind == ECHO_KIND_F1)
    {
        const char *prefix = "F1: X=";
        const char *mid = " Y=";
        for (i = 0; prefix[i] != '\0' && idx < STRING_INFO_MAX_LEN; i++)
            buf[idx++] = prefix[i];
        idx += s16_to_dec(s_last_f1_x, &buf[idx]);
        for (i = 0; mid[i] != '\0' && idx < STRING_INFO_MAX_LEN; i++)
            buf[idx++] = mid[i];
        idx += s16_to_dec(s_last_f1_y, &buf[idx]);
    }
#if PARAM_WRITE_EN
    else if (s_echo_kind == ECHO_KIND_PARAM)
    {
        /* 格式：
         *   成功：     "P01=50.0"          绿
         *   触发限幅： "P01=500.0 CLP"      绿
         *   未知 ID：  "P?? UNK"            红
         */
        if (s_last_param_unknown)
        {
            color = STRING_INFO_COLOR_RED;
            buf[idx++] = 'P';
            /* 把 ID 以两位十六进制打印，方便快速识别 */
            {
                u8 hi = (u8)((s_last_param_id >> 4) & 0x0F);
                u8 lo = (u8)(s_last_param_id & 0x0F);
                buf[idx++] = (char)(hi < 10 ? ('0' + hi) : ('A' + hi - 10));
                buf[idx++] = (char)(lo < 10 ? ('0' + lo) : ('A' + lo - 10));
            }
            buf[idx++] = ' ';
            buf[idx++] = 'U';
            buf[idx++] = 'N';
            buf[idx++] = 'K';
        }
        else
        {
            buf[idx++] = 'P';
            {
                u8 hi = (u8)((s_last_param_id >> 4) & 0x0F);
                u8 lo = (u8)(s_last_param_id & 0x0F);
                buf[idx++] = (char)(hi < 10 ? ('0' + hi) : ('A' + hi - 10));
                buf[idx++] = (char)(lo < 10 ? ('0' + lo) : ('A' + lo - 10));
            }
            buf[idx++] = '=';
            idx += float_to_dec1(s_last_param_value, &buf[idx]);
            if (s_last_param_clamped && idx + 4 < STRING_INFO_MAX_LEN)
            {
                buf[idx++] = ' ';
                buf[idx++] = 'C';
                buf[idx++] = 'L';
                buf[idx++] = 'P';
            }
        }
    }
    else if (s_echo_kind == ECHO_KIND_PARAM3)
    {
        /* 格式："P*=30.0,44.0,55.0" 或末尾带 " CLP" */
        buf[idx++] = 'P';
        buf[idx++] = '*';
        buf[idx++] = '=';
        idx += float_to_dec1(s_last_p3_x, &buf[idx]);
        if (idx < STRING_INFO_MAX_LEN)
            buf[idx++] = ',';
        idx += float_to_dec1(s_last_p3_y, &buf[idx]);
        if (idx < STRING_INFO_MAX_LEN)
            buf[idx++] = ',';
        idx += float_to_dec1(s_last_p3_z, &buf[idx]);
        if (s_last_p3_clamped && idx + 4 < STRING_INFO_MAX_LEN)
        {
            buf[idx++] = ' ';
            buf[idx++] = 'C';
            buf[idx++] = 'L';
            buf[idx++] = 'P';
        }
    }
#endif
    else
    {
        s_echo_kind = ECHO_KIND_NONE;
        return;
    }

    if (idx > STRING_INFO_MAX_LEN)
        idx = STRING_INFO_MAX_LEN;
    buf[idx] = '\0';

    String_Info_Send(HW_ALL, color, buf);

    s_echo_kind = ECHO_KIND_NONE;
    s_echo_gap_cnt = 0;
}

/* ---------- 0x00 ACK 直发（暂未启用） ---------- */
void Uplink_Send_Ack(u8 id_get, u8 sc_get, u8 ac_get)
{
    u8 buf[9];
    u8 sc = 0, ac = 0;
    u8 i;

    buf[0] = 0xAA;
    buf[1] = 0xAF;
    buf[2] = 0x00;
    buf[3] = 0x03;
    buf[4] = id_get;
    buf[5] = sc_get;
    buf[6] = ac_get;

    for (i = 0; i < 7; i++)
    {
        sc += buf[i];
        ac += sc;
    }
    buf[7] = sc;
    buf[8] = ac;

    UartSendLXIMU(buf, 9);
}

#else /* UPLINK_CMD_EN == 0：全部退化为空函数，零开销 */

void Uplink_Cmd_Init(void) {}
void Uplink_Cmd_Tick(void) {}
void Uplink_Cmd_Dispatch(u8 *data, u8 len)
{
    (void)data;
    (void)len;
}
float Uplink_GetGoalX_Cm(void) { return (float)PID3D_GOAL_X_CM; }
float Uplink_GetGoalY_Cm(void) { return (float)PID3D_GOAL_Y_CM; }
float Uplink_GetGoalZ_Cm(void) { return (float)PID3D_GOAL_Z_CM; }
void Uplink_Send_Ack(u8 id_get, u8 sc_get, u8 ac_get)
{
    (void)id_get;
    (void)sc_get;
    (void)ac_get;
}

#endif /* UPLINK_CMD_EN */
