#include "Auto_Mission.h"
#include "ANO_DT_LX.h"
#include "ANO_LX.h"
#include "LX_FC_Fun.h"
#include "LX_FC_State.h"
#include "Uplink_Cmd.h"
#include "User_Task.h"

#define AUTO_TICK_MS 20u
/*
 * 4S LiPo 电压保护分层：
 * - 起飞前：空载/轻载电压低于15.2V时拒绝新任务，避免低余量起飞；
 * - 飞行中：14.4V只告警，14.0V持续2s才自动降落，13.6V持续200ms认为危急。
 */
#define AUTO_VOLT_TAKEOFF_MIN_100 1520u
#define AUTO_VOLT_WARN_100 1440u
#define AUTO_VOLT_LAND_100 1400u
#define AUTO_VOLT_CRITICAL_100 1360u
#define AUTO_VOLT_MAX_100 2600u
#define AUTO_VOLT_LAND_CONFIRM_TICKS 100u
#define AUTO_VOLT_CRITICAL_CONFIRM_TICKS 10u
#define AUTO_MODE2_STABLE_TICKS 100u
#define AUTO_GROUND_STABLE_TICKS 100u
#define AUTO_CMD_RETRY_TIMEOUT_TICKS 100u
#define AUTO_MODE2_TIMEOUT_TICKS 250u
#define AUTO_UNLOCK_TIMEOUT_TICKS 150u
#define AUTO_TAKEOFF_WAIT_TICKS 300u
#define AUTO_TAKEOFF_NO_LIFT_TICKS 500u
#define AUTO_TAKEOFF_MIN_LIFT_CM 15L
#define AUTO_TAKEOFF_CONFIRM_TICKS 10u
#define AUTO_LAND_WAIT_TICKS 400u
#define AUTO_IDLE_STATUS_GAP_TICKS 25u
#define AUTO_ACTIVE_STATUS_GAP_TICKS 10u
#define AUTO_F5_FRESH_MS 500u
#define AUTO_F5_AGE_UNKNOWN 65535u
#define AUTO_MANUAL_VEL_TIMEOUT_TICKS 15u

#define AUTO_PLAN_NONE 0u
#define AUTO_PLAN_MODE_ONLY 1u
#define AUTO_PLAN_DRYRUN 2u
#define AUTO_PLAN_REAL 3u
#define AUTO_PLAN_TAKEOFF_HOLD 4u

#define AUTO_RC_OWNER_AUTO 0u
#define AUTO_RC_OWNER_RC 1u

static u8 s_state;
static u8 s_last_cmd;
static u8 s_plan;
static u16 s_last_cmd_seq;
static u16 s_status_seq;
static u16 s_error;
static u16 s_status_flags;
static u16 s_height_cm;
static u16 s_hold_ms;
static u16 s_timeout_ms;
static u16 s_state_tick;
static u16 s_mode2_stable_tick;
static u16 s_status_gap_tick;
static u16 s_f5_age_ms;
static u32 s_last_f5_rx_cnt;
static u16 s_rx_f7_cnt;
static u16 s_err_cnt;
static u8 s_need_status_now;
static u8 s_rc_control_owner;
static s32 s_takeoff_alt_ref_cm;
static s32 s_takeoff_lift_max_cm;
static u16 s_takeoff_confirm_tick;
static u16 s_last_f7_seq;
static u16 s_last_move_seq;
static u16 s_last_vel_seq;
static s16 s_manual_vx_cmps;
static s16 s_manual_vy_cmps;
static s16 s_manual_yaw_dps;
static u16 s_manual_vel_timeout_tick;
static u16 s_volt_low_tick;
static u16 s_volt_critical_tick;
static u8 s_volt_warn_sent;

static void app(char *buf, u8 *idx, const char *str)
{
	u8 i = 0;
	while (str[i] != '\0' && *idx < STRING_INFO_MAX_LEN)
	{
		buf[*idx] = str[i];
		(*idx)++;
		i++;
	}
}

static void app_ch(char *buf, u8 *idx, char c)
{
	if (*idx < STRING_INFO_MAX_LEN)
	{
		buf[*idx] = c;
		(*idx)++;
	}
}

static void app_u16_dec(char *buf, u8 *idx, u16 v)
{
	char tmp[6];
	u8 n = 0;
	do
	{
		tmp[n++] = (char)('0' + (v % 10u));
		v /= 10u;
	} while (v > 0u && n < sizeof(tmp));
	while (n > 0u)
	{
		app_ch(buf, idx, tmp[--n]);
	}
}

static void app_s32_dec(char *buf, u8 *idx, s32 v)
{
	u32 mag;
	if (v < 0)
	{
		app_ch(buf, idx, '-');
		mag = (u32)(-v);
	}
	else
	{
		mag = (u32)v;
	}
	if (mag > 65535u)
	{
		mag = 65535u;
	}
	app_u16_dec(buf, idx, (u16)mag);
}

static void app_u8_hex(char *buf, u8 *idx, u8 v)
{
	const char hex[] = "0123456789ABCDEF";
	app_ch(buf, idx, hex[(v >> 4) & 0x0F]);
	app_ch(buf, idx, hex[v & 0x0F]);
}

static void app_u16_hex(char *buf, u8 *idx, u16 v)
{
	app_u8_hex(buf, idx, (u8)(v >> 8));
	app_u8_hex(buf, idx, (u8)(v & 0xFFu));
}

static void auto_log(u8 level, const char *head, u16 seq, u16 err)
{
	char msg[STRING_INFO_MAX_LEN + 1];
	u8 idx = 0;
	app(msg, &idx, "AUTO ");
	app(msg, &idx, head);
	app(msg, &idx, " seq=");
	app_u16_dec(msg, &idx, seq);
	if (err != AUTO_ERR_OK)
	{
		app(msg, &idx, " err=");
		app_u16_hex(msg, &idx, err);
	}
	msg[idx] = '\0';
	Uplink_Log(level, msg);
}

static void auto_log_takeoff_alt(u8 level, const char *head, s32 ref_cm, s32 cur_cm, s32 delta_cm)
{
	char msg[STRING_INFO_MAX_LEN + 1];
	u8 idx = 0;
	app(msg, &idx, "AUTO ");
	app(msg, &idx, head);
	app(msg, &idx, " b=");
	app_s32_dec(msg, &idx, ref_cm);
	app(msg, &idx, " h=");
	app_s32_dec(msg, &idx, cur_cm);
	app(msg, &idx, " d=");
	app_s32_dec(msg, &idx, delta_cm);
	msg[idx] = '\0';
	Uplink_Log(level, msg);
}

static u16 clamp_ms_from_ticks(u16 ticks)
{
	u32 ms = (u32)ticks * AUTO_TICK_MS;
	if (ms > 65535u)
	{
		ms = 65535u;
	}
	return (u16)ms;
}

static s16 clamp_alt_s16(s32 alt)
{
	if (alt > 32767L)
	{
		return 32767;
	}
	if (alt < -32768L)
	{
		return -32768;
	}
	return (s16)alt;
}

static u8 is_active_state(u8 st)
{
	return (st != AUTO_STATE_IDLE && st != AUTO_STATE_DONE && st != AUTO_STATE_ERROR) ? 1u : 0u;
}

static void clear_rt_output(void);
static void mark_status_now(void);
static void enter_state(u8 new_state, const char *name);
static void enter_state_quiet(u8 new_state);
static void manual_vel_stop_state(void);

