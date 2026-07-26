# 凌霄飞控项目 · 记忆迁移完整指南

> **目标读者**：迁移到新电脑后的 GitHub Copilot Agent  
> **核心目标**：让你完全无缝衔接这个项目的所有开发历史、约束规则和当前阶段

---

## 第一步：你必须理解的全貌

这是一个**匿名凌霄室内四旋翼无人机飞控**项目，包含两大部分：

| 部分 | 技术栈 | 当前状态 |
|------|--------|---------|
| 飞控MCU固件 | STM32F407 + Keil5 + 纯C | 已实飞验证，PID三轴联动完成 |
| 桌面GUI上位机 | Python + PySide6 + pyqtgraph | P0-P10全部完成，路径可视化大阶段收尾 |

---

## 最高优先硬件记忆（2026-07-24实测）

- 外部传感器/光流/激光高度突然“无数据”时，第一优先级先查 `0x0D` 电池电压帧和 `0x0E` 外接模块状态；`0x0D` 电压消失会伴随光流/激光/通用速度数据消失，并可触发 `[A0 红] 运动解算失效复位`。
- 目前有两类互不冲突的确认原因：一是异常 ANO `SWD&UART V2.0` 类 DAP/UART 复合模块接入 UART2 树莓派链路后干扰电压/外部传感；二是 USB-TTL `TX` 误接入 `UART5/USART5` 主通信总线，干扰 STM32↔凌霄IMU通信。
- `UART5/USART5` 不是树莓派主动通信口。板上 `RX/TX` 相对 STM32：`RX`=STM32接收IMU数据，`TX`=STM32发送给IMU。树莓派建图只读IMU数据时只能 `飞控USART5 RX → USB-TTL RX`、`GND ↔ GND`，USB-TTL `TX/VCC` 和飞控 `USART5 TX` 不接。
- 树莓派主动发送 SLAM/目标位置只能走 UART2 的 `0xF5` 链路，不得复用 USART5。

---

## 第二步：迁移文件目录结构说明

```
记忆迁移/
├── review.md                          ← 本文档（先读这里）
├── memories/
│   ├── user/                          ← 用户级持久记忆（跨工作区）
│   │   ├── drone-lingxiao-rules.md    ← 凌霄项目核心规则速查（最高优先）
│   │   └── stm32-ucosiii-keil.md     ← STM32/uCOS-III移植经验
│   └── repo/                          ← 仓库级记忆（仅本项目）
│       ├── dev-log.md                 ← ★ 最重要：全部开发历史+当前进度
│       ├── project-structure.md       ← 模块结构详细说明
│       ├── architecture.md            ← 架构决策记录（为什么这样设计）
│       ├── gui-architecture.md        ← GUI上位机架构备忘
│       ├── encoding.md                ← 编码规范（GBK！）
│       ├── intellisense.md            ← VS Code IntelliSense配置说明
│       └── path-viz-plan.md           ← 路径可视化大阶段锁定计划
├── github_config/                     ← VS Code工程内的AI配置
│   ├── copilot-instructions.md        ← 全局开发指令（每次必读）
│   └── instructions/
│       ├── lingxiao-protocol.instructions.md  ← 协议规则库
│       ├── keil5-stm32f407.instructions.md    ← MCU开发规则
│       └── drone-c-conventions.instructions.md ← C代码规范
└── copilot_skills/                    ← 专项技能包（6个）
    ├── drone-add-sensor/SKILL.md      ← 添加传感器技能
    ├── drone-code-review/SKILL.md     ← 代码审查技能
    ├── drone-new-module/SKILL.md      ← 新建模块技能
    ├── drone-protocol-debug/SKILL.md  ← 协议调试技能
    ├── drone-protocol-send/SKILL.md   ← 协议发送技能
    └── drone-task-sequence/SKILL.md   ← 程控任务序列技能
```

---

## 第三步：写入新电脑的操作步骤（必须严格执行）

### 3.1 工程内配置（已在项目里，会自动生效）

这部分文件已经存在于项目代码仓库中（`.github/` 目录），**只要工程文件夹克隆到新电脑，就会自动被 VS Code + Copilot 识别**，无需手动操作：

```
工程根目录/.github/copilot-instructions.md          ← 自动加载为全局指令
工程根目录/.github/instructions/*.instructions.md   ← 自动加载为上下文规则
```

**验证方法**：在新电脑打开工程后，在 Copilot Chat 里问"这个项目用什么语言"，如果回答"纯C"且提到Keil5/STM32F407，说明工程配置已生效。

