# Codex 记忆迁移总说明

> 目标读者：接手 `/home/ubuntu22/stm32/ANO_LX_FC` 的 Codex / Codex CLI。  
> 目标：让 Codex 不把本项目当新项目，而是完整继承 VS Code Copilot 阶段积累的飞控、GUI、协议、调试、编码、历史问题和安全约束。

---

## 0. 先说结论

本目录是从 VS Code Copilot 的记忆系统、仓库 `.github` 指令、无人机专用 skill、项目文档和 VS Code 配置中筛选出来的迁移包。**只迁移匿名凌霄 STM32F407 无人机项目相关内容**，没有迁移其他项目的自动规则。

Codex 接手后，不能只读本文件。必须按下方顺序把迁移内容写入项目级 Codex 规则，并在每次开发前按顺序阅读关键记忆。

---

## 1. 目录结构与用途

```text
codex记忆迁移/
├── review.md
├── memories/
│   ├── user/
│   │   └── drone-lingxiao-rules.md
│   └── repo/
│       ├── dev-log.md
│       ├── project-structure.md
│       ├── architecture.md
│       ├── encoding.md
│       ├── intellisense.md
│       ├── gui-architecture.md
│       ├── imu-test-tool.md
│       └── path-viz-plan.md
├── github_config/
│   ├── chat-log.md
│   ├── copilot-instructions.md
│   └── instructions/
│       ├── drone-c-conventions.instructions.md
│       ├── keil5-stm32f407.instructions.md
│       └── lingxiao-protocol.instructions.md
├── copilot_skills/
│   ├── drone-add-sensor/SKILL.md
│   ├── drone-code-review/SKILL.md
│   ├── drone-new-module/SKILL.md
│   ├── drone-protocol-debug/SKILL.md
│   ├── drone-protocol-send/SKILL.md
│   └── drone-task-sequence/SKILL.md
├── project_docs/
│   ├── dev.md
│   ├── 数据帧.md
│   ├── 树莓派飞控对接文档.md
│   ├── 最终验收清单.md
│   ├── 验收题目.md
│   ├── gui/path_viz_master_plan.md
│   ├── gui/README.md
│   └── groundTest/README.md
├── vscode_config/
│   ├── c_cpp_properties.json
│   ├── extensions.json
│   ├── launch.json
│   ├── settings.json
│   └── tasks.json
```

说明：
- `memories/repo/dev-log.md` 是最重要的历史总账，记录了飞控固件、GUI、协议、真机问题、踩坑、修复和当前状态。
- `memories/user/drone-lingxiao-rules.md` 是最高优先级速查规则，里面的红色警戒必须每次开发前看。
- `github_config/` 是原 VS Code Copilot 的项目指令。Codex 不一定自动识别 `.instructions.md`，所以要把关键内容合并进 Codex 项目规则。
- `copilot_skills/` 是无人机专项技能包。Codex 没有 Copilot skill 机制时，也要把这些当作领域知识文档按需阅读。
- 迁移包内不保留其他项目的混合记忆、旧迁移说明或乱码 `.bak` 备份，避免 Codex 误读。

---

## 2. Codex 必须如何写入项目级记忆

建议在 `ANO_LX_FC` 仓库根目录创建或更新 `AGENTS.md`。如果已经存在，不要覆盖，应该把以下内容合并进去。这样 Codex 每次进入该仓库时会自动读到项目规则。

推荐写入 `AGENTS.md` 的核心内容如下：

```markdown
# 匿名凌霄 STM32F407 无人机项目规则

## 每次开始开发前必须读取
1. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
2. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
3. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
4. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`
5. 如涉及协议，读取 `记忆迁移/codex记忆迁移/github_config/instructions/lingxiao-protocol.instructions.md`
6. 如涉及飞控 C 代码，读取 `记忆迁移/codex记忆迁移/github_config/instructions/drone-c-conventions.instructions.md`
7. 如涉及 STM32/外设/编译烧录，读取 `记忆迁移/codex记忆迁移/github_config/instructions/keil5-stm32f407.instructions.md`
8. 如涉及 GUI/路径可视化，读取 `记忆迁移/codex记忆迁移/memories/repo/gui-architecture.md`、`记忆迁移/codex记忆迁移/memories/repo/path-viz-plan.md`、`记忆迁移/codex记忆迁移/project_docs/gui/path_viz_master_plan.md`

