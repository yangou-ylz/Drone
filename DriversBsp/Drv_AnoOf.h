#ifndef __DRV_ANO_OF_H
#define __DRV_ANO_OF_H

//==引用
#include "SysConfig.h"

//==定义/声明
#define ANO_OF_51_MAX_PAYLOAD_LEN 17

typedef struct
{
	// 下面这些数据都来自匿名光流模块的串口协议，由 AnoOF_GetOneByte/AnoOF_DataAnl 解析后填充。

	u8 of_update_cnt;  // 光流速度数据更新计数，收到 0x51-模式1 帧时自增。
	u8 alt_update_cnt; // 高度数据更新计数，收到 0x34 高度帧时自增。
	u8 raw_51_update_cnt; // 任意 0x51 mode 帧更新计数，用于DAP/现场诊断。

	u8 link_sta; // 链路状态：500ms 内收到过任意有效帧则为 1，否则为 0。
	u8 work_sta; // 工作状态：光流速度和高度数据都在持续更新时为 1，否则为 0。

	u8 of_quality; // 光流质量值，数值越大通常表示当前图像匹配质量越好。

	u16 rx_ok_cnt;      // 合法匿名帧累计数（UART4 光流入口）。
	u16 rx_addr_err_cnt; // 目标地址不匹配累计数。
	u16 rx_len_err_cnt; // 帧长度异常累计数。
	u16 rx_ck_err_cnt;  // SC/AC 校验错误累计数。
	u16 id_51_cnt;      // 0x51 光流帧累计数。
	u16 id_34_cnt;      // 0x34 测距帧累计数。
	u16 id_other_cnt;   // 其它合法帧累计数。
	u16 mode0_cnt;      // 0x51 MODE0 累计数。
	u16 mode1_cnt;      // 0x51 MODE1 累计数。
	u16 mode2_cnt;      // 0x51 MODE2 累计数。

	u8 raw_51_mode; // 最近一帧 0x51 的 MODE。
	u8 raw_51_len;  // 最近一帧 0x51 DATA 长度。
	u8 last_addr;   // 最近一帧/疑似帧的目标地址，辅助判断光流是否还在发给上位机0xAF。
	u8 raw_51_payload[ANO_OF_51_MAX_PAYLOAD_LEN]; // 最近一帧 0x51 DATA 区，按匿名标准原样保存，便于DAP诊断。

	u8 of0_sta; // 原始光流数据状态位，对应 0x51 帧中 data[4] == 0。
	s8 of0_dx;	// 原始光流 X 方向位移增量，未做高度/惯导融合。
	s8 of0_dy;	// 原始光流 Y 方向位移增量，未做高度/惯导融合。

	u8 of1_sta; // 高度融合后光流状态位，对应 0x51 帧中 data[4] == 1。
	s16 of1_dx; // 高度融合后的 X 方向速度/位移量，当前工程把它当作水平速度数据使用。
	s16 of1_dy; // 高度融合后的 Y 方向速度/位移量，当前工程把它当作水平速度数据使用。

	u8 of2_sta;		 // 惯导融合后光流状态位，对应 0x51 帧中 data[4] == 2。
	s16 of2_dx;		 // 惯导融合后的 X 方向原始输出。
	s16 of2_dy;		 // 惯导融合后的 Y 方向原始输出。
	s16 of2_dx_fix;	 // 惯导融合后修正过的 X 方向输出。
	s16 of2_dy_fix;	 // 惯导融合后修正过的 Y 方向输出。
	s16 intergral_x; // X 方向积分量，用于累计位移估计。
	s16 intergral_y; // Y 方向积分量，用于累计位移估计。

	u32 of_alt_cm; // 光流模块输出的测距高度，单位 cm，来自 0x34 高度帧。
	u8 of_alt_direction; // 最近 0x34 的方向字段。
	u16 of_alt_angle;    // 最近 0x34 的角度字段。

	float quaternion[4]; // 光流模块输出的姿态四元数，来自 0x04 姿态帧，缩放系数为 0.0001f。

	s16 acc_data_x; // 光流模块内置 IMU 的 X 轴加速度原始值，来自 0x01 惯性数据帧。
	s16 acc_data_y; // 光流模块内置 IMU 的 Y 轴加速度原始值。
	s16 acc_data_z; // 光流模块内置 IMU 的 Z 轴加速度原始值。
	s16 gyr_data_x; // 光流模块内置 IMU 的 X 轴角速度原始值。
	s16 gyr_data_y; // 光流模块内置 IMU 的 Y 轴角速度原始值。
	s16 gyr_data_z; // 光流模块内置 IMU 的 Z 轴角速度原始值。

} _ano_of_st;

// 飞控状态

//==数据声明
extern _ano_of_st ano_of;
//==函数声明
// static
static void AnoOF_DataAnl(uint8_t *data_buf, uint8_t num);

// public
void AnoOF_GetOneByte(uint8_t data);
void AnoOF_Check_State(float dT_s);
#endif
