# 项目模块结构详细说明

## 目录树

```
ANO_LX_FC/
├── FcSrc/                  ← 飞控核心逻辑（主要开发区域）
│   ├── main.c              ← 程序入口：All_Init() + Scheduler_Run()
│   ├── SysConfig.h         ← 全局类型/宏定义（u8/s16/vec3_f等）
│   ├── Ano_Scheduler.c/h   ← 裸机时分调度器（7个频率循环）
│   ├── User_Task.c/h       ← 用户逻辑唯一入口
│   ├── ANO_DT_LX.c/h       ← 凌霄通信协议核心（收发、解析）
│   ├── ANO_LX.c/h          ← 数据结构定义 + 遥控/程控数据处理
│   ├── LX_FC_Fun.c/h       ← 飞控功能API（解锁/上锁/模式/起降）
│   ├── LX_FC_State.c/h     ← 飞控状态机（fc_sta全局状态结构体）
│   └── LX_FC_EXT_Sensor.c/h← 外部传感器（光流/GPS/测距）数据结构
│
├── DriversBsp/             ← 板级支持包（跨MCU通用）
│   ├── Ano_Math.c/h        ← 数学库（三角函数等）
│   ├── Drv_AnoOf.c/h       ← 匿名光流驱动
│   ├── Drv_BSP.c/h         ← BSP总初始化（All_Init）
│   └── Drv_UbloxGPS.c/h    ← Ublox GPS解析
│
├── DriversMcu/STM32F407/   ← STM32F407专用底层驱动
│   ├── McuConfig.h         ← MCU级类型定义（u8/s16/s32等）
│   ├── Drivers/            ← 各外设驱动
│   │   ├── Drv_Uart.c/h    ← UART（含UartSendLXIMU函数）
│   │   ├── Drv_PwmOut.c/h  ← PWM电机输出
│   │   ├── Drv_RcIn.c/h    ← 遥控器信号捕获
│   │   ├── Drv_adc.c/h     ← ADC电压采集
│   │   ├── Drv_led.c/h     ← LED控制
│   │   ├── Drv_sys.c/h     ← 系统滴答定时器
│   │   └── Drv_timer.c/h   ← 基础定时器
│   └── Libraries/          ← STM32标准库/HAL库
│
├── ProjectSTM32F407/       ← Keil5工程文件（STM32F407）
│   ├── ANO_LX_STM32F407.uvprojx  ← 主工程文件
│   └── build/              ← 编译输出
│
└── .github/
    ├── copilot-instructions.md    ← 全局AI开发指令
    └── instructions/
        ├── lingxiao-protocol.instructions.md
        ├── keil5-stm32f407.instructions.md
        └── drone-c-conventions.instructions.md
```

## 当前实机串口分配（室内机，2026-06-21校正）

- `UART5`：凌霄 IMU 主通信口，当前实用，收发都在走 ANO 协议。
- `UART4`：匿名光流模块，当前实用，接收光流/高度数据并喂给 `LX_FC_EXT_Sensor`。
- `USART6`：SBUS 遥控输入，当前实机在用。
- `UART1`：代码里保留了 Ublox GPS 驱动/初始化残留，但**当前室内项目不使用 GPS**，实机视为闲置口。
- `UART2`：历史上做过直连数传 `0xA0` 日志测试；当前 `LOG_TEST_EN=0` 且 `user_log_test_task()` 已注释，不再使用，实机视为闲置口。
- `UART3`：驱动初始化仍在 `All_Init()`，但当前无业务解析也无发送调用，视为闲置口。

说明：判断“当前在用”时，优先按当前室内机硬件方案和启用路径看，不把历史残留驱动/GPS测试代码算进现用串口。


## 关键全局变量

| 变量 | 类型 | 定义位置 | 说明 |
|------|------|----------|------|
| `fc_sta` | `_fc_state_st` | LX_FC_State.c | 飞控运行状态（模式、解锁、IMU就绪等） |
| `fc_att` | `_fc_att_un` | ANO_LX.c | 姿态欧拉角（来自0x03帧） |
| `fc_att_qua` | `_fc_att_qua_un` | ANO_LX.c | 姿态四元数（来自0x04帧） |
| `fc_vel` | `_fc_vel_un` | ANO_LX.c | 飞行速度（来自0x07帧） |
| `fc_bat` | `_fc_bat_un` | ANO_LX.c | 电池状态（来自0x0D帧） |
| `rt_tar` | `_rt_tar_un` | ANO_LX.c | 实时控制目标（发送0x41帧用） |
| `pwm_to_esc` | `_pwm_st` | ANO_LX.c | ESC PWM输出值（来自0x20帧） |
| `dt` | `_dt_st` | ANO_DT_LX.c | 数据传输管理结构体 |
| `rc_in` | `_rc_in_st` | Drv_RcIn.c | 遥控器输入数据 |

## 飞控状态结构体（fc_sta）字段

```c
typedef struct {
    u8 fc_mode_cmd;    // 发出的模式命令（0-3）
    u8 fc_mode_sta;    // 当前实际模式（0=姿态,1=定高,2=定点,3=程控）
    u8 unlock_cmd;     // 发出的解锁命令（0=上锁,1=解锁）
    u8 unlock_sta;     // 当前实际解锁状态
    _cmd_fun_st cmd_fun; // 最近执行的CMD功能
    u8 imu_ready;      // IMU就绪标志
    u8 take_off;       // 已起飞标志
    u8 in_air;         // 在空中标志
    u8 landing;        // 降落中标志
} _fc_state_st;
```