## 最高优先级规则
- 本项目是匿名凌霄室内四旋翼无人机，飞控主控为 STM32F407，语言以纯 C 为主。
- 用户逻辑首要入口是 `FcSrc/User_Task.c::UserTask_OneKeyCmd()`，50Hz 调度调用。
- 凌霄 IMU 是闭源控制核心，STM32 主要做上层任务封装、协议通信、目标/速度指令组织，不要把姿态环/PWM底层控制当成 STM32 自己写的逻辑。
- 修改协议、地址、功能码、模式响应、0x41/0xE0/0xA0/0x32/0x33/0x34 等内容时，必须先查 `用户手册/匿名通信协议V7.pdf` 和 `用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`。手册与记忆冲突时，以手册为准，并回写修正记忆。
- 外部传感/光流/激光高度无数据时，先查 `0x0D` 电池电压和 UART2 树莓派串口桥硬件。已实测异常 DAP/UART 复合模块会让电压数据消失，并联动触发 `A0 红 运动解算失效复位` 和外部传感无数据；拔掉后恢复。
- 严禁阻塞调度循环，严禁动态内存，协议结构体必须 `__packed__`，发送 CMD 前必须检查 `dt.wait_ck == 0`。
- 遇到新问题或解决卡点后，必须追加到 `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`，格式：`[日期] [问题] → [根因] → [解决方案] → [教训]`。
- 每次代码变更后，优先运行 `./scripts/build.sh` 做 GCC/CMake 编译验证；不要主动运行最终飞行程序，实机运行由用户执行。

