# STM32 + uCOS-III 移植经验（Keil Compiler V6）

## 致命Bug：OS_CPU_ARM_FP_EN 导致 OSInit 死循环

- **现象**：main() 能跑，调用 OSInit() 之后卡死，LED不亮，毫无反应
- **根本原因**：`os_cpu.h` 用 `#ifndef __TARGET_FPU_SOFTVFP` 判断FPU。`__TARGET_FPU_SOFTVFP` 是 Compiler V5(armcc) 专有宏，**Compiler V6(armclang) 不定义它**，导致 `OS_CPU_ARM_FP_EN = 1u`。`OSInitHook()` 里检查 FPCCR，Cortex-M3 无FPU，进入 `while(1)` 死循环
- **修复**：`os_cpu.h` 强制 `#define OS_CPU_ARM_FP_EN 0u`

## Compiler V6 移植 uCOS-III 必改清单（Cortex-M3）

1. `os_cpu.h`：`OS_CPU_ARM_FP_EN` 强制 `0u`（**最高优先，第一步**）
2. `os_cpu.h`：`OS_TASK_SW_SYNC()` → `__asm volatile ("isb")`（V6无`__isb()`）
3. `os_cpu_a.asm`：FPU 指令块用 `IF {FALSE} ... ENDIF` 包住
4. `startup_*.s`：向量表 PendSV/SysTick → `OS_CPU_PendSVHandler`/`OS_CPU_SysTickHandler`
5. `stm32f10x_conf.h`：删 `#include "RTE_Components.h"`，加 `#define assert_param(expr) ((void)0)`
6. `cpu_cfg.h`：`CPU_CFG_NVIC_PRIO_BITS 4u` 不能在 `#if 0` 里
7. `os_cfg_app.h`：`OS_CFG_TMR_TASK_RATE_HZ` = `OS_CFG_TICK_RATE_HZ`（都用1000u）
8. `OS_CPU_SysTickInit(72000u)` 放在 StartTask 第一行，不能在 OSStart 前调
9. J-Link：Debug → Port 选 **SW**，不是 JTAG
10. 任务栈：最小 256 words；消息传枚举值用 `(void*)(CPU_INT32U)val`，别传栈指针

## 诊断模板（OS启动卡死定位用）

```c
// main.c 里分段插入，看闪几下判断卡在哪
diag_blink(2);   // 能闪=main正常
OSInit(&err);
diag_blink(3);   // 能闪=OSInit正常，闪2下卡=OSInit死（查FPU！）
OSTaskCreate(...);
diag_blink(4);   // 能闪=OSTaskCreate正常
OSStart(&err);
```
