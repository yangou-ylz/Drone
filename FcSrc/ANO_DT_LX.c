#include "ANO_DT_LX.h"
#include "ANO_LX.h"
#include "Drv_RcIn.h"
#include "LX_FC_EXT_Sensor.h"
#include "Drv_led.h"
#include "LX_FC_State.h"
#include "Drv_Uart.h"
#include "Uplink_Cmd.h" /* 上行指令分发：F1/F2/F3/F5/F7/F9 */
#include "Auto_Mission.h"

/*==========================================================================
 * 描述    ：凌霄飞控通信主程序
 * 更新时间：2020-01-22
 * 作者		 ：匿名科创-茶不思
 * 官网    ：www.anotc.com
 * 淘宝    ：anotc.taobao.com
 * 技术Q群 ：190169595
 * 项目合作：18084888982，18061373080
============================================================================
 * 匿名科创团队感谢大家的支持，欢迎大家进群互相交流、讨论、学习。
 * 若您觉得匿名有不好的地方，欢迎您拍砖提意见。
 * 若您觉得匿名好，请多多帮我们推荐，支持我们。
 * 匿名开源程序代码欢迎您的引用、延伸和拓展，不过在希望您在使用时能注明出处。
 * 君子坦荡荡，小人常戚戚，匿名坚决不会请水军、请喷子，也从未有过抹黑同行的行为。
 * 开源不易，生活更不容易，希望大家互相尊重、互帮互助，共同进步。
 * 只有您的支持，匿名才能做得更好。
===========================================================================*/

u8 send_buffer[50]; // 发送数据缓存
_dt_st dt;

	// 0xA0帧内容暂存，由String_Info_Send写入，由Add_Send_Data在发送时读取
static u8 s_log_color;
static char s_log_str[STRING_INFO_MAX_LEN + 1];

static void add_s32_le(u8 *_cnt, u8 send_buffer[], s32 val)
{
	send_buffer[(*_cnt)++] = BYTE0(val);
	send_buffer[(*_cnt)++] = BYTE1(val);
	send_buffer[(*_cnt)++] = BYTE2(val);
	send_buffer[(*_cnt)++] = BYTE3(val);
}

static void add_u32_le(u8 *_cnt, u8 send_buffer[], u32 val)
{
	send_buffer[(*_cnt)++] = BYTE0(val);
	send_buffer[(*_cnt)++] = BYTE1(val);
	send_buffer[(*_cnt)++] = BYTE2(val);
	send_buffer[(*_cnt)++] = BYTE3(val);
}

static void add_u16_le(u8 *_cnt, u8 send_buffer[], u16 val)
{
	send_buffer[(*_cnt)++] = BYTE0(val);
	send_buffer[(*_cnt)++] = BYTE1(val);
}

static void add_s16_le(u8 *_cnt, u8 send_buffer[], s16 val)
{
	send_buffer[(*_cnt)++] = BYTE0(val);
	send_buffer[(*_cnt)++] = BYTE1(val);
}

// 将 u8 转为两位大写十六进制 ASCII，写入 buf[0]和buf[1]
static void u8_to_hex(u8 val, char *buf)
{
	const char hex[] = "0123456789ABCDEF";
	buf[0] = hex[val >> 4];
	buf[1] = hex[val & 0x0F];
}

