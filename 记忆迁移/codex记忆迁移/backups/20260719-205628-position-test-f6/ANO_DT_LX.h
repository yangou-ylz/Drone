#ifndef __ANO_DT_LX_H
#define __ANO_DT_LX_H
//==引用
#include "SysConfig.h"

//==定义/声明
#define FUN_NUM_LEN 256
// 0xA0字符串帧单次最大发送长度，仅统计STR字段，不含前置COLOR字节
#define STRING_INFO_MAX_LEN 43
// 0xA0日志颜色定义，按官方协议：0黑 1红 2绿
#define STRING_INFO_COLOR_BLACK 0
#define STRING_INFO_COLOR_RED 1
#define STRING_INFO_COLOR_GREEN 2

typedef struct
{
	u8 D_Addr;		 // 目标地址
	u8 WTS;			 // wait to send等待发送标记
	u16 fre_ms;		 // 发送周期
	u16 time_cnt_ms; // 计时变量
} _dt_frame_st;

// cmd
typedef struct
{
	u8 CID;
	u8 CMD[10];
} _cmd_st;

// check
typedef struct
{
	u8 ID;
	u8 SC;
	u8 AC;
} _ck_st;

// param
typedef struct
{
	u16 par_id;
	s32 par_val;
} _par_st;

// 除了data帧的所有的数据帧结构体，包含帧头、目标地址、功能码、数据长度、数据区和校验字节
// 真正发送的是buffer, _dt_st和data拼接起来到buffer,最后一起发出去
typedef struct
{
	_dt_frame_st fun[FUN_NUM_LEN]; // 功能码（如0X41等等），这是一个数组，长度256（即256个功能码），每个功能码对应一个_dt_frame_st结构体，包含该功能码的目标地址、发送周期、计时变量等信息
	//
	u8 wait_ck; // 等待时间（用于CMD发送后等待校验返回的超时处理）
	//
	_cmd_st cmd_send; // CMD命令发送数据
	_ck_st ck_send;	  // CK校验发送数据
	_ck_st ck_back;	  // CK校验返回数据
	_par_st par_data; // 参数数据
} _dt_st;

//==数据声明
extern _dt_st dt;
//==函数声明
// static
static void ANO_DT_LX_Send_Data(u8 *dataToSend, u8 length);
static void ANO_DT_LX_Data_Receive_Anl(u8 *data, u8 len);

// public
//
void ANO_DT_Init(void);
void ANO_LX_Data_Exchange_Task(float dT_s);
void ANO_DT_LX_Data_Receive_Prepare(u8 data);
//
void CMD_Send(u8 dest_addr, _cmd_st *cmd);
void CK_Back(u8 dest_addr, _ck_st *ck);
void PAR_Back(u8 dest_addr, _par_st *par);
// 发0xA0字符串信息帧至凌霄IMU（UART5路径）
void String_Info_Send(u8 dest_addr, u8 color, const char *str);
#endif
