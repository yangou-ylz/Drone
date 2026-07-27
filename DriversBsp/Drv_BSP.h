#ifndef _DRVBSP_H_
#define _DRVBSP_H_
#include "SysConfig.h"
#include "Drv_Sys.h"
#include "ANO_LX.h"

typedef struct
{
	u8 sig_mode; //0==null,1==ppm,2==sbus
	//
	s16 ppm_ch[9];
	//
	s16 sbus_ch[16];
	u8 sbus_flag;
	//
	u16 signal_fre;
	u8 no_signal;
	u8 fail_safe;
	u8 hold_frame; // SBUS持续输出完全相同的保持帧，常见于发射机关机但接收机仍输出hold帧
	_rc_ch_un rc_ch;
	u16 signal_cnt_tmp;
	u8 rc_in_mode_tmp;
} _rc_input_st;

//==数据声明
extern _rc_input_st rc_in;

u8 All_Init(void);

void DrvRcInputInit(void);
void DrvPpmGetOneCh(u16 data);
void DrvSbusGetOneByte(u8 data);
void DrvRcInputTask(float dT_s);

#endif