//===================================================================
void ANO_DT_Init(void)
{
	//========定时触发
	// 0x0D：电压电流数据
	dt.fun[0x0d].D_Addr = 0xff;
	dt.fun[0x0d].fre_ms = 100;	  // 触发发送的周期100ms
	dt.fun[0x0d].time_cnt_ms = 1; // 设置初始相位，单位1ms
	// 0x40：遥控器数据
	dt.fun[0x40].D_Addr = 0xff;
	dt.fun[0x40].fre_ms = 20;	  // 触发发送的周期100ms
	dt.fun[0x40].time_cnt_ms = 0; // 设置初始相位，单位1ms

	//========外部触发
	// 0x30： GPS 传感器信息
	dt.fun[0x30].D_Addr = 0xff;
	dt.fun[0x30].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0x30].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0x33：速度传感器（光流）
	dt.fun[0x33].D_Addr = 0xff;
	dt.fun[0x33].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0x33].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0x34：测距传感器数据
	dt.fun[0x34].D_Addr = 0xff;
	dt.fun[0x34].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0x34].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0x41：实时控制帧
	dt.fun[0x41].D_Addr = 0xff;
	dt.fun[0x41].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0x41].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0xE0：CMD 命令帧
	dt.fun[0xe0].D_Addr = 0xff;
	dt.fun[0xe0].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0xe0].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0XE2: 参数写入、参数读取返回
	dt.fun[0xe2].D_Addr = 0xff;
	dt.fun[0xe2].fre_ms = 0;	  // 0 由外部触发
	dt.fun[0xe2].time_cnt_ms = 0; // 设置初始相位，单位1ms
	// 0xA0：字符串信息帧
	dt.fun[0xa0].D_Addr = 0xff;
	dt.fun[0xa0].fre_ms = 0; // 0 由外部触发
	dt.fun[0xa0].time_cnt_ms = 0;
	// 0xF6：树莓派位置镜像调试帧（STM32解析0xF5后下发给GUI）
	dt.fun[UPLINK_F6_CMD].D_Addr = 0xff;
	dt.fun[UPLINK_F6_CMD].fre_ms = 0;
	dt.fun[UPLINK_F6_CMD].time_cnt_ms = 0;
	// 0xF8：自主任务状态帧（STM32状态机 -> GUI）
	dt.fun[AUTO_F8_CMD].D_Addr = 0xff;
	dt.fun[AUTO_F8_CMD].fre_ms = 0;
	dt.fun[AUTO_F8_CMD].time_cnt_ms = 0;
}

// 数据发送接口
static void ANO_DT_LX_Send_Data(u8 *dataToSend, u8 length)
{
	//
	UartSendLXIMU(dataToSend, length);
}

