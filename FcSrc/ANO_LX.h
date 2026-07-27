#ifndef __ANO_LX_H
#define __ANO_LX_H
//==引用
#include "McuConfig.h"

//==定义/声明

enum
{
    ch_1_rol = 0,
    ch_2_pit,
    ch_3_thr,
    ch_4_yaw,
    ch_5_aux1,
    ch_6_aux2,
    ch_7_aux3,
    ch_8_aux4,
    ch_9_aux5,
    ch_10_aux6,
};

// 0x40
typedef struct
{
    s16 ch_[10]; //

} __attribute__((__packed__)) _rc_ch_st;

typedef union
{
    u8 byte_data[20];
    _rc_ch_st st_data;
} _rc_ch_un;

// 0x41：实时控制帧（目标姿态/速度）
// 存储飞控的期望控制目标（姿态、速度、油门），由遥控或程控指令生成，供飞控闭环控制算法（如PID）使用。
typedef struct
{
    s16 rol;     // 期望滚转角（单位：0.01度，如3500=35.00度）
    s16 pit;     // 期望俯仰角（单位：0.01度，负号与摇杆方向相反）
    s16 thr;     // 期望油门（单位：0.1%，如1000=100.0%）
    s16 yaw_dps; // 期望偏航角速度（单位：度/秒，逆时针为正）
    s16 vel_x;   // 期望头向速度（单位：厘米/秒，前飞为正）
    s16 vel_y;   // 期望左向速度（单位：厘米/秒，左移为正）
    s16 vel_z;   // 期望天向速度（单位：厘米/秒，上升为正）
} __attribute__((__packed__)) _rt_tar_st;

typedef union
{
    u8 byte_data[14];   // 字节流（14字节，对应协议数据区）
    _rt_tar_st st_data; // 结构化数据（目标控制量）
} _rt_tar_un;

// 0x0D：电池数据
typedef struct
{
    u16 voltage_100; // 电池电压（单位：10mV，如1250=12.50V）
    u16 current_100; // 电池电流（单位：10mA，如500=5.00A）
} __attribute__((__packed__)) _fc_bat_st;

typedef union
{
    u8 byte_data[4];    // 字节流（4字节）
    _fc_bat_st st_data; // 结构化数据（电池状态）
} _fc_bat_un;

// 0x05：高度数据（IMU下发，单位cm）
typedef struct
{
    s32 alt_fu_cm;  // 融合后高度
    s32 alt_add_cm; // 附加测距高度
    u8 alt_sta;     // 高度状态
} __attribute__((__packed__)) _fc_alt_st;

typedef union
{
    u8 byte_data[9];
    _fc_alt_st st_data;
} _fc_alt_un;

// 0x0E：外接模块工作状态（IMU下发）
typedef struct
{
    u8 sta_g_vel;   // 通用速度传感器状态：0无数据/1不可用/2正常/3良好
    u8 sta_g_pos;   // 通用位置传感器状态
    u8 sta_gps;     // GPS状态
    u8 sta_alt_add; // 附加测距高度状态
} __attribute__((__packed__)) _fc_ext_status_st;

typedef union
{
    u8 byte_data[4];
    _fc_ext_status_st st_data;
} _fc_ext_status_un;

// 0x03：姿态数据（欧拉角）
typedef struct
{
    s16 rol_x100; // 滚转角（单位：0.01度，如1234=12.34度）
    s16 pit_x100; // 俯仰角（单位：0.01度）
    s16 yaw_x100; // 偏航角（单位：0.01度）
    u8 state;     // 姿态状态（0=无效，1=有效）
} __attribute__((__packed__)) _fc_att_st;

typedef union
{
    u8 byte_data[7];    // 字节流（7字节）
    _fc_att_st st_data; // 结构化数据（欧拉角姿态）
} _fc_att_un;

// 0x04：姿态数据（四元数）
typedef struct
{
    s16 w_x10000; // 四元数w分量（单位：0.0001，如10000=1.0000）
    s16 x_x10000; // 四元数x分量
    s16 y_x10000; // 四元数y分量
    s16 z_x10000; // 四元数z分量
    u8 state;     // 姿态状态（0=无效，1=有效）
} __attribute__((__packed__)) _fc_att_qua_st;

typedef union
{
    u8 byte_data[9];        // 字节流（9字节）
    _fc_att_qua_st st_data; // 结构化数据（四元数姿态）
} _fc_att_qua_un;

// 0x07：速度数据
typedef struct
{
    s16 vel_x; // 头向速度（单位：厘米/秒，前飞为正）
    s16 vel_y; // 左向速度（单位：厘米/秒，左移为正）
    s16 vel_z; // 天向速度（单位：厘米/秒，上升为正）
} __attribute__((__packed__)) _fc_vel_st;

typedef union
{
    u8 byte_data[6];    // 字节流（6字节）
    _fc_vel_st st_data; // 结构化数据（速度）
} _fc_vel_un;

// 0x08：位置偏移（相对起飞点XY位移，单位cm）
typedef struct
{
    s32 pos_x; // 头向位置（单位：厘米，前为正）
    s32 pos_y; // 左向位置（单位：厘米，左为正）
} __attribute__((__packed__)) _fc_pos_st;

typedef union
{
    u8 byte_data[8]; // 字节流（8字节）
    _fc_pos_st st_data;
} _fc_pos_un;

// 0x41
typedef struct
{
    u16 pwm_m1;
    u16 pwm_m2;
    u16 pwm_m3;
    u16 pwm_m4;
    u16 pwm_m5;
    u16 pwm_m6;
    u16 pwm_m7;
    u16 pwm_m8;
} _pwm_st;

//==数据声明
extern _fc_att_un fc_att;
extern _fc_att_qua_un fc_att_qua;
extern _fc_vel_un fc_vel;
extern _fc_pos_un fc_pos;
extern _rt_tar_un rt_tar;
extern _fc_bat_un fc_bat;
extern _fc_alt_un fc_alt;
extern _fc_ext_status_un fc_ext_status;
extern _pwm_st pwm_to_esc;
//==函数声明
// static

// public
void ANO_LX_Task(void);

#endif