static u8 auto_owns_rc_control(void)
{
	return (s_rc_control_owner == AUTO_RC_OWNER_AUTO) ? 1u : 0u;
}

static void acquire_auto_control(const char *reason)
{
	if (s_rc_control_owner != AUTO_RC_OWNER_AUTO)
	{
		s_rc_control_owner = AUTO_RC_OWNER_AUTO;
		clear_rt_output();
		mark_status_now();
		auto_log(UPLINK_LOG_WARN, reason, s_last_cmd_seq, AUTO_ERR_OK);
	}
}

static void release_rc_control(const char *reason)
{
	manual_vel_stop_state();
	UserTask_Pid3dStopFromGui();
	s_rc_control_owner = AUTO_RC_OWNER_RC;
	clear_rt_output();
	s_plan = AUTO_PLAN_NONE;
	s_error = AUTO_ERR_OK;
	enter_state(AUTO_STATE_IDLE, reason);
}

static void lock_rc_control(const char *reason)
{
	manual_vel_stop_state();
	UserTask_Pid3dStopFromGui();
	s_rc_control_owner = AUTO_RC_OWNER_AUTO;
	clear_rt_output();
	s_plan = AUTO_PLAN_NONE;
	s_error = AUTO_ERR_OK;
	enter_state(AUTO_STATE_IDLE, reason);
}

static void clear_rt_output(void)
{
	rt_tar.st_data.rol = 0;
	rt_tar.st_data.pit = 0;
	rt_tar.st_data.thr = 0;
	rt_tar.st_data.yaw_dps = 0;
	rt_tar.st_data.vel_x = 0;
	rt_tar.st_data.vel_y = 0;
	rt_tar.st_data.vel_z = 0;
}

static void manual_vel_stop_state(void)
{
	s_manual_vx_cmps = 0;
	s_manual_vy_cmps = 0;
	s_manual_yaw_dps = 0;
	s_manual_vel_timeout_tick = 0;
}

static s16 clamp_manual_s16(s16 v, s16 limit)
{
	if (v > limit)
	{
		return limit;
	}
	if (v < -limit)
	{
		return (s16)(-limit);
	}
	return v;
}

static void reset_takeoff_detect(void)
{
	s_takeoff_alt_ref_cm = fc_alt.st_data.alt_fu_cm;
	s_takeoff_lift_max_cm = 0;
	s_takeoff_confirm_tick = 0;
}

static s32 takeoff_delta_cm(void)
{
	s32 delta = fc_alt.st_data.alt_fu_cm - s_takeoff_alt_ref_cm;
	if (delta > s_takeoff_lift_max_cm)
	{
		s_takeoff_lift_max_cm = delta;
	}
	return delta;
}

static u8 voltage_sample_ok(void)
{
	return (fc_bat.st_data.voltage_100 > 0u &&
			fc_bat.st_data.voltage_100 <= AUTO_VOLT_MAX_100)
			   ? 1u
			   : 0u;
}

static u8 voltage_takeoff_ok(void)
{
	return (fc_bat.st_data.voltage_100 >= AUTO_VOLT_TAKEOFF_MIN_100 &&
			voltage_sample_ok() != 0u)
			   ? 1u
			   : 0u;
}

static u8 voltage_flight_ok(void)
{
	return (fc_bat.st_data.voltage_100 >= AUTO_VOLT_LAND_100 &&
			voltage_sample_ok() != 0u)
			   ? 1u
			   : 0u;
}

static u8 voltage_warn_now(void)
{
	return (fc_bat.st_data.voltage_100 < AUTO_VOLT_WARN_100 ||
			voltage_sample_ok() == 0u)
			   ? 1u
			   : 0u;
}

static u8 voltage_low_now(void)
{
	return (fc_bat.st_data.voltage_100 < AUTO_VOLT_LAND_100 ||
			voltage_sample_ok() == 0u)
			   ? 1u
			   : 0u;
}

static void voltage_runtime_reset(void)
{
	s_volt_low_tick = 0;
	s_volt_critical_tick = 0;
	s_volt_warn_sent = 0;
}

static u8 voltage_runtime_ok(void)
{
	u16 v = fc_bat.st_data.voltage_100;

	if (v < AUTO_VOLT_LAND_100 || voltage_sample_ok() == 0u)
	{
		if (s_volt_low_tick < 0xFFFFu)
		{
			s_volt_low_tick++;
		}
	}
	else
	{
		s_volt_low_tick = 0;
	}

	if (v < AUTO_VOLT_CRITICAL_100 || voltage_sample_ok() == 0u)
	{
		if (s_volt_critical_tick < 0xFFFFu)
		{
			s_volt_critical_tick++;
		}
	}
	else
	{
		s_volt_critical_tick = 0;
	}

	if (v < AUTO_VOLT_WARN_100 && s_volt_warn_sent == 0u)
	{
		auto_log(UPLINK_LOG_WARN, "VOLT_WARN", s_last_cmd_seq, AUTO_ERR_OK);
		s_volt_warn_sent = 1u;
		mark_status_now();
	}
	else if (v >= AUTO_VOLT_WARN_100)
	{
		s_volt_warn_sent = 0u;
	}

	if (s_volt_critical_tick >= AUTO_VOLT_CRITICAL_CONFIRM_TICKS ||
		s_volt_low_tick >= AUTO_VOLT_LAND_CONFIRM_TICKS)
	{
		return 0u;
	}
	return 1u;
}

static u8 module_state_ok(u8 sta)
{
	/* 手册0x0E状态：0无数据、1不可用、2正常、3良好。 */
	return (sta >= 2u) ? 1u : 0u;
}

static u8 ext_vel_ok(void)
{
	return module_state_ok(fc_ext_status.st_data.sta_g_vel);
}

static u8 ext_alt_ok(void)
{
	return module_state_ok(fc_ext_status.st_data.sta_alt_add);
}

static void refresh_flags(void)
{
	u16 flags = 0;
	if (voltage_flight_ok() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_VOLT_OK;
	}
	if (voltage_takeoff_ok() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_VOLT_TAKEOFF_OK;
	}
	if (voltage_warn_now() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_VOLT_WARN;
	}
	if (voltage_low_now() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_VOLT_LOW;
	}
	if (fc_sta.fc_mode_sta == 2u)
	{
		flags |= AUTO_STATUS_FLAG_MODE2;
	}
	if (fc_sta.unlock_sta != 0u)
	{
		flags |= AUTO_STATUS_FLAG_UNLOCKED;
	}
	flags |= AUTO_STATUS_FLAG_NO_XY_MOTION;
	if (s_f5_age_ms < AUTO_F5_FRESH_MS)
	{
		flags |= AUTO_STATUS_FLAG_F5_FRESH;
	}
	if (is_active_state(s_state))
	{
		flags |= AUTO_STATUS_FLAG_ACTIVE;
	}
	if (ext_vel_ok() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_EXT_VEL_OK;
	}
	if (ext_alt_ok() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_EXT_ALT_OK;
	}
	if (auto_owns_rc_control() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_RC_LOCKOUT;
	}
	if (rc_in.fail_safe != 0u)
	{
		flags |= AUTO_STATUS_FLAG_RC_FAILSAFE;
	}
	if (rc_in.no_signal != 0u)
	{
		flags |= AUTO_STATUS_FLAG_RC_NO_SIGNAL;
	}
	if (rc_in.hold_frame != 0u)
	{
		flags |= AUTO_STATUS_FLAG_RC_HOLD_FRAME;
	}
	s_status_flags = flags;
}