//===================================================================
// 数据接收程序
//===================================================================
static u8 DT_RxBuffer[256], DT_data_cnt = 0; // 256个字节
void ANO_DT_LX_Data_Receive_Prepare(u8 data)
{
	static u8 _data_len = 0, _data_cnt = 0;
	static u8 rxstate = 0;

	// 判断帧头是否满足匿名协议的0xAA
	if (rxstate == 0 && data == 0xAA)
	{
		rxstate = 1;
		DT_RxBuffer[0] = data;
	}
	// 判断是不是发送给本模块的数据或者是广播数据
	else if (rxstate == 1 && (data == HW_TYPE || data == HW_ALL))
	{
		rxstate = 2;
		DT_RxBuffer[1] = data;
	}
	// 接收帧CMD字节
	else if (rxstate == 2)
	{
		rxstate = 3;
		DT_RxBuffer[2] = data;
	}
	// 接收数据长度字节
	else if (rxstate == 3 && data < 250)
	{
		rxstate = 4;
		DT_RxBuffer[3] = data;
		_data_len = data;
		_data_cnt = 0;
	}
	// 接收数据区
	else if (rxstate == 4 && _data_len > 0)
	{
		_data_len--;
		DT_RxBuffer[4 + _data_cnt++] = data;
		if (_data_len == 0)
			rxstate = 5;
	}
	// 接收校验字节1
	else if (rxstate == 5)
	{
		rxstate = 6;
		DT_RxBuffer[4 + _data_cnt++] = data;
	}
	// 接收校验字节2，表示一帧数据接收完毕，调用数据解析函数
	else if (rxstate == 6)
	{
		rxstate = 0;
		DT_RxBuffer[4 + _data_cnt] = data;
		DT_data_cnt = _data_cnt + 5;
		// ano_dt_data_ok = 1;
		ANO_DT_LX_Data_Receive_Anl(DT_RxBuffer, DT_data_cnt);
	}
	else
	{
		rxstate = 0;
	}
}
/////////////////////////////////////////////////////////////////////////////////////
// Data_Receive_Anl函数是协议数据解析函数，函数参数是符合协议格式的一个数据帧，该函数会首先对协议数据进行校验
// 校验通过后对数据进行解析，实现相应功能
// 此函数可以不用用户自行调用，由函数ANO_Data_Receive_Prepare自动调用
static void ANO_DT_LX_Data_Receive_Anl(u8 *data, u8 len)
{
	u8 check_sum1 = 0, check_sum2 = 0;
	// 判断数据长度是否正确
	if (*(data + 3) != (len - 6))
		return;
	// 根据收到的数据计算校验字节1和2
	for (u8 i = 0; i < len - 2; i++) // 从帧头 0xAA 字节开始，一直到 DATA 区结束
	{
		check_sum1 += *(data + i); // 和校验 SUM CHECK 计算方法：对每一字节进行累加操作，只取低 8 位
		check_sum2 += check_sum1;  // 附加校验 ADD CHECK 计算方法：计算和校验时，每进行一字节的加法运算，同时进行一次 SUM CHECK 的累加操作，只取低 8 位。
	}
	// 计算出的校验字节和收到的校验字节做对比，完全一致代表本帧数据合法，不一致则跳出解析函数
	if ((check_sum1 != *(data + len - 2)) || (check_sum2 != *(data + len - 1))) // 判断sum校验
	{
		if (*(data + 2) == UPLINK_F5_CMD)
		{
			Uplink_Cmd_Record_F5_Checksum_Error();
		}
		return;
	}
	// 再次判断帧头以及目标地址是否合法
	if (*(data) != 0xAA || (*(data + 1) != HW_TYPE && *(data + 1) != HW_ALL))
		return;
	//=============================================================================
	// 根据帧的CMD，也就是第3字节，进行对应数据的解析
	// PWM数据
	if (*(data + 2) == 0X20)
	{
		// data+4：DATA区第1字节（PWM1低字节），data+5：PWM1高字节
		// 转换为u16指针后解引用，得到16位PWM1值
		pwm_to_esc.pwm_m1 = *((u16 *)(data + 4)); // DATA区  从帧的第4字节开始，data + 4 指向 DATA区的第1个字节
		pwm_to_esc.pwm_m2 = *((u16 *)(data + 6)); //(u16 *)：将 uint8_t*类型的指针 强制转换 为 uint16_t *,告诉编译器，从 data + 4这个地址开始，往后2个字节是一个完整的u16类型数据”。
		pwm_to_esc.pwm_m3 = *((u16 *)(data + 8));
		pwm_to_esc.pwm_m4 = *((u16 *)(data + 10));
		pwm_to_esc.pwm_m5 = *((u16 *)(data + 12));
		pwm_to_esc.pwm_m6 = *((u16 *)(data + 14));
		pwm_to_esc.pwm_m7 = *((u16 *)(data + 16));
		pwm_to_esc.pwm_m8 = *((u16 *)(data + 18));

		//		若某0x20帧的DATA区为（16进制）：

		// 34 12 56 34 78 56 9A 78 BC 9A DE BC F0 DE 23 F0

		// （共16字节，8个PWM，小端模式）

		// 则解析结果为：

		// PWM1：0x1234（data+4=0x34，data+5=0x12 → 0x1234）

		// PWM2：0x3456（data+6=0x56，data+7=0x34 → 0x3456）

		// PWM3：0x5678（data+8=0x78，data+9=0x56 → 0x5678）

		//...以此类推
	}
	// 凌霄IMU发出的RGB灯光数据
	else if (*(data + 2) == 0X0f)
	{
		led.brightness[0] = *(data + 4);
		led.brightness[1] = *(data + 5);
		led.brightness[2] = *(data + 6);
		led.brightness[3] = *(data + 7);
	}
	// 凌霄飞控当前的运行状态
	else if (*(data + 2) == 0X06)
	{
		fc_sta.fc_mode_sta = *(data + 4);
		fc_sta.unlock_sta = *(data + 5);
		fc_sta.cmd_fun.CID = *(data + 6);
		fc_sta.cmd_fun.CMD_0 = *(data + 7);
		fc_sta.cmd_fun.CMD_1 = *(data + 8);
	}
	// 飞行速度
	else if (*(data + 2) == 0X07)
	{
		for (u8 i = 0; i < 6; i++)
		{
			fc_vel.byte_data[i] = *(data + 4 + i);
		}
	}
	// 高度数据（融合高度/附加测高/状态）
	else if (*(data + 2) == 0X05)
	{
		for (u8 i = 0; i < 9; i++)
		{
			fc_alt.byte_data[i] = *(data + 4 + i);
		}
	}
	// 外接模块工作状态（通用速度/位置/GPS/附加测高）
	else if (*(data + 2) == 0X0E)
	{
		for (u8 i = 0; i < 4; i++)
		{
			fc_ext_status.byte_data[i] = *(data + 4 + i);
		}
	}
	// XY位置偏移（相对起飞点，单位cm）
	else if (*(data + 2) == 0X08)
	{
		for (u8 i = 0; i < 8; i++)
		{
			fc_pos.byte_data[i] = *(data + 4 + i);
		}
	}
	// 姿态角（需要在上位机凌霄IMU界面配置输出功能）
	else if (*(data + 2) == 0X03)
	{
		for (u8 i = 0; i < 7; i++)
		{
			fc_att.byte_data[i] = *(data + 4 + i);
		}
	}
	// 姿态四元数
	else if (*(data + 2) == 0X04)
	{
		for (u8 i = 0; i < 9; i++)
		{
			fc_att_qua.byte_data[i] = *(data + 4 + i);
		}
	}
	// 传感器数据
	else if (*(data + 2) == 0X01)
	{
		/*
		acc_x = *((s16 *)(data + 4));
		acc_y = *((s16 *)(data + 6));
		acc_z = *((s16 *)(data + 8));
		gyr_x = *((s16 *)(data + 10));
		gyr_y = *((s16 *)(data + 12));
		gyr_z = *((s16 *)(data + 14));
		state = *(data + 16);
		*/
	}
	// 命令E0，具体命令格式及功能，参见匿名通信协议V7版
	else if (*(data + 2) == 0XE0)
	{
		// 根据命令ID：(*(data + 4)) ，来执行不同的命令
		switch (*(data + 4))
		{
		case 0x01:
		{
		}
		break;
		case 0x02:
		{
		}
		break;
		case 0x10:
		{
		}
		break;
		case 0x11:
		{
		}
		break;
		default:
			break;
		}
		// 收到命令后，需要返回对应的应答信息，也就是CK_Back函数
		dt.ck_send.ID = *(data + 4);
		dt.ck_send.SC = check_sum1;
		dt.ck_send.AC = check_sum2;
		CK_Back(SWJ_ADDR, &dt.ck_send);

		// 调试回显：向IMU发送绿色LOG，确认该CMD帧已成功接收
		// 格式："E0 CID=XX OK"，XX为CID的十六进制
		{
			char dbg_str[] = "E0 CID=XX OK";
			u8_to_hex(*(data + 4), &dbg_str[7]); // 将CID写入XX位置
			String_Info_Send(0xFF, STRING_INFO_COLOR_GREEN, dbg_str);
		}
	}
	// 收到的是ck返回
	else if (*(data + 2) == 0X00)
	{
		// 判断收到的CK信息和发送的CK信息是否相等
		if ((dt.ck_back.ID == *(data + 4)) && (dt.ck_back.SC == *(data + 5)) && (dt.ck_back.AC == *(data + 6)))
		{
			// 校验成功
			dt.wait_ck = 0;
		}
	}
	// 读取参数
	else if (*(data + 2) == 0XE1)
	{
		// 获取需要读取的参数的id
		u16 _par = *(data + 4) + *(data + 5) * 256;
		dt.par_data.par_id = _par;
		dt.par_data.par_val = 0;
		// 发送该参数
		PAR_Back(0xff, &dt.par_data);
	}
	// 写入参数
	else if (*(data + 2) == 0xE2)
	{
		// 目前凌霄开源MCU不涉及参数的写入，推荐大家直接使用源码方式调整自己定义的参数，故此处只返回对应的CK校验信息
		//		u16 _par = *(data+4)+*(data+5)*256;
		//		u32 _val = (s32)(((*(data+6))) + ((*(data+7))<<8) + ((*(data+8))<<16) + ((*(data+9))<<24));
		//
		dt.ck_send.ID = *(data + 4);
		dt.ck_send.SC = check_sum1;
		dt.ck_send.AC = check_sum2;
		CK_Back(0xff, &dt.ck_send);
		// 赋值参数
		// Parameter_Set(_par,_val);
	}
	// ==== 上行指令分发（阶段1/2/3a/6/7a）====
	// 0xF1：灵活链路验证帧（仅回显，不写飞控状态）
	// 0xF2：参数运行时写入帧（白名单：PID3D GOAL_X/Y/Z）
	// 0xF3：一帧同时写入三轴目标坐标
	// 0xF5：树莓派位置帧，当前仅解析/日志，不接控制输出
	// 0xF7：GUI自主任务命令
	// 0xF9：GUI相对位移命令
	// 注意：不要用 0xE0/0xE2，那两个 CMD 已被上方原生分支占用（CK_Back 协议）。
	else if (*(data + 2) == 0xF1)
	{
		Uplink_Cmd_Dispatch(data, len);
	}
	else if (*(data + 2) == 0xF2)
	{
		Uplink_Cmd_Dispatch(data, len);
	}
	else if (*(data + 2) == 0xF3)
	{
		/* 0xF3：一帧同时写入三轴目标坐标 */
		Uplink_Cmd_Dispatch(data, len);
	}
	else if (*(data + 2) == UPLINK_F5_CMD)
	{
		/* 0xF5：树莓派位置帧，阶段3a只保存快照和回0xA0日志 */
		Uplink_Cmd_Dispatch(data, len);
	}
	else if (*(data + 2) == AUTO_F7_CMD)
	{
		/* 0xF7：GUI自主任务命令，解析后交给Auto_Mission状态机 */
		Uplink_Cmd_Dispatch(data, len);
	}
	else if (*(data + 2) == AUTO_F9_CMD)
	{
		/* 0xF9：GUI相对位移命令，解析后交给Auto_Mission位移入口 */
		Uplink_Cmd_Dispatch(data, len);
	}
	}

