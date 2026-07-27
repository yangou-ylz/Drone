#include "Auto_Mission.h"
#include "ANO_DT_LX.h"
#include "ANO_LX.h"
#include "LX_FC_Fun.h"
#include "LX_FC_State.h"
#include "Uplink_Cmd.h"

#define AUTO_TICK_MS 20u
#define AUTO_VOLT_MIN_100 900u
#define AUTO_VOLT_MAX_100 2600u
#define AUTO_MODE2_STABLE_TICKS 100u
#define AUTO_GROUND_STABLE_TICKS 100u
#define AUTO_CMD_RETRY_TIMEOUT_TICKS 100u
#define AUTO_MODE2_TIMEOUT_TICKS 250u
#define AUTO_UNLOCK_TIMEOUT_TICKS 150u
#define AUTO_TAKEOFF_WAIT_TICKS 300u
#define AUTO_LAND_WAIT_TICKS 400u
#define AUTO_IDLE_STATUS_GAP_TICKS 25u
#define AUTO_ACTIVE_STATUS_GAP_TICKS 5u
#define AUTO_F5_FRESH_MS 500u
#define AUTO_F5_AGE_UNKNOWN 65535u

#define AUTO_PLAN_NONE 0u
#define AUTO_PLAN_MODE_ONLY 1u
#define AUTO_PLAN_DRYRUN 2u
#define AUTO_PLAN_REAL 3u

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
	s_rc_control_owner = AUTO_RC_OWNER_RC;
	clear_rt_output();
	s_plan = AUTO_PLAN_NONE;
	s_error = AUTO_ERR_OK;
	enter_state(AUTO_STATE_IDLE, reason);
}

static void lock_rc_control(const char *reason)
{
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

static u8 voltage_ok(void)
{
	return (fc_bat.st_data.voltage_100 >= AUTO_VOLT_MIN_100 &&
			fc_bat.st_data.voltage_100 <= AUTO_VOLT_MAX_100)
			   ? 1u
			   : 0u;
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
	if (voltage_ok() != 0u)
	{
		flags |= AUTO_STATUS_FLAG_VOLT_OK;
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

static void enter_state(u8 new_state, const char *name)
{
	s_state = new_state;
	s_state_tick = 0;
	s_mode2_stable_tick = 0;
	mark_status_now();
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
	return 1u;
}

static u8 precheck_base(u8 require_locked, u8 require_mode2)
{
	if (voltage_ok() == 0u)
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
	s_rx_f7_cnt = 0;
	s_err_cnt = 0;
	s_need_status_now = 1;
	s_rc_control_owner = AUTO_RC_OWNER_AUTO;
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
		cmd->seq == s_last_cmd_seq)
	{
		set_error(AUTO_ERR_DUP_SEQ, 0);
		auto_log(UPLINK_LOG_WARN, "DUP", cmd->seq, AUTO_ERR_DUP_SEQ);
		return;
	}

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
		s_error = AUTO_ERR_USER_ABORT;
		s_err_cnt++;
		clear_rt_output();
		enter_state(AUTO_STATE_ABORT_LAND, "ABORT_LAND");
		return;
	}
	if (cmd->cmd == AUTO_CMD_CLEAR_ERROR)
	{
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

	set_error(AUTO_ERR_BAD_CMD, 0);
	auto_log(UPLINK_LOG_ERR, "BAD_CMD", cmd->seq, AUTO_ERR_BAD_CMD);
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
			enter_state(AUTO_STATE_TAKEOFF_REQUEST, "TAKEOFF_REQ");
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
		if (s_state_tick >= AUTO_TAKEOFF_WAIT_TICKS)
		{
			enter_state(AUTO_STATE_HOLD, "HOLD");
		}
		else if (clamp_ms_from_ticks(s_state_tick) > s_timeout_ms)
		{
			set_error(AUTO_ERR_TAKEOFF_TIMEOUT, 1u);
			auto_log(UPLINK_LOG_ERR, "TAKEOFF_TIMEOUT", s_last_cmd_seq, AUTO_ERR_TAKEOFF_TIMEOUT);
		}
		break;
	case AUTO_STATE_HOLD:
		if (clamp_ms_from_ticks(s_state_tick) >= s_hold_ms)
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
	if (s_plan != AUTO_PLAN_REAL || runtime_guard_state() == 0u)
	{
		return;
	}
	if (voltage_ok() == 0u)
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
