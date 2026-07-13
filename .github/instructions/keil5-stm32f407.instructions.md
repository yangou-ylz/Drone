---
description: "STM32F407 + Keil5 嵌入式开发规则。使用场景：编写驱动代码、配置外设、处理中断、调整时钟、编写Keil工程相关配置、调试MCU级问题时。包含时钟配置、中断优先级、外设使用规范、内存约束、Keil编译选项。"
---

# STM32F407 + Keil5 开发规则

## 时钟配置

| 时钟域 | 频率 | 说明 |
|--------|------|------|
| 系统时钟 (SYSCLK) | 168 MHz | STM32F407最高频率 |
| APB1 总线 | 42 MHz | 低速外设（UART2~5, I2C, SPI2~3, TIM2~7/12~14） |
| APB2 总线 | 84 MHz | 高速外设（UART1/6, SPI1, TIM1/8~11） |
| APB1 定时器时钟 | 84 MHz | APB1×2（当APB1分频系数≠1时） |
| APB2 定时器时钟 | 168 MHz | APB2×2（当APB2分频系数≠1时） |

> **定时器频率公式**：若APBx分频≠1，则定时器时钟 = APBx × 2

---

## 中断优先级分组

本项目使用**第4组**（`NVIC_PriorityGroup_4`）：
- 全部4位用于抢占优先级（0~15）
- 0位用于响应优先级（固定为0）
- 抢占优先级数字越小，优先级越高

**优先级设置原则**：
- 系统滴答定时器（SysTick）：最高优先级 0
- UART接收中断（凌霄IMU通信）：高优先级 1~2
- PWM/TIM更新中断：中等优先级 3~5
- 其他外设中断：低优先级 6~15

> 禁止抢占优先级相同的中断互相嵌套（它们是平级的）

---

## 内存约束（严格执行）

| 约束 | 说明 |
|------|------|
| 禁止动态内存 | 不得使用 `malloc`/`free`/`calloc`，使用静态或全局数组 |
| 禁止递归 | 可能导致栈溢出，使用迭代+状态机代替 |
| 禁止C++特性 | 所有文件为`.c`，不使用类、模板、异常、RTTI |
| 栈大小注意 | 局部大数组（>256字节）应声明为static或全局 |

STM32F407 RAM：192KB（含64KB CCM）。CCM区只能被CPU访问，不能用于DMA。

---

## 外设驱动路径

| 外设 | 文件路径 |
|------|----------|
| UART | `DriversMcu/STM32F407/Drivers/Drv_Uart.c/h` |
| PWM输出 | `DriversMcu/STM32F407/Drivers/Drv_PwmOut.c/h` |
| 遥控输入（捕获） | `DriversMcu/STM32F407/Drivers/Drv_RcIn.c/h` |
| ADC（电压） | `DriversMcu/STM32F407/Drivers/Drv_adc.c/h` |
| LED | `DriversMcu/STM32F407/Drivers/Drv_led.c/h` |
| 系统滴答 | `DriversMcu/STM32F407/Drivers/Drv_sys.c/h` |
| 定时器基础 | `DriversMcu/STM32F407/Drivers/Drv_timer.c/h` |
| BSP总初始化 | `DriversBsp/Drv_BSP.c/h`（`All_Init()`函数） |

> **不要直接修改`DriversMcu/`下的底层驱动**，除非有明确需求且已在dev-log中记录

---

## Keil5 项目配置

| 配置项 | 值 |
|--------|-----|
| 项目文件 | `ProjectSTM32F407/ANO_LX_STM32F407.uvprojx` |
| 编译输出目录 | `ProjectSTM32F407/build/` |
| C标准 | C99 |
| 优化级别 | 默认O2（调试时可改为O0） |
| 目标芯片 | STM32F407ZGTx（或具体型号） |

### 常用Keil操作
- **编译**：F7 或 Project → Build Target
- **烧录**：F8 或 Flash → Download
- **清理输出**：运行 `clear编译完的东西.bat`
- **调试连接**：J-Link，接口SWD，速度4MHz

### 头文件包含顺序规范
```c
// 1. 系统配置（必须第一个）
#include "SysConfig.h"
// 2. MCU底层驱动
#include "Drv_Uart.h"
// 3. BSP板级驱动  
#include "Drv_BSP.h"
// 4. 飞控功能模块
#include "LX_FC_State.h"
#include "ANO_DT_LX.h"
```

---

## UART通信配置（凌霄IMU接口）

- 波特率：**500000** bps（凌霄协议标准波特率）
- 数据位：8位，停止位：1位，无校验
- 发送函数：`UartSendLXIMU(u8 *data, u8 len)`
- 接收入口：UART接收中断 → 每字节调用 `ANO_DT_LX_Data_Receive_Prepare(data)`

---

## 调度器频率与外设关系

```
1000Hz (1ms)  — 预留给最高实时性需求（如高速传感器采样）
 500Hz (2ms)  — 预留
 200Hz (5ms)  — 预留（可用于姿态环计算）
 100Hz (10ms) — 传感器数据处理
  50Hz (20ms) — 用户任务UserTask_OneKeyCmd()、控制指令发送
  20Hz (50ms) — 状态上报、LED闪烁
   2Hz (500ms)— 低频日志、心跳
```

---

## 常见STM32F407编译错误处理

| 错误 | 原因 | 解决方法 |
|------|------|----------|
| `undefined reference to 'xxx'` | 函数未实现或未加入工程 | 检查.c文件是否加入Keil工程组 |
| `implicit declaration of function` | 缺少头文件包含 | 添加对应`.h`的`#include` |
| 硬件故障（HardFault） | 访问非法地址/栈溢出 | 检查数组越界、空指针、递归深度 |
| 程序跑飞 | 中断未注册或优先级冲突 | 检查NVIC配置和ISR函数名拼写 |