//===================================================================
// 数据发送实现程序
//===================================================================
static void Add_Send_Data(u8 frame_num, u8 *_cnt, u8 send_buffer[])
{
	s16 temp_data;
	s32 temp_data_32;
	// 根据需要发送的帧ID，也就是frame_num，来填充数据，填充到send_buffer数组内
	switch (frame_num)
	{
	case 0x00: // CHECK返回
	{
		send_buffer[(*_cnt)++] = dt.ck_send.ID;
		send_buffer[(*_cnt)++] = dt.ck_send.SC;
		send_buffer[(*_cnt)++] = dt.ck_send.AC;
	}
	break;
	case 0x0d: // 电池数据
	{
		for (u8 i = 0; i < 4; i++)
		{
			send_buffer[(*_cnt)++] = fc_bat.byte_data[i];
		}
	}
	break;
	case 0x30: // GPS数据
	{
		//
		for (u8 i = 0; i < 23; i++)
		{
			send_buffer[(*_cnt)++] = ext_sens.fc_gps.byte[i];
		}
	}
	break;
	case 0x33: // 通用速度测量数据
	{
		//
		for (u8 i = 0; i < 6; i++)
		{
			send_buffer[(*_cnt)++] = ext_sens.gen_vel.byte[i];
		}
	}
	break;
	case 0x34: // 通用距离测量数据
	{
		//
		for (u8 i = 0; i < 7; i++)
		{
			send_buffer[(*_cnt)++] = ext_sens.gen_dis.byte[i];
		}
	}
	break;
	case 0x40: // 遥控数据帧
	{
		if (Auto_Mission_RcControlAllowed() == 0u)
		{
			/*
			 * AUTO锁定时不能把真实遥控摇杆继续透传给IMU。
			 * 否则遥控器开着且油门在低位时，Mode2会把前4通道视为非中位，
			 * 优先响应遥控输入，导致一键起飞命令被接受但实际无法离地。
			 */
			const s16 auto_rc_ch[10] = {
				1500, 1500, 1500, 1500, 1500,
				1250, 1500, 1500, 1500, 1500};
			for (u8 i = 0; i < 10; i++)
			{
				send_buffer[(*_cnt)++] = BYTE0(auto_rc_ch[i]);
				send_buffer[(*_cnt)++] = BYTE1(auto_rc_ch[i]);
			}
		}
		else
		{
			for (u8 i = 0; i < 20; i++)
			{
				send_buffer[(*_cnt)++] = rc_in.rc_ch.byte_data[i];
			}
		}
	}
	break;
	case 0x41: // 实时控制数据帧
	{
		for (u8 i = 0; i < 14; i++)
		{
			send_buffer[(*_cnt)++] = rt_tar.byte_data[i];
		}
	}
	break;
	case 0xe0: // CMD命令帧
	{
		send_buffer[(*_cnt)++] = dt.cmd_send.CID;
		for (u8 i = 0; i < 10; i++)
		{
			send_buffer[(*_cnt)++] = dt.cmd_send.CMD[i];
		}
	}
	break;
	case 0xe2: // PARA返回
	{
		temp_data = dt.par_data.par_id;
		send_buffer[(*_cnt)++] = BYTE0(temp_data);
		send_buffer[(*_cnt)++] = BYTE1(temp_data);
		temp_data_32 = dt.par_data.par_val;
		send_buffer[(*_cnt)++] = BYTE0(temp_data_32);
		send_buffer[(*_cnt)++] = BYTE1(temp_data_32);
		send_buffer[(*_cnt)++] = BYTE2(temp_data_32);
		send_buffer[(*_cnt)++] = BYTE3(temp_data_32);
	}
	break;
	case 0xa0: // 字符串信息帧，DATA首字节为颜色，后续ASCII字符串
	{
		u8 i = 0;
		send_buffer[(*_cnt)++] = s_log_color;
		while (i < STRING_INFO_MAX_LEN && s_log_str[i] != '\0')
		{
			send_buffer[(*_cnt)++] = (u8)s_log_str[i++];
		}
	}
	break;
	case UPLINK_F6_CMD: // 树莓派位置镜像帧，供GUI位置测试解析
	{
		_uplink_f5_snapshot_st snap;
		if (Uplink_F5_GetSnapshot(&snap) == 0)
		{
			break;
		}
		add_s32_le(_cnt, send_buffer, snap.cur_x_cm);
		add_s32_le(_cnt, send_buffer, snap.cur_y_cm);
		add_s32_le(_cnt, send_buffer, snap.cur_z_cm);
		add_s32_le(_cnt, send_buffer, snap.tar_x_cm);
		add_s32_le(_cnt, send_buffer, snap.tar_y_cm);
		add_s32_le(_cnt, send_buffer, snap.tar_z_cm);
		send_buffer[(*_cnt)++] = snap.flags;
		add_u32_le(_cnt, send_buffer, snap.rx_cnt);
		add_u32_le(_cnt, send_buffer, snap.len_err_cnt);
		add_u32_le(_cnt, send_buffer, snap.checksum_err_cnt);
	}
	break;
	case AUTO_F8_CMD: // 自主任务状态帧，供GUI显示/日志
	{
		_auto_mission_status_st st;
		Auto_Mission_GetStatus(&st);
		send_buffer[(*_cnt)++] = st.ver;
		add_u16_le(_cnt, send_buffer, st.status_seq);
		add_u16_le(_cnt, send_buffer, st.last_cmd_seq);
		send_buffer[(*_cnt)++] = st.state;
		send_buffer[(*_cnt)++] = st.last_cmd;
		add_u16_le(_cnt, send_buffer, st.error);
		add_u16_le(_cnt, send_buffer, st.flags);
		send_buffer[(*_cnt)++] = st.mode;
		send_buffer[(*_cnt)++] = st.unlock;
		add_u16_le(_cnt, send_buffer, st.voltage_100);
		add_s16_le(_cnt, send_buffer, st.alt_cm);
		add_u16_le(_cnt, send_buffer, st.state_ms);
		add_u16_le(_cnt, send_buffer, st.f5_age_ms);
		add_u16_le(_cnt, send_buffer, st.rx_f7_cnt);
		add_u16_le(_cnt, send_buffer, st.err_cnt);
	}
	break;
	default:
		break;
	}
}