static void mark_status_now(void)
{
	s_need_status_now = 1;
}

static void set_error(u16 err, u8 to_error_state)
{
	s_error = err;
	s_err_cnt++;
	manual_vel_stop_state();
	UserTask_Pid3dStopFromGui();
	clear_rt_output();
	if (to_error_state != 0u)
	{
		s_state = AUTO_STATE_ERROR;
		s_plan = AUTO_PLAN_NONE;
		s_state_tick = 0;
		s_mode2_stable_tick = 0;
	}
	mark_status_now();
}

static void abort_land_with_error(u16 err, const char *name)
{
	s_error = err;
	s_err_cnt++;
	manual_vel_stop_state();
	UserTask_Pid3dStopFromGui();
	clear_rt_output();
	auto_log(UPLINK_LOG_ERR, name, s_last_cmd_seq, err);
	enter_state_quiet(AUTO_STATE_ABORT_LAND);
}

static void enter_state_quiet(u8 new_state)
{
	s_state = new_state;
	s_state_tick = 0;
	s_mode2_stable_tick = 0;
	if (new_state == AUTO_STATE_MODE2_REQUEST ||
		new_state == AUTO_STATE_MOVE_RUN ||
		new_state == AUTO_STATE_IDLE ||
		new_state == AUTO_STATE_DONE ||
		new_state == AUTO_STATE_ERROR)
	{
		voltage_runtime_reset();
	}
	mark_status_now();
}

static void enter_state(u8 new_state, const char *name)
{
	enter_state_quiet(new_state);
	if (name != 0)
	{
		auto_log(UPLINK_LOG_INFO, name, s_last_cmd_seq, AUTO_ERR_OK);
	}
}

static u8 require_key(u8 cmd)
{
	if (cmd == AUTO_CMD_REQUEST_MODE2 ||
		cmd == AUTO_CMD_DRYRUN_TAKEOFF_LAND ||
		cmd == AUTO_CMD_START_LOW_TAKEOFF_LAND ||
		cmd == AUTO_CMD_TAKEOFF_HOLD ||
		cmd == AUTO_CMD_RELEASE_RC ||
		cmd == AUTO_CMD_LOCK_RC)
	{
		return 1u;
	}
	return 0u;
}

static u8 validate_params(const _auto_mission_cmd_st *cmd)
{
	if (cmd->cmd == AUTO_CMD_START_LOW_TAKEOFF_LAND ||
		cmd->cmd == AUTO_CMD_DRYRUN_TAKEOFF_LAND)
	{
		if (cmd->height_cm < 30u || cmd->height_cm > 80u)
		{
			return 0u;
		}
		if (cmd->hold_ms < 1000u || cmd->hold_ms > 5000u)
		{
			return 0u;
		}
		if (cmd->timeout_ms < 5000u || cmd->timeout_ms > 60000u)
		{
			return 0u;
		}
	}
	else if (cmd->cmd == AUTO_CMD_TAKEOFF_HOLD)
	{
		if (cmd->height_cm < 30u || cmd->height_cm > 80u)
		{
			return 0u;
		}
		if (cmd->timeout_ms < 5000u || cmd->timeout_ms > 60000u)
		{
			return 0u;
		}
	}
	return 1u;
}

static u8 precheck_base(u8 require_locked, u8 require_mode2)
{
	if (voltage_takeoff_ok() == 0u)
	{
		set_error(AUTO_ERR_PRECHECK_VOLT, 0);
		return 0u;
	}
	if (require_locked != 0u && fc_sta.unlock_sta != 0u)
	{
		set_error(AUTO_ERR_PRECHECK_UNLOCK, 0);
		return 0u;
	}
	if (require_mode2 != 0u && fc_sta.fc_mode_sta != 2u)
	{
		set_error(AUTO_ERR_PRECHECK_MODE, 0);
		return 0u;
	}
	if (dt.wait_ck != 0u)
	{
		set_error(AUTO_ERR_PRECHECK_WAIT_CK, 0);
		return 0u;
	}
	if (ext_vel_ok() == 0u)
	{
		set_error(AUTO_ERR_PRECHECK_EXT_VEL, 0);
		return 0u;
	}
	if (ext_alt_ok() == 0u)
	{
		set_error(AUTO_ERR_PRECHECK_EXT_ALT, 0);
		return 0u;
	}
	s_error = AUTO_ERR_OK;
	mark_status_now();
	return 1u;
}

static u8 move_state_allows_start(void)
{
	/* 允许在F7起飞后的HOLD悬停窗口内由F9接管位移。
	 * 推荐由F7 TAKEOFF_HOLD起飞，后续正常降落走F7 LAND_ONLY。 */
	if (s_state == AUTO_STATE_HOLD &&
		(s_plan == AUTO_PLAN_REAL || s_plan == AUTO_PLAN_TAKEOFF_HOLD))
	{
		return 1u;
	}
	if (s_plan != AUTO_PLAN_NONE)
	{
		return 0u;
	}
	if (s_state == AUTO_STATE_IDLE ||
		s_state == AUTO_STATE_DONE ||
		s_state == AUTO_STATE_MOVE_HOLD)
	{
		return 1u;
	}
	return 0u;
}

static u8 move_axis_from_xyz(s16 x_cm, s16 y_cm, s16 z_cm, u8 requested_axis)
{
	if (requested_axis <= AUTO_MOVE_AXIS_XY)
	{
		return requested_axis;
	}
	if (z_cm != 0)
	{
		if (x_cm == 0 && y_cm == 0)
		{
			return AUTO_MOVE_AXIS_Z;
		}
		return AUTO_MOVE_AXIS_XYZ;
	}
	if (x_cm != 0 && y_cm != 0)
	{
		return AUTO_MOVE_AXIS_XY;
	}
	if (x_cm != 0)
	{
		return AUTO_MOVE_AXIS_X;
	}
	if (y_cm != 0)
	{
		return AUTO_MOVE_AXIS_Y;
	}
	return AUTO_MOVE_AXIS_XY;
}

static u8 move_params_ok(const _auto_move_cmd_st *cmd)
{
	if (cmd->x_cm > AUTO_MOVE_LIMIT_CM || cmd->x_cm < -AUTO_MOVE_LIMIT_CM)
	{
		return 0u;
	}
	if (cmd->y_cm > AUTO_MOVE_LIMIT_CM || cmd->y_cm < -AUTO_MOVE_LIMIT_CM)
	{
		return 0u;
	}
	if (cmd->z_cm > AUTO_MOVE_LIMIT_CM || cmd->z_cm < -AUTO_MOVE_LIMIT_CM)
	{
		return 0u;
	}
	return 1u;
}

static u8 move_precheck(void)
{
	if (voltage_flight_ok() == 0u)
	{
		set_error(AUTO_ERR_PRECHECK_VOLT, 0);
		return 0u;
	}
	if (fc_sta.fc_mode_sta != 2u)
	{
		set_error(AUTO_ERR_MOVE_DENY_MODE, 0);
		return 0u;
	}
	if (fc_sta.unlock_sta == 0u)
	{
		set_error(AUTO_ERR_MOVE_DENY_UNLOCK, 0);
		return 0u;
	}
	if (dt.wait_ck != 0u)
	{
		set_error(AUTO_ERR_PRECHECK_WAIT_CK, 0);
		return 0u;
	}
	if (ext_vel_ok() == 0u || ext_alt_ok() == 0u)
	{
		set_error(AUTO_ERR_MOVE_DENY_SENSOR, 0);
		return 0u;
	}
	s_error = AUTO_ERR_OK;
	return 1u;
}

