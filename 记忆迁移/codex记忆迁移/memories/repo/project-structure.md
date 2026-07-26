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
├── ProjectSTM32F407/       ← 原 Keil5 工程文件（Windows 遗留，当前 Ubuntu 不用）
│   ├── ANO_LX_STM32F407.uvprojx  ← Keil5 主工程（仅供参考，不用来编译）
│   └── STM32F407VETx_FLASH.ld    ← GCC 链接脚本（新增，供 CMake 使用）
│
├── CMakeLists.txt          ← GCC/CMake 旁路工程入口（当前主用）
├── cmake/arm-none-eabi-gcc.cmake  ← 交叉编译工具链配置
├── compat/include/         ← Linux 大小写桥接头文件（sysconfig.h 等）
├── build-gcc/              ← CMake 构建输出（ANO_LX.elf/.hex/.bin）
├── scripts/                ← 快捷脚本（build.sh / flash-dap.sh 等）
├── openocd/                ← OpenOCD 配置文件
│   └── stm32f407-cmsis-dap-low-speed-no-srst.cfg  ← 已验证可用的烧录配置
│
└── .github/
    ├── copilot-instructions.md    ← 全局AI开发指令
    └── instructions/
        ├── lingxiao-protocol.instructions.md
        ├── keil5-stm32f407.instructions.md
        └── drone-c-conventions.instructions.md
```

## 基础系统工作原理

本项目不是“STM32 单独完成全部飞控闭环”的结构，而是：

```text
STM32F407（可编程中央总控）
  ├─ 运行本仓库 C 代码
  ├─ 组织用户任务、遥控输入、外部传感器输入、目标/速度/模式/CMD 指令
  └─ 通过匿名协议帧发送给凌霄 IMU

凌霄 IMU（闭源传感/融合/控制核心）
  ├─ 内部算法不可见、不可改
  ├─ 接收 STM32/外部模块协议帧后自行融合和处理
  └─ 输出传感数据、融合状态、命令状态、电机 PWM 等匿名协议帧

数传 / 上位机
  └─ 接收凌霄 IMU 链路输出的数据帧并显示或记录
```

关键理解：

- STM32 侧代码能改的是“给 IMU 的输入”和“自身上层任务组织”，不是 IMU 闭源算法。
- 凌霄 IMU 输出的数据帧可能包含传感器数据、命令状态、融合结果和电机 PWM；这些输出不一定由 STM32 直接生成。
- 调试数传输出时必须先判断该帧数据来源；不能默认“STM32 改了就会直接改变数传输出”。
- 接入匿名系列外部传感器时，优先查手册和权威资料，按协议打包给 IMU。

## 当前开发工具链（Ubuntu 22.04）

| 工具 | 路径/版本 | 用途 |
|------|---------|------|
| arm-none-eabi-gcc | `/opt/gcc-arm-none-eabi-9-2020-q2-update/bin/` 9.3.1 | 交叉编译 |
| CMake | `~/.local/bin/cmake` 4.1.3 | 构建系统 |
| Ninja | `/usr/bin/ninja` | 构建后端 |
| OpenOCD | `../tools/xpack-openocd-0.12.0-7` | 烧录/调试 |
| ANO CMSIS-DAP | VID:PID=5269:6367 | 调试器 |

**日常命令**：
```bash
./scripts/build.sh           # 编译
./scripts/flash-dap.sh       # 烧录（低速无SRST，已验证）
./scripts/probe-dap-low-speed.sh  # 只连接不烧录（排查用）
```

## 当前实机串口分配（室内机，2026-07-24校正）

- `UART5/USART5`：凌霄 IMU 主通信口，当前实用，收发都在走 ANO 协议。板上 `RX/TX` 标注相对于 STM32：`RX` 是 STM32 接收 IMU 数据（IMU→STM32），`TX` 是 STM32 发送数据给 IMU（STM32→IMU）。若树莓派只需要读取姿态/速度/高度等 IMU 数据用于建图，只能旁路监听 `USART5 RX → USB-TTL RX` 和 `GND ↔ GND`；USB-TTL `TX`、`VCC/5V` 和飞控 `USART5 TX` 都不要接。接入 USB-TTL TX 会干扰 STM32↔IMU 主通信，现场实测会导致 `0x0D`/外部传感等数据瞬间异常。
- `UART4`：匿名光流模块，当前实用，接收光流/高度数据并喂给 `LX_FC_EXT_Sensor`。
- `USART6`：SBUS 遥控输入，当前实机在用。
- `UART1`：代码里保留了 Ublox GPS 驱动/初始化残留，但**当前室内项目不使用 GPS**，实机视为闲置口。
- `UART2`：当前用于树莓派 ↔ STM32 位置通信链路，`PD6=UART2_RX` 接收树莓派 `0xF5`，`PD5=UART2_TX` 回传 `0xA0` ACK/日志，参数 `500000 baud / 8N1 / 无校验 / 无流控`。该链路必须使用已验证的 3.3V USB-TTL 或安全隔离串口桥；不要把 ANO `SWD&UART V2.0` 这类 DAP/UART 复合板直接当树莓派 UART2 桥使用，除非已验证插入后 `0x0D` 电压和 `0x0E` 外接模块状态稳定。
- `UART3`：驱动初始化仍在 `All_Init()`，但当前无业务解析也无发送调用，视为闲置口。

说明：判断“当前在用”时，优先按当前室内机硬件方案和启用路径看，不把历史残留驱动/GPS测试代码算进现用串口。

## 电池电压与外部传感状态链路（2026-07-24校正）

- STM32 电池采样入口在 `DriversMcu/STM32F407/Drivers/Drv_adc.c`，飞控板电压检测走 ADC1 Channel 15 / `PC5`，再经 STM32/IMU 数据链路形成 `0x0D` 电池电压帧。
- GUI/数传侧 `0x0D` 电压不是普通辅助信息。现场实测证明：无电压或电压归零时，凌霄 IMU 会出现运动解算失效复位，光流/激光/通用速度等外部传感状态也会消失。
- 已确认两类互不冲突的硬件/接线故障都会造成类似现象：一是异常 DAP/UART 复合串口模块接入 `UART2` 树莓派链路后造成电压/外部传感异常；二是把 USB-TTL 的 `TX` 接入 `UART5/USART5` 主通信总线，干扰 STM32↔IMU 数据。
- 因此排查光流/激光无数据时，先确认 `0x0D` 是否正常，再排查 `UART2` USB-TTL/DAP-UART 模块反灌/电平问题，以及 `UART5` 是否被外部 TX 主动驱动。`UART5` 只能高阻监听，不能让树莓派或USB-TTL向该总线发送。


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