//===================================================================

static void Frame_Send(u8 frame_num, _dt_frame_st *dt_frame)
{
	u8 _cnt = 0;

	send_buffer[_cnt++] = 0xAA;
	send_buffer[_cnt++] = dt_frame->D_Addr;
	send_buffer[_cnt++] = frame_num;
	send_buffer[_cnt++] = 0;
	//==
	// add_send_data
	Add_Send_Data(frame_num, &_cnt, send_buffer);
	//==
	send_buffer[3] = _cnt - 4;
	//==
	u8 check_sum1 = 0, check_sum2 = 0;
	for (u8 i = 0; i < _cnt; i++)
	{
		check_sum1 += send_buffer[i];
		check_sum2 += check_sum1;
	}
	send_buffer[_cnt++] = check_sum1;
	send_buffer[_cnt++] = check_sum2;
	//
	if (dt.wait_ck != 0 && frame_num == 0xe0)
	{
		dt.ck_back.ID = frame_num;
		dt.ck_back.SC = check_sum1;
		dt.ck_back.AC = check_sum2;
	}
	ANO_DT_LX_Send_Data(send_buffer, _cnt);
}
//===================================================================
//
static void Check_To_Send(u8 frame_num)
{
	// 1. 处理定时发送任务（已经发送）
	if (dt.fun[frame_num].fre_ms)
	{ // 若该帧配置了发送周期（fre_ms > 0）
		if (dt.fun[frame_num].time_cnt_ms < dt.fun[frame_num].fre_ms)
		{
			// 时间未到，递增计数器
			dt.fun[frame_num].time_cnt_ms++;
		}
		else
		{
			// 时间到，重置计数器并标记为待发送
			dt.fun[frame_num].time_cnt_ms = 1;
			dt.fun[frame_num].WTS = 1; // 标记等待发送
		}
	}
	else
	{
		// 无定时需求，等待外部触发（WTS由其他函数设置）
	}

	//------------------------------------------核心操作------------------------------------------
	// 2. 处理待发送任务
	if (dt.fun[frame_num].WTS)
	{											   // 若该帧被标记为待发送
		dt.fun[frame_num].WTS = 0;				   // 清除标记
		Frame_Send(frame_num, &dt.fun[frame_num]); // 实际发送数据
	}
}
//===================================================================

