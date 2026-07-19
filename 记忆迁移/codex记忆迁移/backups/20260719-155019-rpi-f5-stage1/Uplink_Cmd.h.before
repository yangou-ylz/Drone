#ifndef __UPLINK_CMD_H
#define __UPLINK_CMD_H
/******************************************************************************
 * 上行指令模块（阶段1: F1 链路验证 + 阶段2: F2 参数运行时写入）
 * ----------------------------------------------------------------------------
 * 用途：
 *   电脑端通过匿名数传 → 凌霄IMU → STM32F407 发送上行帧；本模块负责
 *   解析协议白名单内的上行帧，通过 0xA0 异步回显到上位机。
 *
 * 阶段1：0xF1 灵活帧（仅链路验证用，不改飞控状态）
 *   - 帧格式：AA FF F1 LEN | s16 X | s16 Y | ... | SC AC
 *   - 回显：绿色 "F1: X=.. Y=.."
 *
 * 阶段2：0xF2 参数运行时写入（白名单内的目标坐标）
 *   - 帧格式：AA FF F2 05 | param_id(1B) | value(4B float LE) | SC AC
 *   - 白名单：仅以下 ID 接受，其他一律拒绝并红字回显
 *       0x01 = PID3D GOAL_X (cm)
 *       0x02 = PID3D GOAL_Y (cm)
 *       0x03 = PID3D GOAL_Z (cm)
 *   - 限幅：|value| <= PARAM_GOAL_LIMIT_CM；越界则 clamp 并 LOG "CLP"
 *   - 生效时机：任务启动时（PID3D step=1 初始化处）拍一次照锁定为 const，
 *               飞行中不会突变。需要重设目标 → 落地 → 写参 → 再起飞。
 *   - 默认值：上电时取自 PID3D_GOAL_X/Y/Z_CM 宏。
 *
 * 阶段2b：0xF3 三轴目标同时写入（一帧带 X+Y+Z）
 *   - 帧格式：AA FF F3 0C | x(4B float LE) | y(4B float LE) | z(4B float LE) | SC AC
 *   - 三轴各自独立限幅为 ±PARAM_GOAL_LIMIT_CM；任一轴被 clamp 则回显末尾带 "CLP"
 *   - 回显格式："P*=30.0,44.0,55.0" 或 "P*=500.0,44.0,55.0 CLP"（绿色）
 *   - 与 0xF2 共享 RAM 存储与 Getter，生效时机一致（任务启动时拍照）。
 *
 * 触发条件：
 *   - Uplink_Cmd_Init 在 All_Init 末尾调用一次；
 *   - Uplink_Cmd_Tick 在 50Hz 调度器内调用；
 *   - Uplink_Cmd_Dispatch 由 ANO_DT_LX 在帧校验通过后回调。
 *
 * 安全开关：
 *   - 编译宏 UPLINK_CMD_EN（默认 1）：置 0 时全部退化为空函数。
 *   - PARAM_WRITE_EN：阶段2 子开关，置 0 时只保留阶段1 行为。
 ******************************************************************************/

#include "SysConfig.h"

#ifndef UPLINK_CMD_EN
#define UPLINK_CMD_EN 1
#endif

#ifndef PARAM_WRITE_EN
#define PARAM_WRITE_EN 1
#endif

/* 阶段2 参数 ID 白名单（与上行协议绑定，不要随意改动数值） */
#define PARAM_ID_GOAL_X 0x01
#define PARAM_ID_GOAL_Y 0x02
#define PARAM_ID_GOAL_Z 0x03

/* 阶段2 安全限幅：目标坐标绝对值上限（单位 cm，5 米室内足够） */
#define PARAM_GOAL_LIMIT_CM 500.0f

/* 初始化：清状态机、回显缓冲，并把 goal 默认值写为 PID3D_GOAL_X/Y/Z_CM。 */
void Uplink_Cmd_Init(void);

/* 50Hz 调度器调用：异步把待回显的内容通过 0xA0 字符串帧送出（限频 10Hz）。 */
void Uplink_Cmd_Tick(void);

/* 由 ANO_DT_LX 在帧校验通过后回调。data 指向完整帧（含帧头）。
 * 调用方需保证 SC/AC 已校验通过。 */
void Uplink_Cmd_Dispatch(u8 *data, u8 len);

/* 阶段2 Getter：任务启动时由 User_Task 调用一次拍照锁定。
 * 返回当前 RAM 中保存的目标坐标（已做限幅）。 */
float Uplink_GetGoalX_Cm(void);
float Uplink_GetGoalY_Cm(void);
float Uplink_GetGoalZ_Cm(void);

/* 0x00 校验返回帧（ACK）发送骨架，阶段1/2 暂未挂载使用，预留给后续阶段。 */
void Uplink_Send_Ack(u8 id_get, u8 sc_get, u8 ac_get);

#endif
