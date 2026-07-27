#ifndef __AUTO_MISSION_H
#define __AUTO_MISSION_H

#include "SysConfig.h"

/*
 * 方案A：STM32主导自主任务状态机。
 *
 * GUI只发送0xF7触发命令；树莓派0xF5位置观测保留接口，但当前自主起降阶段
 * 不依赖SLAM，不写XY速度，不触发0x41水平控制。
 */

#define AUTO_F7_CMD 0xF7
#define AUTO_F7_DATA_LEN 0x10
#define AUTO_F7_TOTAL_LEN 22

#define AUTO_F8_CMD 0xF8
#define AUTO_F8_DATA_LEN 0x19

#define AUTO_F9_CMD 0xF9
#define AUTO_F9_DATA_LEN 0x0F
#define AUTO_F9_TOTAL_LEN 21

#define AUTO_FA_CMD 0xFA
#define AUTO_FA_DATA_LEN 0x0E
#define AUTO_FA_TOTAL_LEN 20

#define AUTO_PROTOCOL_VER 1
#define AUTO_SAFETY_KEY 0xA55A

#define AUTO_FLAG_NO_XY_MOTION 0x0008
#define AUTO_MOVE_LIMIT_CM 200
#define AUTO_VEL_LIMIT_CMPS 30
#define AUTO_YAW_LIMIT_DPS 45

/* 0xF7 cmd */
#define AUTO_CMD_QUERY_STATUS 0x00
#define AUTO_CMD_PRECHECK 0x01
#define AUTO_CMD_REQUEST_MODE2 0x02
#define AUTO_CMD_DRYRUN_TAKEOFF_LAND 0x03
#define AUTO_CMD_START_LOW_TAKEOFF_LAND 0x04
#define AUTO_CMD_ABORT_LAND 0x05
#define AUTO_CMD_EMERGENCY_LOCK 0x06
#define AUTO_CMD_CLEAR_ERROR 0x07
#define AUTO_CMD_RELEASE_RC 0x08
#define AUTO_CMD_LOCK_RC 0x09
#define AUTO_CMD_TAKEOFF_HOLD 0x0A
#define AUTO_CMD_LAND_ONLY 0x0B

/* 0xF9 cmd：GUI相对位移控制。第一版只启动/停止现有PID3D，不管理起降。 */
#define AUTO_MOVE_CMD_QUERY 0x00
#define AUTO_MOVE_CMD_START 0x01
#define AUTO_MOVE_CMD_STOP 0x02

/* 0xFA cmd：GUI键盘低速速度控制。 */
#define AUTO_VEL_CMD_QUERY 0x00
#define AUTO_VEL_CMD_SET 0x01
#define AUTO_VEL_CMD_STOP 0x02

/* 0xF9 axis_mode：与 User_Task.c::pid_3d_task 保持一致。 */
#define AUTO_MOVE_AXIS_XYZ 0
#define AUTO_MOVE_AXIS_X 1
#define AUTO_MOVE_AXIS_Y 2
#define AUTO_MOVE_AXIS_Z 3
#define AUTO_MOVE_AXIS_XY 4

/* F8 state */
#define AUTO_STATE_IDLE 0
#define AUTO_STATE_PRECHECK 1
#define AUTO_STATE_MODE2_REQUEST 2
#define AUTO_STATE_MODE2_WAIT 3
#define AUTO_STATE_DRY_UNLOCK 4
#define AUTO_STATE_DRY_GROUND_STABLE 5
#define AUTO_STATE_DRY_TAKEOFF 6
#define AUTO_STATE_DRY_HOLD 7
#define AUTO_STATE_DRY_LAND 8
#define AUTO_STATE_DRY_LOCK 9
#define AUTO_STATE_UNLOCK_REQUEST 10
#define AUTO_STATE_WAIT_UNLOCK 11
#define AUTO_STATE_GROUND_STABLE 12
#define AUTO_STATE_TAKEOFF_REQUEST 13
#define AUTO_STATE_WAIT_TAKEOFF 14
#define AUTO_STATE_HOLD 15
#define AUTO_STATE_LAND_REQUEST 16
#define AUTO_STATE_WAIT_LAND 17
#define AUTO_STATE_LOCK_REQUEST 18
#define AUTO_STATE_DONE 19
#define AUTO_STATE_ABORT_LAND 20
#define AUTO_STATE_EMERGENCY_LOCK 21
#define AUTO_STATE_ERROR 22
#define AUTO_STATE_MOVE_RUN 23
#define AUTO_STATE_MOVE_HOLD 24
#define AUTO_STATE_MANUAL_VEL 25