// CMD发送
void CMD_Send(u8 dest_addr, _cmd_st *cmd)
{
	dt.fun[0xe0].D_Addr = dest_addr;
	dt.fun[0xe0].WTS = 1; // 标记CMD等待发送
	dt.wait_ck = 1;		  // 标记等待校验
}
// CHECK返回
void CK_Back(u8 dest_addr, _ck_st *ck)
{
	dt.fun[0x00].D_Addr = dest_addr;
	dt.fun[0x00].WTS = 1; // 标记CMD等待发送
}
// PARA返回
void PAR_Back(u8 dest_addr, _par_st *par)
{
	dt.fun[0xe2].D_Addr = dest_addr;
	dt.fun[0xe2].WTS = 1; // 标记CMD等待发送
}
// 发退0xA0字符串信息帧至凌霄IMU（UART5路径）
void String_Info_Send(u8 dest_addr, u8 color, const char *str)
{
	u8 i = 0;
	if (str == 0)
		return;
	s_log_color = color;
	while (i < STRING_INFO_MAX_LEN && str[i] != '\0')
	{
		s_log_str[i] = str[i];
		i++;
	}
	s_log_str[i] = '\0';
	dt.fun[0xa0].D_Addr = dest_addr;
	dt.fun[0xa0].WTS = 1;
}

