---
description: "无人机C代码规范和开发惯例。使用场景：新建模块、编写状态机、命名变量/函数/结构体、设计模块接口、扩展功能时。包含命名规范、模块结构模板、状态机模式、调度器使用惯例、代码可读性和可扩展性要求。"
applyTo: "FcSrc/**"
---

# 无人机C代码规范与开发惯例

## 命名规范

### 变量命名
```c
// 全局变量：模块缩写前缀 + 下划线分隔
u8 fc_mode_sta;          // 飞控状态：fc_ 前缀
u16 vel_x_cmps;          // 速度数据：描述性名称
static u8 step;          // 静态局部变量：直接命名

// 不要这样写
u8 x;                    // 过于简短，无意义
u8 theCurrentFlightModeStatus; // 过于冗长
```

### 函数命名
```c
// 公共函数：模块_功能（大驼峰或下划线分隔均可，保持项目一致）
u8 FC_Unlock(void);
u8 OneKey_Takeoff(u16 height_cm);
void UserTask_OneKeyCmd(void);

// 静态（模块内部）函数：小写下划线
static void calc_pid_output(void);
static u8 check_timeout(u16 time_ms);
```

### 结构体/联合体/枚举命名
```c
// 结构体：_描述_st（下划线前缀，_st后缀）
typedef struct { ... } _fc_state_st;

// 联合体：_描述_un（下划线前缀，_un后缀）
typedef union { ... } _fc_att_un;

// 枚举：直接命名（无特殊后缀）
enum { ch_1_rol = 0, ch_2_pit, ch_3_thr };

// 宏常量：全大写下划线分隔
#define MAX_ANGLE   3500
#define MAX_YAW_DPS 200
```

---

## 模块结构模板

每个新功能模块必须遵循一对`.c/.h`的结构：

### 头文件（.h）模板
```c
#ifndef __MODULE_NAME_H
#define __MODULE_NAME_H

// 1. 引用（只引用本模块必须的头文件）
#include "SysConfig.h"

// 2. 宏定义
#define MODULE_XXX  100

// 3. 类型定义（仅对外暴露的类型）
typedef struct {
    u8 state;
    s16 value;
} __attribute__((__packed__)) _module_data_st;

typedef union {
    u8 byte_data[3];
    _module_data_st st_data;
} _module_data_un;

// 4. 外部数据声明（extern，仅必要时暴露）
extern _module_data_un module_data;

// 5. 公共函数声明
void Module_Init(void);
void Module_Task(float dT_s);

#endif
```

### 源文件（.c）模板
```c
#include "ModuleName.h"
// 其他依赖头文件...

// 模块内部全局数据定义
_module_data_un module_data;
static u8 module_state = 0;

// 静态（内部）函数实现
static void internal_helper(void) {
    // ...
}

// 公共函数实现
void Module_Init(void) {
    module_state = 0;
    // 初始化...
}

void Module_Task(float dT_s) {
    // 主逻辑...
}
```

---

## 状态机模式（核心设计模式）

凡是需要"等待某个条件后执行下一步"的逻辑，**必须用状态机**，禁止用阻塞等待。

### 标准状态机模板
```c
void Mission_Task(void)
{
    static u8 step = 0;        // 当前步骤
    static u32 step_timer = 0; // 步骤计时器（单位：ms或调度周期数）

    switch (step)
    {
    case 0: // 初始/空闲状态
        // 等待触发条件
        if (trigger_condition) {
            step = 1;
            step_timer = 0;
        }
        break;

    case 1: // 执行动作A
        if (ActionA() == 1) {  // 返回1表示发送成功
            step = 2;
            step_timer = 0;
        }
        break;

    case 2: // 等待结果或延时
        step_timer++;
        if (result_ready || step_timer > TIMEOUT_TICKS) {
            step = 3;
        }
        break;

    case 3: // 执行动作B
        if (ActionB() == 1) {
            step = 0; // 回到空闲
        }
        break;

    default:
        step = 0;
        break;
    }
}
```

### 状态机使用原则
- 每个`case`内的代码必须**快速返回**，不阻塞
- 计时用调度周期计数（50Hz下1个周期=20ms）
- 状态变量用`static u8 step`，不要用全局变量（防止模块间耦合）
- 超时保护：每个等待状态都要有超时机制

---

## 飞行控制指令使用规范

### 发送程控指令流程
```c
// 1. 确认已解锁
if (fc_sta.unlock_sta == 0) return;

// 2. 确认处于程控模式
if (fc_sta.fc_mode_sta != 3) return;

// 3. 确认IMU已就绪
if (fc_sta.imu_ready == 0) return;

// 4. 发送控制目标
rt_tar.st_data.vel_x = 100;   // cm/s，向前
rt_tar.st_data.vel_y = 0;
rt_tar.st_data.vel_z = 0;
rt_tar.st_data.yaw_dps = 0;
dt.fun[0x41].WTS = 1;
```

### 飞控API返回值含义
所有 `LX_FC_Fun.h` 中的函数：
- 返回 `1`：命令已发送（不代表执行完成）
- 返回 `0`：当前无法发送（`wait_ck != 0`或条件不满足）

---

## 协议数据结构规范

跨UART传输的所有结构体**必须加`__packed__`**防止编译器字节对齐：

```c
// 正确
typedef struct {
    s16 rol;
    s16 pit;
    s16 thr;
} __attribute__((__packed__)) _rt_tar_st;

// 错误（会导致字节对齐问题）
typedef struct {
    s16 rol;
    s16 pit;
    s16 thr;
} _rt_tar_st;
```

---

## 可扩展性设计要求

### 为未来扩展预留的接口位置

1. **任务调度器**（`Ano_Scheduler.c`）：在对应频率的`Loop_xxxHz()`中添加新任务调用
2. **传感器扩展**（`LX_FC_EXT_Sensor.c`）：添加新传感器数据结构和处理函数
3. **用户任务**（`User_Task.c`）：`UserTask_OneKeyCmd()`中添加新的任务状态机

### 模块间通信原则
- 模块间通过**全局结构体变量**共享数据（如`fc_sta`、`fc_att`、`fc_vel`）
- 不要在模块间直接调用对方的内部（`static`）函数
- 新增全局变量必须在`.h`中用`extern`声明，在唯一的`.c`中定义

---

## 代码可读性要求

```c
// 好的写法：意图清晰，关键步骤有注释
static void fly_to_target(void)
{
    static u8 step = 0;
    static u16 wait_cnt = 0;

    switch (step)
    {
    case 0:
        // 步骤1：切换到程控模式并解锁
        if (LX_Change_Mode(3) && FC_Unlock()) {
            step = 1;
        }
        break;
    case 1:
        // 步骤2：等待飞控确认进入程控模式（最多2秒）
        wait_cnt++;
        if (fc_sta.fc_mode_sta == 3) {
            step = 2;
            wait_cnt = 0;
        } else if (wait_cnt > 100) { // 100×20ms=2s超时
            step = 0; // 超时重置
        }
        break;
    }
}
```