static void go_done(void)
{
	clear_rt_output();
	s_plan = AUTO_PLAN_NONE;
	enter_state(AUTO_STATE_DONE, "DONE");
}

static void go_mode2_request(u8 plan)
{
	s_plan = plan;
	enter_state(AUTO_STATE_MODE2_REQUEST, "MODE2_REQ");
}

static void go_emergency(void)
{
	UserTask_Pid3dStopFromGui();
	clear_rt_output();
	s_error = AUTO_ERR_EMERGENCY_LOCK;
	s_err_cnt++;
	s_plan = AUTO_PLAN_NONE;
	enter_state(AUTO_STATE_EMERGENCY_LOCK, "EMERGENCY");
}

void Auto_Mission_Init(void)
{
	s_state = AUTO_STATE_IDLE;
	s_last_cmd = AUTO_CMD_QUERY_STATUS;
	s_plan = AUTO_PLAN_NONE;
	s_last_cmd_seq = 0;
	s_status_seq = 0;
	s_error = AUTO_ERR_OK;
	s_status_flags = AUTO_STATUS_FLAG_NO_XY_MOTION;
	s_height_cm = 40;
	s_hold_ms = 3000;
	s_timeout_ms = 30000;
	s_state_tick = 0;
	s_mode2_stable_tick = 0;
	s_status_gap_tick = 0;
	s_f5_age_ms = AUTO_F5_AGE_UNKNOWN;
	s_last_f5_rx_cnt = 0;
	s_last_f7_seq = 0;
	s_last_move_seq = 0;
	s_last_vel_seq = 0;
	s_rx_f7_cnt = 0;
	s_err_cnt = 0;
	s_need_status_now = 1;
	s_rc_control_owner = AUTO_RC_OWNER_AUTO;
	manual_vel_stop_state();
	reset_takeoff_detect();
	clear_rt_output();
}

void Auto_Mission_RecordProtocolError(u16 error, u8 cmd)
{
	s_last_cmd = cmd;
	set_error(error, 0);
	auto_log(UPLINK_LOG_ERR, "ERR", s_last_cmd_seq, error);
}

void Auto_Mission_OnCommand(const _auto_mission_cmd_st *cmd)
{
	if (cmd == 0)
	{
		return;
	}

	s_rx_f7_cnt++;
	s_last_cmd = cmd->cmd;

	if (cmd->ver != AUTO_PROTOCOL_VER)
	{
		set_error(AUTO_ERR_BAD_VER, 0);
		auto_log(UPLINK_LOG_ERR, "ERR", cmd->seq, AUTO_ERR_BAD_VER);
		return;
	}

	if (cmd->cmd != AUTO_CMD_QUERY_STATUS &&
		cmd->cmd != AUTO_CMD_EMERGENCY_LOCK &&
		cmd->seq == s_last_f7_seq)
	{
		set_error(AUTO_ERR_DUP_SEQ, 0);
		auto_log(UPLINK_LOG_WARN, "DUP", cmd->seq, AUTO_ERR_DUP_SEQ);
		return;
	}

	s_last_f7_seq = cmd->seq;
	s_last_cmd_seq = cmd->seq;

	if (require_key(cmd->cmd) != 0u && cmd->safety_key != AUTO_SAFETY_KEY)
	{
		set_error(AUTO_ERR_BAD_KEY, 0);
		auto_log(UPLINK_LOG_ERR, "ERR", cmd->seq, AUTO_ERR_BAD_KEY);
		return;
	}

	if (validate_params(cmd) == 0u)
	{
		set_error(AUTO_ERR_BAD_PARAM, 0);
		auto_log(UPLINK_LOG_ERR, "ERR", cmd->seq, AUTO_ERR_BAD_PARAM);
		return;
	}

	if (cmd->height_cm != 0u)
	{
		s_height_cm = cmd->height_cm;
	}
	if (cmd->hold_ms != 0u)
	{
		s_hold_ms = cmd->hold_ms;
	}
	if (cmd->timeout_ms != 0u)
	{
		s_timeout_ms = cmd->timeout_ms;
	}

	if (cmd->cmd == AUTO_CMD_EMERGENCY_LOCK)
	{
		acquire_auto_control("RC_LOCKOUT");
		go_emergency();
		auto_log(UPLINK_LOG_ERR, "EMERGENCY", cmd->seq, AUTO_ERR_EMERGENCY_LOCK);
		return;
	}
	if (cmd->cmd == AUTO_CMD_ABORT_LAND)
	{
		acquire_auto_control("RC_LOCKOUT");
		UserTask_Pid3dStopFromGui();
		s_error = AUTO_ERR_USER_ABORT;
		s_err_cnt++;
		clear_rt_output();
		enter_state(AUTO_STATE_ABORT_LAND, "ABORT_LAND");
		return;
	}
	if (cmd->cmd == AUTO_CMD_LAND_ONLY)
	{
		acquire_auto_control("RC_LOCKOUT");
		UserTask_Pid3dStopFromGui();
		clear_rt_output();
		s_error = AUTO_ERR_OK;
		s_plan = AUTO_PLAN_NONE;
		if (fc_sta.unlock_sta == 0u)
		{
			enter_state(AUTO_STATE_DONE, "LAND_DONE");
		}
		else
		{
			enter_state(AUTO_STATE_LAND_REQUEST, "LAND_ONLY");
		}
		return;
	}
	if (cmd->cmd == AUTO_CMD_CLEAR_ERROR)
	{
		UserTask_Pid3dStopFromGui();
		clear_rt_output();
		s_error = AUTO_ERR_OK;
		s_plan = AUTO_PLAN_NONE;
		enter_state(AUTO_STATE_IDLE, "CLEAR");
		return;
	}
	if (cmd->cmd == AUTO_CMD_RELEASE_RC)
	{
		release_rc_control("RC_RELEASE");
		return;
	}
	if (cmd->cmd == AUTO_CMD_LOCK_RC)
	{
		lock_rc_control("RC_LOCKOUT");
		return;
	}
	if (cmd->cmd == AUTO_CMD_QUERY_STATUS)
	{
		auto_log(UPLINK_LOG_INFO, "QUERY", cmd->seq, AUTO_ERR_OK);
		mark_status_now();
		return;
	}
	if (cmd->cmd == AUTO_CMD_PRECHECK)
	{
		enter_state(AUTO_STATE_PRECHECK, "PRECHECK");
		if (precheck_base(1u, 0u) != 0u)
		{
			auto_log(UPLINK_LOG_INFO, "PRECHECK_OK", cmd->seq, AUTO_ERR_OK);
			enter_state(AUTO_STATE_IDLE, "READY");
		}
		else
		{
			auto_log(UPLINK_LOG_ERR, "PRECHECK_FAIL", cmd->seq, s_error);
		}
		return;
	}
	if (cmd->cmd == AUTO_CMD_REQUEST_MODE2)
	{
		acquire_auto_control("RC_LOCKOUT");
		if (precheck_base(1u, 0u) != 0u)
		{
			go_mode2_request(AUTO_PLAN_MODE_ONLY);
		}
		else
		{
			auto_log(UPLINK_LOG_ERR, "MODE2_DENY", cmd->seq, s_error);
		}
		return;
	}
	if (cmd->cmd == AUTO_CMD_DRYRUN_TAKEOFF_LAND)
	{
		acquire_auto_control("RC_LOCKOUT");
		if (precheck_base(1u, 0u) != 0u)
		{
			go_mode2_request(AUTO_PLAN_DRYRUN);
		}
		else
		{
			auto_log(UPLINK_LOG_ERR, "DRY_DENY", cmd->seq, s_error);
		}
		return;
	}
	if (cmd->cmd == AUTO_CMD_START_LOW_TAKEOFF_LAND)
	{
		acquire_auto_control("RC_LOCKOUT");
		if ((cmd->flags & AUTO_FLAG_NO_XY_MOTION) == 0u)
		{
			set_error(AUTO_ERR_BAD_PARAM, 0);
			auto_log(UPLINK_LOG_ERR, "NO_XY_REQUIRED", cmd->seq, AUTO_ERR_BAD_PARAM);
			return;
		}
		if (precheck_base(1u, 0u) != 0u)
		{
			go_mode2_request(AUTO_PLAN_REAL);
		}
		else
		{
			auto_log(UPLINK_LOG_ERR, "START_DENY", cmd->seq, s_error);
		}
		return;
	}
	if (cmd->cmd == AUTO_CMD_TAKEOFF_HOLD)
	{
		acquire_auto_control("RC_LOCKOUT");
		if (precheck_base(1u, 0u) != 0u)
		{
			go_mode2_request(AUTO_PLAN_TAKEOFF_HOLD);
		}
		else
		{
			auto_log(UPLINK_LOG_ERR, "TAKEOFF_HOLD_DENY", cmd->seq, s_error);
		}
		return;
	}

	set_error(AUTO_ERR_BAD_CMD, 0);
	auto_log(UPLINK_LOG_ERR, "BAD_CMD", cmd->seq, AUTO_ERR_BAD_CMD);
}