void Rpi_Position_Mirror_Send(u8 dest_addr)
{
	dt.fun[UPLINK_F6_CMD].D_Addr = dest_addr;
	dt.fun[UPLINK_F6_CMD].WTS = 1;
}

void Auto_Mission_Status_Send(u8 dest_addr)
{
	dt.fun[AUTO_F8_CMD].D_Addr = dest_addr;
	dt.fun[AUTO_F8_CMD].WTS = 1;
}

// 若指令没发送成功，会持续重新发送，间隔50ms。
static u8 repeat_cnt;
static inline void CK_Back_Check()
{
	static u8 time_dly;
	if (dt.wait_ck == 1)
	{
		if (time_dly < 50) // 50ms
		{
			time_dly++;
		}
		else
		{
			time_dly = 0;
			repeat_cnt++;
			if (repeat_cnt < 5)
			{
				dt.fun[0xe0].WTS = 1; // 标记等待发送，重发
			}
			else
			{
				repeat_cnt = 0;
				dt.wait_ck = 0;
			}
		}
	}
	else
	{
		time_dly = 0;
		repeat_cnt = 0;
	}
}

// 1ms调用一次，用于通信交换数据
void ANO_LX_Data_Exchange_Task(float dT_s)
{
	//=====检测CMD是否返回了校验
	CK_Back_Check();
	//=====检测是否触发发送
	Check_To_Send(0x30);
	Check_To_Send(0x33);
	Check_To_Send(0x34);
	Check_To_Send(0x40);
	Check_To_Send(0x41);
	Check_To_Send(0xe0);
	Check_To_Send(0xe2);
	Check_To_Send(0x0d);
	Check_To_Send(0xa0);
	Check_To_Send(UPLINK_F6_CMD);
	Check_To_Send(AUTO_F8_CMD);
}

//===================================================================