---

### 3.2 用户级记忆（必须手动写入）

这部分存储在 VS Code 用户全局存储里，**不随工程文件夹转移**，必须手动写入。

**实际存储路径（Windows）**：
```
C:\Users\<用户名>\AppData\Roaming\Code\User\globalStorage\github.copilot-chat\memory-tool\memories\
```

**操作方式**：在新电脑上打开 Copilot Chat，说以下话让 Copilot 帮你写入：

> "请帮我在用户记忆中创建文件 `drone-lingxiao-rules.md`，内容如下：[粘贴 memories/user/drone-lingxiao-rules.md 的全部内容]"

> "请帮我在用户记忆中创建文件 `stm32-ucosiii-keil.md`，内容如下：[粘贴 memories/user/stm32-ucosiii-keil.md 的全部内容]"

**或者直接用工具写入（推荐）**：
新电脑 Copilot 可以通过 memory 工具直接创建，命令是：
```
memory create /memories/drone-lingxiao-rules.md  [文件内容]
memory create /memories/stm32-ucosiii-keil.md    [文件内容]
```

---

### 3.3 仓库级记忆（必须手动写入）

这部分存储在工作区存储里，**不随工程文件夹转移**，必须手动写入。

**实际存储路径（Windows）**：
```
C:\Users\<用户名>\AppData\Roaming\Code\User\workspaceStorage\<工作区ID>\GitHub.copilot-chat\memory-tool\memories\repo\
```

**操作方式**：在新电脑打开工程后，在 Copilot Chat 里依次说：

> "请帮我在仓库记忆中创建文件 `dev-log.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `project-structure.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `architecture.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `gui-architecture.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `encoding.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `intellisense.md`，内容如下：[粘贴内容]"
> "请帮我在仓库记忆中创建文件 `path-viz-plan.md`，内容如下：[粘贴内容]"

**或者直接用工具写入（推荐）**：
新电脑 Copilot 可以通过 memory 工具直接创建：
```
memory create /memories/repo/dev-log.md           [文件内容]
memory create /memories/repo/project-structure.md [文件内容]
memory create /memories/repo/architecture.md      [文件内容]
memory create /memories/repo/gui-architecture.md  [文件内容]
memory create /memories/repo/encoding.md          [文件内容]
memory create /memories/repo/intellisense.md      [文件内容]
memory create /memories/repo/path-viz-plan.md     [文件内容]
```

---

### 3.4 技能文件（必须手动写入）

技能文件存储在：
```
C:\Users\<用户名>\.copilot\skills\<skill-name>\SKILL.md
```

**操作方式（PowerShell）**：
```powershell
$skillBase = "$env:USERPROFILE\.copilot\skills"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-add-sensor"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-code-review"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-new-module"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-protocol-debug"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-protocol-send"
New-Item -ItemType Directory -Force -Path "$skillBase\drone-task-sequence"

# 然后把各 copilot_skills/XXX/SKILL.md 拷贝到对应目录
```

---

## 第四步：读取记忆的正确顺序

**每次开始开发前，必须按以下顺序阅读**（这是强约束，不能跳过）：

### 必读顺序（不可省略）
1. **`/memories/drone-lingxiao-rules.md`**（用户记忆）— 整个项目最核心的规则，包含最容易犯的11种错误，每次开发前必读，防止重蹈覆辙
2. **`/memories/repo/dev-log.md`**（仓库记忆）— 当前进度 + 全部历史问题记录，是最重要的上下文文件
3. **`/memories/repo/project-structure.md`**（仓库记忆）— 了解模块结构
4. **`/memories/repo/architecture.md`**（仓库记忆）— 了解设计决策，知道"为什么这样写"

### 按需读取
- 涉及GUI时：读 `/memories/repo/gui-architecture.md` 和 `/memories/repo/path-viz-plan.md`
- 涉及协议时：读 `.github/instructions/lingxiao-protocol.instructions.md`
- 涉及C代码规范时：读 `.github/instructions/drone-c-conventions.instructions.md`
- 新建模块时：用 `drone-new-module` skill
- 调试协议时：用 `drone-protocol-debug` skill

---

## 第五步：当前项目状态速览