void Auto_Mission_OnMoveCommand(const _auto_move_cmd_st *cmd)
{
	u8 axis_mode;
	u8 clamped;

	if (cmd == 0)
	{
		return;
	}

	s_last_cmd = AUTO_F9_CMD;

	if (cmd->ver != AUTO_PROTOCOL_VER)
	{
		set_error(AUTO_ERR_BAD_VER, 0);
		auto_log(UPLINK_LOG_ERR, "MOVE_ERR", cmd->seq, AUTO_ERR_BAD_VER);
		return;
	}

	if (cmd->cmd != AUTO_MOVE_CMD_QUERY &&
		cmd->cmd != AUTO_MOVE_CMD_STOP &&
		cmd->seq == s_last_move_seq)
	{
		set_error(AUTO_ERR_DUP_SEQ, 0);
		auto_log(UPLINK_LOG_WARN, "MOVE_DUP", cmd->seq, AUTO_ERR_DUP_SEQ);
		return;
	}

	s_last_move_seq = cmd->seq;
	s_last_cmd_seq = cmd->seq;

	if (cmd->cmd == AUTO_MOVE_CMD_QUERY)
	{
		auto_log(UPLINK_LOG_INFO, "MOVE_QUERY", cmd->seq, AUTO_ERR_OK);
		mark_status_now();
		return;
	}

	if (cmd->cmd == AUTO_MOVE_CMD_STOP)
	{
		UserTask_Pid3dStopFromGui();
		clear_rt_output();
		s_plan = AUTO_PLAN_NONE;
		s_error = AUTO_ERR_OK;
		enter_state(AUTO_STATE_DONE, "MOVE_STOP");
		return;
	}

	if (cmd->cmd != AUTO_MOVE_CMD_START)
	{
		set_error(AUTO_ERR_BAD_CMD, 0);
		auto_log(UPLINK_LOG_ERR, "MOVE_BAD_CMD", cmd->seq, AUTO_ERR_BAD_CMD);
		return;
	}

	if (cmd->safety_key != AUTO_SAFETY_KEY)
	{
		set_error(AUTO_ERR_BAD_KEY, 0);
		auto_log(UPLINK_LOG_ERR, "MOVE_ERR", cmd->seq, AUTO_ERR_BAD_KEY);
		return;
	}

	if (move_params_ok(cmd) == 0u)
	{
		set_error(AUTO_ERR_BAD_PARAM, 0);
		auto_log(UPLINK_LOG_ERR, "MOVE_BAD_PARAM", cmd->seq, AUTO_ERR_BAD_PARAM);
		return;
	}

	if (move_state_allows_start() == 0u)
	{
		set_error(AUTO_ERR_MOVE_DENY_STATE, 0);
		auto_log(UPLINK_LOG_ERR, "MOVE_DENY_STATE", cmd->seq, AUTO_ERR_MOVE_DENY_STATE);
		return;
	}

	if (UserTask_Pid3dGuiActive() != 0u && UserTask_Pid3dGuiStep() == 3u)
	{
		set_error(AUTO_ERR_MOVE_BUSY, 0);
		auto_log(UPLINK_LOG_WARN, "MOVE_BUSY", cmd->seq, AUTO_ERR_MOVE_BUSY);
		return;
	}

	if (move_precheck() == 0u)
	{
		auto_log(UPLINK_LOG_ERR, "MOVE_DENY", cmd->seq, s_error);
		return;
	}

	acquire_auto_control("RC_LOCKOUT");
	clamped = Uplink_SetGoalXYZ_Cm((float)cmd->x_cm, (float)cmd->y_cm, (float)cmd->z_cm);
	axis_mode = move_axis_from_xyz(cmd->x_cm, cmd->y_cm, cmd->z_cm, cmd->axis_mode);
	if (UserTask_Pid3dStartFromGui(axis_mode) == 0u)
	{
		set_error(AUTO_ERR_MOVE_BUSY, 0);
		auto_log(UPLINK_LOG_WARN, "MOVE_BUSY", cmd->seq, AUTO_ERR_MOVE_BUSY);
		return;
	}

	s_error = AUTO_ERR_OK;
	s_plan = AUTO_PLAN_NONE;
	enter_state(AUTO_STATE_MOVE_RUN, (clamped != 0u) ? "MOVE_START_CLP" : "MOVE_START");
}

static u8 manual_vel_state_allows(void)
{
	if (auto_owns_rc_control() == 0u)
	{
		return 0u;
	}
	if (fc_sta.fc_mode_sta != 2u || fc_sta.unlock_sta == 0u)
	{
		return 0u;
	}
	if (s_state == AUTO_STATE_ABORT_LAND ||
		s_state == AUTO_STATE_EMERGENCY_LOCK ||
		s_state == AUTO_STATE_ERROR)
	{
		return 0u;
	}
	return 1u;
}