/* F8 error */
#define AUTO_ERR_OK 0x0000
#define AUTO_ERR_BAD_LEN 0x0001
#define AUTO_ERR_BAD_VER 0x0002
#define AUTO_ERR_BAD_KEY 0x0003
#define AUTO_ERR_BAD_PARAM 0x0004
#define AUTO_ERR_DUP_SEQ 0x0005
#define AUTO_ERR_BAD_CMD 0x0006
#define AUTO_ERR_PRECHECK_VOLT 0x0010
#define AUTO_ERR_PRECHECK_MODE 0x0011
#define AUTO_ERR_PRECHECK_UNLOCK 0x0012
#define AUTO_ERR_PRECHECK_WAIT_CK 0x0013
#define AUTO_ERR_PRECHECK_EXT_VEL 0x0014
#define AUTO_ERR_PRECHECK_EXT_ALT 0x0015
#define AUTO_ERR_MODE2_TIMEOUT 0x0020
#define AUTO_ERR_UNLOCK_TIMEOUT 0x0030
#define AUTO_ERR_TAKEOFF_TIMEOUT 0x0040
#define AUTO_ERR_TAKEOFF_NO_LIFT 0x0041
#define AUTO_ERR_LAND_TIMEOUT 0x0050
#define AUTO_ERR_USER_ABORT 0x0060
#define AUTO_ERR_EMERGENCY_LOCK 0x0061
#define AUTO_ERR_RUNTIME_VOLT 0x0070
#define AUTO_ERR_RUNTIME_MODE 0x0071
#define AUTO_ERR_RUNTIME_EXT 0x0072
#define AUTO_ERR_MOVE_BUSY 0x0080
#define AUTO_ERR_MOVE_DENY_STATE 0x0081
#define AUTO_ERR_MOVE_DENY_MODE 0x0082
#define AUTO_ERR_MOVE_DENY_UNLOCK 0x0083
#define AUTO_ERR_MOVE_DENY_SENSOR 0x0084
#define AUTO_ERR_MOVE_TIMEOUT 0x0085
#define AUTO_ERR_VEL_DENY_RC 0x0090
#define AUTO_ERR_VEL_DENY_STATE 0x0091
#define AUTO_ERR_VEL_TIMEOUT 0x0092

/* F8 flags */
#define AUTO_STATUS_FLAG_VOLT_OK 0x0001
#define AUTO_STATUS_FLAG_MODE2 0x0002
#define AUTO_STATUS_FLAG_UNLOCKED 0x0004
#define AUTO_STATUS_FLAG_NO_XY_MOTION 0x0008
#define AUTO_STATUS_FLAG_F5_FRESH 0x0010
#define AUTO_STATUS_FLAG_ACTIVE 0x0020
#define AUTO_STATUS_FLAG_EXT_VEL_OK 0x0040
#define AUTO_STATUS_FLAG_EXT_ALT_OK 0x0080
#define AUTO_STATUS_FLAG_RC_LOCKOUT 0x0100
#define AUTO_STATUS_FLAG_RC_FAILSAFE 0x0200
#define AUTO_STATUS_FLAG_RC_NO_SIGNAL 0x0400
#define AUTO_STATUS_FLAG_RC_HOLD_FRAME 0x0800
#define AUTO_STATUS_FLAG_VOLT_TAKEOFF_OK 0x1000
#define AUTO_STATUS_FLAG_VOLT_WARN 0x2000
#define AUTO_STATUS_FLAG_VOLT_LOW 0x4000

typedef struct
{
	u8 ver;
	u16 seq;
	u8 cmd;
	u16 safety_key;
	u16 height_cm;
	u16 hold_ms;
	u16 flags;
	u16 timeout_ms;
	u16 reserved;
} _auto_mission_cmd_st;

typedef struct
{
	u8 ver;
	u16 seq;
	u8 cmd;
	u16 safety_key;
	s16 x_cm;
	s16 y_cm;
	s16 z_cm;
	u8 axis_mode;
	u16 flags;
} _auto_move_cmd_st;

typedef struct
{
	u8 ver;
	u16 seq;
	u8 cmd;
	u16 safety_key;
	s16 vx_cmps;
	s16 vy_cmps;
	s16 yaw_dps;
	u16 flags;
} _auto_vel_cmd_st;

typedef struct
{
	u8 ver;
	u16 status_seq;
	u16 last_cmd_seq;
	u8 state;
	u8 last_cmd;
	u16 error;
	u16 flags;
	u8 mode;
	u8 unlock;
	u16 voltage_100;
	s16 alt_cm;
	u16 state_ms;
	u16 f5_age_ms;
	u16 rx_f7_cnt;
	u16 err_cnt;
} _auto_mission_status_st;

void Auto_Mission_Init(void);
void Auto_Mission_Tick_50Hz(void);
void Auto_Mission_OnCommand(const _auto_mission_cmd_st *cmd);
void Auto_Mission_OnMoveCommand(const _auto_move_cmd_st *cmd);
void Auto_Mission_OnVelocityCommand(const _auto_vel_cmd_st *cmd);
void Auto_Mission_RecordProtocolError(u16 error, u8 cmd);
void Auto_Mission_GetStatus(_auto_mission_status_st *out);
u8 Auto_Mission_RcControlAllowed(void);

#endif