### 飞控MCU固件（STM32F407）
- **已完成**：上行指令链路（0xF1/0xF2/0xF3帧）、三轴PID位移任务、全通道遥控诊断
- **当前可用触发通道**：CH6=X+Y联动(axis_mode=4)、CH10=仅Y轴(axis_mode=2)、CH7=Z轴
- **用户唯一入口**：`FcSrc/User_Task.c` → `UserTask_OneKeyCmd()`，50Hz调用
- **重要参数**：`PID3D_EN=1`（三轴PID启用）、`RC_IDENTIFY_SAFE_MODE=0`（正常飞行模式，=1时禁止所有任务）

### GUI上位机（Python + PySide6）
- **已完成**：阶段A~E + GUI路径可视化P0~P10（全部完成?）
- **启动方式**：项目根目录 `run_gui.bat` 或 `C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe -m gui.main`
- **注意**：GUI 使用 Python 3.13（不是3.14），`.venv` 目录是3.14环境，不可用
- **功能门控**：GUI顶部"功能"菜单中勾选"路径可视化"后，3D/2D视图Dock出现

### 已知但未解决的问题（冻结状态）
- 路径漂移：IMU 0x07速度帧存在双重积分漂移，等光流传感器接入后才能根治，GUI端补丁无法解决（物理事实）
- Y轴超调约59%：PID KP偏高/KD偏低，待下次实飞调参

---

## 第六步：绝对禁止事项（红色警戒）

这些是已经血泪验证过的坑，**绝对不能重蹈**：

1. **发CMD前忘记检查 `dt.wait_ck == 0`** → 校验混乱，CMD失效
2. **在程控模式未激活时发送0x41帧** → 飞控忽略，无效指令（必须先确认 `fc_sta.fc_mode_sta == 3`）
3. **结构体忘记加 `__packed__`** → 字节对齐错误，数据解析乱码
4. **在调度循环里用阻塞延时（HAL_Delay/delay_ms）** → 整个调度死住，飞机失控
5. **`ANO_DT_LX.c`原始代码bug**：两个`else if`都是`0x03`（第二个应为`0x04`四元数），已修复，但合并代码时注意不要引入回退
6. **RC_Data_Task()在100Hz覆写vel_x/y** → PID任务写入的速度指令被下一帧清零，所有速度指令冲突先查ANO_LX.c的RC任务
7. **烧录后不断电重启** → 旧代码仍在运行，"功能不生效"的第一排查项
8. **GUI: Win32串口未设COMMTIMEOUTS** → ReadFile阻塞，UI线程卡死
9. **GUI: QThread worker循环忘记 `QCoreApplication.processEvents()`** → QueuedConnection槽永不被派发
10. **GUI: 跨线程用 `Q_ARG(bytes,...)` 而非 `Q_ARG(QByteArray,...)`** → Python bytes不是注册QMetaType，静默失效
11. **GUI文件编码**：所有 `.py` 文件含中文必须加 `# -*- coding: gbk -*-` 头，所有 `.c/.h` 遗留文件也是GBK，禁止用 PowerShell UTF8 模式追加内容

---

## 第七步：每次开发完成后的强制记录义务

**每次解决问题后必须立即追加到 `/memories/repo/dev-log.md`**，格式：
```
[日期] [遇到的问题] → [根本原因] → [解决方案] → [教训/下次避免方法]
```

**每次完成一个功能后必须更新"当前总进度"节**，标明已完成/进行中/待做。

---

## 附录：关键文件速查

| 你要做的事 | 必读的文件 |
|----------|----------|
| 添加飞控功能 | `FcSrc/User_Task.c` + `memories/repo/dev-log.md` |
| 调试协议 | `FcSrc/ANO_DT_LX.c` + `github_config/instructions/lingxiao-protocol.instructions.md` |
| 修改GUI | `gui/main.py` + `memories/repo/gui-architecture.md` |
| 不确定协议字段 | `用户手册/匿名通信协议V7.pdf`（官方手册优先于一切记忆规则） |
| 新建模块 | 用 `drone-new-module` skill + `github_config/instructions/drone-c-conventions.instructions.md` |
| 代码审查 | 用 `drone-code-review` skill |
| 判断当前进度 | `memories/repo/dev-log.md` 底部"当前总进度"节 |
| 路径可视化相关 | `gui/path_viz_master_plan.md` + `memories/repo/path-viz-plan.md` |

---

> ?? 最后提醒：这个项目有大量已踩过的坑，记录在 `dev-log.md` 里。在写任何新代码之前，先把 `dev-log.md` 从头到尾读一遍，确保不会重新引入已经修复过的问题。这不是建议，是强制要求。