## 不要自动导入的内容
- 不要把任何非飞控项目规则当成本项目规则。
- 如果迁移包之外还能看到旧的混合记忆或历史迁移说明，不要导入到 Codex 规则；本迁移包内已经剔除这些内容。
```

---

## 3. Codex 第一次接手时的阅读顺序

第一次接手必须完整阅读，不要只看 README：

1. `review.md`：先理解迁移包怎么用。
2. `memories/user/drone-lingxiao-rules.md`：最高优先级红色警戒。
3. `memories/repo/dev-log.md`：从头到尾读，这是全部历史问题与当前状态。
4. `memories/repo/project-structure.md`：理解目录、串口、工具链、关键变量。
5. `memories/repo/architecture.md`：理解“为什么这样设计”。
6. `github_config/copilot-instructions.md`：原 Copilot 全局项目指令。
7. `github_config/instructions/*.instructions.md`：协议、C规范、STM32规则。
8. `project_docs/dev.md`、`数据帧.md`、`树莓派飞控对接文档.md`：理解上位机/树莓派/飞控通信和上行指令链路。
9. 如果任务涉及 GUI，再读 `memories/repo/gui-architecture.md`、`imu-test-tool.md`、`path-viz-plan.md`、`project_docs/gui/path_viz_master_plan.md`。
10. 如果任务涉及专门动作，按需读 `copilot_skills/drone-*/SKILL.md`。

---

## 4. 当前项目状态摘要

飞控固件：
- 当前硬件是 STM32F407 + 凌霄 IMU 闭源飞控模块 + 凌霄光流/数传等外设。
- Ubuntu 22 当前主用 GCC/CMake/Ninja/OpenOCD：编译 `./scripts/build.sh`，烧录 `./scripts/flash-dap.sh`。
- Keil 工程是 Windows 遗留参考，当前 Ubuntu 环境不主用。
- `UserTask_OneKeyCmd()` 是用户任务主入口。
- 已实现上行指令链路：`0xF1` 链路验证、`0xF2` 单轴目标写入、`0xF3` 三轴目标写入。
- 已实现 PID 位置任务：CH6 触发 X+Y 联动，CH10 触发 Y，CH7 触发 Z；这些任务会写 `rt_tar` 并通过 `0x41` 发速度指令。
- 基础遥控飞行不要误触 CH6/CH7/CH10 高档；如果只做新机架基础起飞测试，可临时关闭 `User_Task.h` 中的 `PID_TEST_EN`。

GUI/上位机：
- `gui/` 是 Python + PySide6 上位机，不是 STM32 固件。
- GUI 路径可视化 P0-P10 已完成，后续改动必须遵守 `path_viz_master_plan.md` 的阶段和验收约束。
- GUI 文件含中文时遵守 GBK/CP936 编码历史约定，详见 `memories/repo/encoding.md`。

已知重要风险：
- `RC_Data_Task()` 在 100Hz 可能覆写速度目标，任何速度指令无效或被清零时先查 `FcSrc/ANO_LX.c`。
- 烧录后必须断电重启，否则旧代码可能仍在运行。
- `0x08` 位置帧历史上不适合直接闭环；之前 PID3D 主要用 `0x07` 速度积分作为观测。
- IMU 速度积分和 GUI 路径可视化漂移问题是物理传感器限制，不能靠无限补丁解决。

---

## 5. 已剔除的非飞控内容

这次迁移只保留飞控项目相关材料。所有非飞控全局记忆、混合来源记忆、旧迁移说明、乱码或重复 `.bak` 备份都已整体剔除，避免 Codex 把其他项目约束误当成本项目规则。

---

## 6. 给 Codex 的首次启动提示词

完整提示词已经单独写入 `CODEX_FIRST_PROMPT.md`。建议直接把该文件全文复制给 Codex，它会要求 Codex 按顺序阅读迁移文档，并建立自己的 `AGENTS.md`、记忆索引、会话启动 checklist 和更新规则。

下面保留一个短版提示词，用于快速启动：

```text
你现在接手的是 /home/ubuntu22/stm32/ANO_LX_FC 匿名凌霄 STM32F407 无人机项目。不要把它当新项目。

请先完整阅读：
1. 记忆迁移/codex记忆迁移/review.md
2. 记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md
3. 记忆迁移/codex记忆迁移/memories/repo/dev-log.md
4. 记忆迁移/codex记忆迁移/memories/repo/project-structure.md
5. 记忆迁移/codex记忆迁移/memories/repo/architecture.md
6. 记忆迁移/codex记忆迁移/github_config/copilot-instructions.md
7. 记忆迁移/codex记忆迁移/github_config/instructions/*.instructions.md

阅读后，请把 review.md 第 2 节推荐的项目规则合并到仓库根目录 AGENTS.md（若已有则合并，不要覆盖），并在之后每次开发前自动按 AGENTS.md 的必读顺序读取这些记忆。

然后请继续按照 `记忆迁移/codex记忆迁移/CODEX_FIRST_PROMPT.md` 的要求，创建或更新 Codex 自己的项目记忆结构：`CODEX_MEMORY_INDEX.md`、`CODEX_SESSION_START.md`、`CODEX_UPDATE_RULES.md`。

注意：不要混入任何其他项目约束。本迁移包已经删除混合来源；如果在其他目录看到旧副本，也不要导入。
```

---

## 7. 迁移核对记录

本次迁移已核对：
- repo 级记忆源头 8 个，目标 8 个。
- drone 专项 skill 6 个，目标 6 个。
- `app-*` skill 未迁移。
- 已删除所有非飞控全局记忆、混合来源目录、历史迁移目录和 `.bak` 备份。
- 迁移包内只保留匿名凌霄 STM32F407 无人机项目相关材料。

最后提醒：Codex 后续每完成一个真实问题修复，都要继续更新 `memories/repo/dev-log.md`，否则下一轮又会忘记已经踩过的坑。