void Auto_Mission_OnVelocityCommand(const _auto_vel_cmd_st *cmd)
{
	s16 vx;
	s16 vy;
	s16 yaw;
	u8 clamped;
	u8 was_manual;

	if (cmd == 0)
	{
		return;
	}

	s_last_cmd = AUTO_FA_CMD;

	if (cmd->ver != AUTO_PROTOCOL_VER)
	{
		set_error(AUTO_ERR_BAD_VER, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_ERR", cmd->seq, AUTO_ERR_BAD_VER);
		return;
	}

	if (cmd->cmd != AUTO_VEL_CMD_QUERY &&
		cmd->cmd != AUTO_VEL_CMD_STOP &&
		cmd->seq == s_last_vel_seq)
	{
		set_error(AUTO_ERR_DUP_SEQ, 0);
		auto_log(UPLINK_LOG_WARN, "VEL_DUP", cmd->seq, AUTO_ERR_DUP_SEQ);
		return;
	}

	s_last_vel_seq = cmd->seq;
	s_last_cmd_seq = cmd->seq;

	if (cmd->cmd == AUTO_VEL_CMD_QUERY)
	{
		auto_log(UPLINK_LOG_INFO, "VEL_QUERY", cmd->seq, AUTO_ERR_OK);
		mark_status_now();
		return;
	}

	if (cmd->cmd == AUTO_VEL_CMD_STOP)
	{
		manual_vel_stop_state();
		clear_rt_output();
		if (s_state == AUTO_STATE_MANUAL_VEL)
		{
			s_plan = AUTO_PLAN_NONE;
			enter_state(AUTO_STATE_DONE, "VEL_STOP");
		}
		else
		{
			auto_log(UPLINK_LOG_INFO, "VEL_STOP", cmd->seq, AUTO_ERR_OK);
		}
		return;
	}

	if (cmd->cmd != AUTO_VEL_CMD_SET)
	{
		set_error(AUTO_ERR_BAD_CMD, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_BAD_CMD", cmd->seq, AUTO_ERR_BAD_CMD);
		return;
	}

	if (cmd->safety_key != AUTO_SAFETY_KEY)
	{
		set_error(AUTO_ERR_BAD_KEY, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_ERR", cmd->seq, AUTO_ERR_BAD_KEY);
		return;
	}

	if (auto_owns_rc_control() == 0u)
	{
		set_error(AUTO_ERR_VEL_DENY_RC, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_DENY_RC", cmd->seq, AUTO_ERR_VEL_DENY_RC);
		return;
	}

	if (manual_vel_state_allows() == 0u)
	{
		set_error(AUTO_ERR_VEL_DENY_STATE, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_DENY", cmd->seq, AUTO_ERR_VEL_DENY_STATE);
		return;
	}

	if (voltage_flight_ok() == 0u || ext_vel_ok() == 0u || ext_alt_ok() == 0u)
	{
		set_error(AUTO_ERR_PRECHECK_EXT_VEL, 0);
		auto_log(UPLINK_LOG_ERR, "VEL_DENY", cmd->seq, s_error);
		return;
	}

	UserTask_Pid3dStopFromGui();
	s_plan = AUTO_PLAN_NONE;
	manual_vel_stop_state();
	was_manual = (s_state == AUTO_STATE_MANUAL_VEL) ? 1u : 0u;
	vx = clamp_manual_s16(cmd->vx_cmps, AUTO_VEL_LIMIT_CMPS);
	vy = clamp_manual_s16(cmd->vy_cmps, AUTO_VEL_LIMIT_CMPS);
	yaw = clamp_manual_s16(cmd->yaw_dps, AUTO_YAW_LIMIT_DPS);
	clamped = (vx != cmd->vx_cmps || vy != cmd->vy_cmps || yaw != cmd->yaw_dps) ? 1u : 0u;
	s_manual_vx_cmps = vx;
	s_manual_vy_cmps = vy;
	s_manual_yaw_dps = yaw;
	s_manual_vel_timeout_tick = AUTO_MANUAL_VEL_TIMEOUT_TICKS;
	s_error = AUTO_ERR_OK;
	if (was_manual == 0u)
	{
		enter_state(AUTO_STATE_MANUAL_VEL, (clamped != 0u) ? "VEL_SET_CLP" : "VEL_SET");
	}
	else
	{
		mark_status_now();
	}
	if (clamped != 0u)
	{
		auto_log(UPLINK_LOG_WARN, "VEL_CLP", cmd->seq, AUTO_ERR_BAD_PARAM);
	}
}

static void tick_mode2_request(void)
{
	if (LX_Change_Mode(2u) != 0u)
	{
		enter_state(AUTO_STATE_MODE2_WAIT, "MODE2_WAIT");
	}
	else if (s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
	{
		set_error(AUTO_ERR_PRECHECK_WAIT_CK, 1u);
		auto_log(UPLINK_LOG_ERR, "MODE2_WAITCK", s_last_cmd_seq, AUTO_ERR_PRECHECK_WAIT_CK);
	}
}

static void tick_mode2_wait(void)
{
	if (fc_sta.fc_mode_sta == 2u)
	{
		if (s_mode2_stable_tick < 0xFFFFu)
		{
			s_mode2_stable_tick++;
		}
		if (s_mode2_stable_tick >= AUTO_MODE2_STABLE_TICKS)
		{
			if (s_plan == AUTO_PLAN_MODE_ONLY)
			{
				go_done();
			}
			else if (s_plan == AUTO_PLAN_DRYRUN)
			{
				enter_state(AUTO_STATE_DRY_UNLOCK, "DRY_UNLOCK");
			}
			else if (s_plan == AUTO_PLAN_REAL)
			{
				enter_state(AUTO_STATE_UNLOCK_REQUEST, "UNLOCK_REQ");
			}
			else if (s_plan == AUTO_PLAN_TAKEOFF_HOLD)
			{
				enter_state(AUTO_STATE_UNLOCK_REQUEST, "TAKEOFF_HOLD");
			}
			else
			{
				go_done();
			}
		}
	}
	else
	{
		s_mode2_stable_tick = 0;
		if (s_state_tick > AUTO_MODE2_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_MODE2_TIMEOUT, 1u);
			auto_log(UPLINK_LOG_ERR, "MODE2_TIMEOUT", s_last_cmd_seq, AUTO_ERR_MODE2_TIMEOUT);
		}
	}
}

static void tick_dryrun(void)
{
	switch (s_state)
	{
	case AUTO_STATE_DRY_UNLOCK:
		if (s_state_tick >= 50u)
			enter_state(AUTO_STATE_DRY_GROUND_STABLE, "DRY_GROUND");
		break;
	case AUTO_STATE_DRY_GROUND_STABLE:
		if (s_state_tick >= AUTO_GROUND_STABLE_TICKS)
			enter_state(AUTO_STATE_DRY_TAKEOFF, "DRY_TAKEOFF");
		break;
	case AUTO_STATE_DRY_TAKEOFF:
		if (s_state_tick >= 50u)
			enter_state(AUTO_STATE_DRY_HOLD, "DRY_HOLD");
		break;
	case AUTO_STATE_DRY_HOLD:
		if (clamp_ms_from_ticks(s_state_tick) >= s_hold_ms)
			enter_state(AUTO_STATE_DRY_LAND, "DRY_LAND");
		break;
	case AUTO_STATE_DRY_LAND:
		if (s_state_tick >= 50u)
			enter_state(AUTO_STATE_DRY_LOCK, "DRY_LOCK");
		break;
	case AUTO_STATE_DRY_LOCK:
		if (s_state_tick >= 50u)
			go_done();
		break;
	default:
		break;
	}
}

static void tick_real_mission(void)
{
	switch (s_state)
	{
	case AUTO_STATE_UNLOCK_REQUEST:
		if (FC_Unlock() != 0u)
		{
			enter_state(AUTO_STATE_WAIT_UNLOCK, "WAIT_UNLOCK");
		}
		else if (s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_PRECHECK_WAIT_CK, 1u);
			auto_log(UPLINK_LOG_ERR, "UNLOCK_WAITCK", s_last_cmd_seq, AUTO_ERR_PRECHECK_WAIT_CK);
		}
		break;
	case AUTO_STATE_WAIT_UNLOCK:
		if (fc_sta.unlock_sta != 0u)
		{
			enter_state(AUTO_STATE_GROUND_STABLE, "GROUND_STABLE");
		}
		else if (s_state_tick > AUTO_UNLOCK_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_UNLOCK_TIMEOUT, 1u);
			auto_log(UPLINK_LOG_ERR, "UNLOCK_TIMEOUT", s_last_cmd_seq, AUTO_ERR_UNLOCK_TIMEOUT);
		}
		break;
	case AUTO_STATE_GROUND_STABLE:
		if (s_state_tick >= AUTO_GROUND_STABLE_TICKS)
		{
			reset_takeoff_detect();
			auto_log_takeoff_alt(UPLINK_LOG_INFO, "TO_REF",
								  s_takeoff_alt_ref_cm,
								  fc_alt.st_data.alt_fu_cm,
								  0);
			enter_state_quiet(AUTO_STATE_TAKEOFF_REQUEST);
		}
		break;
	case AUTO_STATE_TAKEOFF_REQUEST:
		if (OneKey_Takeoff(s_height_cm) != 0u)
		{
			enter_state(AUTO_STATE_WAIT_TAKEOFF, "WAIT_TAKEOFF");
		}
		else if (s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_PRECHECK_WAIT_CK, 1u);
			auto_log(UPLINK_LOG_ERR, "TAKEOFF_WAITCK", s_last_cmd_seq, AUTO_ERR_PRECHECK_WAIT_CK);
		}
		break;
	case AUTO_STATE_WAIT_TAKEOFF:
	{
		s32 delta_cm = takeoff_delta_cm();
		if (delta_cm >= AUTO_TAKEOFF_MIN_LIFT_CM)
		{
			if (s_takeoff_confirm_tick < 0xFFFFu)
			{
				s_takeoff_confirm_tick++;
			}
		}
		else
		{
			s_takeoff_confirm_tick = 0;
		}

		if (s_takeoff_confirm_tick >= AUTO_TAKEOFF_CONFIRM_TICKS)
		{
			auto_log_takeoff_alt(UPLINK_LOG_INFO, "LIFT_OK",
								  s_takeoff_alt_ref_cm,
								  fc_alt.st_data.alt_fu_cm,
								  delta_cm);
			enter_state_quiet(AUTO_STATE_HOLD);
		}
		else if (clamp_ms_from_ticks(s_state_tick) > s_timeout_ms)
		{
			abort_land_with_error(AUTO_ERR_TAKEOFF_TIMEOUT, "TAKEOFF_TIMEOUT");
		}
		else if (s_state_tick >= AUTO_TAKEOFF_NO_LIFT_TICKS)
		{
			auto_log_takeoff_alt(UPLINK_LOG_ERR, "NO_LIFT",
								  s_takeoff_alt_ref_cm,
								  fc_alt.st_data.alt_fu_cm,
								  s_takeoff_lift_max_cm);
			abort_land_with_error(AUTO_ERR_TAKEOFF_NO_LIFT, "TAKEOFF_NO_LIFT");
		}
		else if (s_state_tick >= AUTO_TAKEOFF_WAIT_TICKS)
		{
			mark_status_now();
		}
		break;
	}
	case AUTO_STATE_HOLD:
		if (s_plan == AUTO_PLAN_REAL && clamp_ms_from_ticks(s_state_tick) >= s_hold_ms)
		{
			enter_state(AUTO_STATE_LAND_REQUEST, "LAND_REQ");
		}
		break;
	case AUTO_STATE_LAND_REQUEST:
		if (OneKey_Land() != 0u)
		{
			enter_state(AUTO_STATE_WAIT_LAND, "WAIT_LAND");
		}
		else if (s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_PRECHECK_WAIT_CK, 1u);
			auto_log(UPLINK_LOG_ERR, "LAND_WAITCK", s_last_cmd_seq, AUTO_ERR_PRECHECK_WAIT_CK);
		}
		break;
	case AUTO_STATE_WAIT_LAND:
		if (s_state_tick >= AUTO_LAND_WAIT_TICKS || fc_sta.unlock_sta == 0u)
		{
			enter_state(AUTO_STATE_LOCK_REQUEST, "LOCK_REQ");
		}
		else if (clamp_ms_from_ticks(s_state_tick) > s_timeout_ms)
		{
			set_error(AUTO_ERR_LAND_TIMEOUT, 1u);
			auto_log(UPLINK_LOG_ERR, "LAND_TIMEOUT", s_last_cmd_seq, AUTO_ERR_LAND_TIMEOUT);
		}
		break;
	case AUTO_STATE_LOCK_REQUEST:
		clear_rt_output();
		if (fc_sta.unlock_sta == 0u)
		{
			go_done();
		}
		else if (FC_Lock() != 0u)
		{
			/* Wait until the IMU reports locked before declaring DONE. */
		}
		else if (s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
		{
			set_error(AUTO_ERR_PRECHECK_WAIT_CK, 1u);
			auto_log(UPLINK_LOG_ERR, "LOCK_WAITCK", s_last_cmd_seq, AUTO_ERR_PRECHECK_WAIT_CK);
		}
		break;
	default:
		break;
	}
}

static void tick_abort_or_emergency(void)
{
	if (s_state == AUTO_STATE_ABORT_LAND)
	{
		clear_rt_output();
		if (OneKey_Land() != 0u || s_state_tick > AUTO_CMD_RETRY_TIMEOUT_TICKS)
		{
			enter_state(AUTO_STATE_WAIT_LAND, "ABORT_WAIT_LAND");
		}
	}
	else if (s_state == AUTO_STATE_EMERGENCY_LOCK)
	{
		clear_rt_output();
		(void)FC_Lock();
		if (fc_sta.unlock_sta == 0u && s_state_tick > 50u)
		{
			set_error(AUTO_ERR_EMERGENCY_LOCK, 1u);
		}
	}
}

static void move_runtime_fault(u16 err, const char *name)
{
	UserTask_Pid3dStopFromGui();
	clear_rt_output();
	set_error(err, 1u);
	auto_log(UPLINK_LOG_ERR, name, s_last_cmd_seq, err);
}

static void tick_move_control(void)
{
	if (s_state != AUTO_STATE_MOVE_RUN && s_state != AUTO_STATE_MOVE_HOLD)
	{
		return;
	}
	if (voltage_runtime_ok() == 0u)
	{
		move_runtime_fault(AUTO_ERR_RUNTIME_VOLT, "MOVE_VOLT");
		return;
	}
	if (fc_sta.fc_mode_sta != 2u)
	{
		move_runtime_fault(AUTO_ERR_RUNTIME_MODE, "MOVE_MODE");
		return;
	}
	if (fc_sta.unlock_sta == 0u)
	{
		move_runtime_fault(AUTO_ERR_MOVE_DENY_UNLOCK, "MOVE_LOCKED");
		return;
	}
	if (ext_vel_ok() == 0u || ext_alt_ok() == 0u)
	{
		move_runtime_fault(AUTO_ERR_RUNTIME_EXT, "MOVE_EXT");
		return;
	}

	UserTask_Pid3dTickFromGui();
	if (UserTask_Pid3dGuiActive() == 0u)
	{
		move_runtime_fault(AUTO_ERR_MOVE_TIMEOUT, "MOVE_TIMEOUT");
		return;
	}
	if (UserTask_Pid3dGuiStep() == 4u && s_state != AUTO_STATE_MOVE_HOLD)
	{
		enter_state(AUTO_STATE_MOVE_HOLD, "MOVE_HOLD");
	}
}

static void tick_manual_velocity(void)
{
	if (s_state != AUTO_STATE_MANUAL_VEL)
	{
		return;
	}
	if (voltage_runtime_ok() == 0u)
	{
		move_runtime_fault(AUTO_ERR_RUNTIME_VOLT, "VEL_VOLT");
		return;
	}
	if (auto_owns_rc_control() == 0u || fc_sta.fc_mode_sta != 2u || fc_sta.unlock_sta == 0u)
	{
		move_runtime_fault(AUTO_ERR_VEL_DENY_STATE, "VEL_DENY");
		return;
	}
	if (ext_vel_ok() == 0u || ext_alt_ok() == 0u)
	{
		move_runtime_fault(AUTO_ERR_RUNTIME_EXT, "VEL_EXT");
		return;
	}

	if (s_manual_vel_timeout_tick == 0u)
	{
		manual_vel_stop_state();
		clear_rt_output();
		s_plan = AUTO_PLAN_NONE;
		enter_state(AUTO_STATE_DONE, "VEL_TIMEOUT");
		auto_log(UPLINK_LOG_WARN, "VEL_TIMEOUT", s_last_cmd_seq, AUTO_ERR_VEL_TIMEOUT);
		return;
	}
	s_manual_vel_timeout_tick--;
	rt_tar.st_data.rol = 0;
	rt_tar.st_data.pit = 0;
	rt_tar.st_data.thr = 0;
	rt_tar.st_data.yaw_dps = s_manual_yaw_dps;
	rt_tar.st_data.vel_x = s_manual_vx_cmps;
	rt_tar.st_data.vel_y = s_manual_vy_cmps;
	rt_tar.st_data.vel_z = 0;
	dt.fun[0x41].WTS = 1;
}

static u8 runtime_guard_state(void)
{
	switch (s_state)
	{
	case AUTO_STATE_UNLOCK_REQUEST:
	case AUTO_STATE_WAIT_UNLOCK:
	case AUTO_STATE_GROUND_STABLE:
	case AUTO_STATE_TAKEOFF_REQUEST:
	case AUTO_STATE_WAIT_TAKEOFF:
	case AUTO_STATE_HOLD:
		return 1u;
	default:
		return 0u;
	}
}

static void runtime_fault(u16 err, const char *name)
{
	clear_rt_output();
	if (fc_sta.unlock_sta != 0u)
	{
		s_error = err;
		s_err_cnt++;
		enter_state(AUTO_STATE_ABORT_LAND, name);
	}
	else
	{
		set_error(err, 1u);
	}
	auto_log(UPLINK_LOG_ERR, name, s_last_cmd_seq, err);
}

static void runtime_safety_guard(void)
{
	if ((s_plan != AUTO_PLAN_REAL && s_plan != AUTO_PLAN_TAKEOFF_HOLD) ||
		runtime_guard_state() == 0u)
	{
		return;
	}
	if (voltage_runtime_ok() == 0u)
	{
		runtime_fault(AUTO_ERR_RUNTIME_VOLT, "RUNTIME_VOLT");
		return;
	}
	if (fc_sta.fc_mode_sta != 2u)
	{
		runtime_fault(AUTO_ERR_RUNTIME_MODE, "RUNTIME_MODE");
		return;
	}
	if (ext_vel_ok() == 0u || ext_alt_ok() == 0u)
	{
		runtime_fault(AUTO_ERR_RUNTIME_EXT, "RUNTIME_EXT");
		return;
	}
}

void Auto_Mission_Tick_50Hz(void)
{
	_uplink_f5_snapshot_st snap;
	u8 active;
	u8 status_gap;

	if (s_state_tick < 0xFFFFu)
	{
		s_state_tick++;
	}

	if (Uplink_F5_GetSnapshot(&snap) != 0u)
	{
		if (snap.rx_cnt != s_last_f5_rx_cnt)
		{
			s_last_f5_rx_cnt = snap.rx_cnt;
			s_f5_age_ms = 0u;
		}
		else if (s_f5_age_ms < AUTO_F5_AGE_UNKNOWN - AUTO_TICK_MS)
		{
			s_f5_age_ms = (u16)(s_f5_age_ms + AUTO_TICK_MS);
		}
	}
	else
	{
		s_f5_age_ms = AUTO_F5_AGE_UNKNOWN;
	}

	refresh_flags();
	runtime_safety_guard();

	switch (s_state)
	{
	case AUTO_STATE_MODE2_REQUEST:
		tick_mode2_request();
		break;
	case AUTO_STATE_MODE2_WAIT:
		tick_mode2_wait();
		break;
	case AUTO_STATE_DRY_UNLOCK:
	case AUTO_STATE_DRY_GROUND_STABLE:
	case AUTO_STATE_DRY_TAKEOFF:
	case AUTO_STATE_DRY_HOLD:
	case AUTO_STATE_DRY_LAND:
	case AUTO_STATE_DRY_LOCK:
		tick_dryrun();
		break;
	case AUTO_STATE_UNLOCK_REQUEST:
	case AUTO_STATE_WAIT_UNLOCK:
	case AUTO_STATE_GROUND_STABLE:
	case AUTO_STATE_TAKEOFF_REQUEST:
	case AUTO_STATE_WAIT_TAKEOFF:
	case AUTO_STATE_HOLD:
	case AUTO_STATE_LAND_REQUEST:
	case AUTO_STATE_WAIT_LAND:
	case AUTO_STATE_LOCK_REQUEST:
		tick_real_mission();
		break;
	case AUTO_STATE_ABORT_LAND:
	case AUTO_STATE_EMERGENCY_LOCK:
		tick_abort_or_emergency();
		break;
	case AUTO_STATE_MOVE_RUN:
	case AUTO_STATE_MOVE_HOLD:
		tick_move_control();
		break;
	case AUTO_STATE_MANUAL_VEL:
		tick_manual_velocity();
		break;
	default:
		break;
	}

	active = is_active_state(s_state);
	status_gap = active ? AUTO_ACTIVE_STATUS_GAP_TICKS : AUTO_IDLE_STATUS_GAP_TICKS;
	if (s_status_gap_tick < 0xFFFFu)
	{
		s_status_gap_tick++;
	}
	if (s_need_status_now != 0u || s_status_gap_tick >= status_gap)
	{
		s_status_gap_tick = 0;
		s_need_status_now = 0;
		s_status_seq++;
		Auto_Mission_Status_Send(HW_ALL);
	}
}

void Auto_Mission_GetStatus(_auto_mission_status_st *out)
{
	if (out == 0)
	{
		return;
	}
	refresh_flags();
	out->ver = AUTO_PROTOCOL_VER;
	out->status_seq = s_status_seq;
	out->last_cmd_seq = s_last_cmd_seq;
	out->state = s_state;
	out->last_cmd = s_last_cmd;
	out->error = s_error;
	out->flags = s_status_flags;
	out->mode = fc_sta.fc_mode_sta;
	out->unlock = fc_sta.unlock_sta;
	out->voltage_100 = fc_bat.st_data.voltage_100;
	out->alt_cm = clamp_alt_s16(fc_alt.st_data.alt_fu_cm);
	out->state_ms = clamp_ms_from_ticks(s_state_tick);
	out->f5_age_ms = s_f5_age_ms;
	out->rx_f7_cnt = s_rx_f7_cnt;
	out->err_cnt = s_err_cnt;
}

u8 Auto_Mission_RcControlAllowed(void)
{
	return (s_rc_control_owner == AUTO_RC_OWNER_RC) ? 1u : 0u;
}
