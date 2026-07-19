# Codex 项目规则入口

本仓库是匿名凌霄 STM32F407 无人机项目。Codex 接手时不要把它当新项目，必须先读取迁移包中的历史记忆和规则。

## 每次开发前必读

1. `记忆迁移/codex记忆迁移/review.md`
2. `记忆迁移/codex记忆迁移/CODEX_MEMORY_INDEX.md`
3. `记忆迁移/codex记忆迁移/CODEX_SESSION_START.md`
4. `记忆迁移/codex记忆迁移/CODEX_FOUNDATION.md`
5. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
6. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
7. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
8. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`
9. 涉及协议时读 `记忆迁移/codex记忆迁移/github_config/instructions/lingxiao-protocol.instructions.md`
10. 涉及飞控 C 代码时读 `记忆迁移/codex记忆迁移/github_config/instructions/drone-c-conventions.instructions.md`
11. 涉及 STM32/外设/编译烧录时读 `记忆迁移/codex记忆迁移/github_config/instructions/keil5-stm32f407.instructions.md`
12. 涉及 GUI 或路径可视化时读 `记忆迁移/codex记忆迁移/memories/repo/gui-architecture.md`、`记忆迁移/codex记忆迁移/memories/repo/imu-test-tool.md`、`记忆迁移/codex记忆迁移/memories/repo/path-viz-plan.md`、`记忆迁移/codex记忆迁移/project_docs/gui/path_viz_master_plan.md`

## 后续任务固定自用流程

每次收到用户任务时，必须按下面顺序自启动，不等用户再次提醒：

1. 确认当前目录为 `/home/ubuntu22/stm32/ANO_LX_FC`，并确认 `记忆迁移/codex记忆迁移/` 存在。
2. 读取 `CODEX_SESSION_START.md` 和 `CODEX_MEMORY_INDEX.md`，先恢复项目上下文。
3. 按任务类型加载对应专项文档和 Copilot drone skill，不凭残留上下文直接写代码。
4. 先检查历史 `dev-log.md`，避免重复踩已记录的问题。
5. 修改代码前优先定位现有实现和相邻风格；飞控任务默认从 `FcSrc/User_Task.c::UserTask_OneKeyCmd()` 和相关协议入口追踪。
6. 修改协议、地址、功能码、模式响应、0x41/0xE0/0xA0/0x32/0x33/0x34/0xF1~0xF6 时，必须先查协议规则；若仍有不确定，查 `用户手册/` 官方 PDF。
7. 修改后按影响面验证：飞控 C 代码优先 `./scripts/build.sh`；GUI 代码优先运行对应 smoke/截图验证；文档改动至少做关键字冲突扫描。
8. 解决问题、纠正旧记忆或完成可验证功能后，立即追加 `dev-log.md`，必要时同步 project_docs / GUI README。

## 任务类型自动路由

| 任务类型 | 必须加载 |
|---|---|
| 飞控固件 / PID / 遥控通道 / 0x41 | `drone-c-conventions.instructions.md`、`lingxiao-protocol.instructions.md`、`dev-log.md`、`project-structure.md`、`architecture.md` |
| 协议 / 串口 / 上行帧 / 0xF1~0xF6 | `lingxiao-protocol.instructions.md`、`project_docs/数据帧.md`、`project_docs/groundTest/README.md`、协议调试/发送 skill |
| 树莓派对接 / 0xF5 位置帧 | `project_docs/树莓派飞控对接文档.md`、`project_docs/数据帧.md`、协议规则 |
| STM32 / 外设 / OpenOCD / 烧录 | `keil5-stm32f407.instructions.md`、`project_docs/最终验收清单.md`、VS Code 配置记忆 |
| GUI / 上位机 / 命令面板 | `gui-architecture.md`、`project_docs/gui/README.md`、`github_config/chat-log.md` |
| IMU 测试台 | `imu-test-tool.md`、`gui-architecture.md`、相关 GUI 文档 |
| 路径可视化 | `path-viz-plan.md`、`project_docs/gui/path_viz_master_plan.md`，并遵守阶段串行和 smoke 验收 |
| 新模块 / 新传感器 / 任务序列 | 对应 `copilot_skills/drone-*/SKILL.md`，并先读 C 规范和协议规则 |
| 代码审查 | `drone-code-review/SKILL.md`，优先找飞行安全、调度阻塞、协议和内存风险 |

## 最高优先级约束

- 本项目飞控主控为 STM32F407，语言以纯 C 为主；凌霄 IMU 是闭源控制核心，STM32 主要做上层任务封装、协议通信、目标/速度指令组织。
- 凌霄飞控由 STM32F407 + 凌霄 IMU 两部分组成：STM32 是可编程中央总控，凌霄 IMU 是闭源传感/融合/控制核心。只能修改 STM32 代码，不能修改或假设知道 IMU 内部代码。
- STM32 通过匿名协议把遥控器、外部传感器、任务目标、速度/位置指令等打包给 IMU；IMU 内置算法如何处理未知，只能通过手册、源码接口、抓包和实测推断。
- 数传接在凌霄 IMU 链路上，不要认为修改 STM32 某段逻辑就能直接改变所有数传输出；必须先分析该输出是 STM32 生成、IMU 转发，还是 IMU 闭源算法生成。
- 用户逻辑首要入口是 `FcSrc/User_Task.c::UserTask_OneKeyCmd()`，由 50Hz 调度调用。
- 修改协议、地址、功能码、模式响应、0x41/0xE0/0xA0/0x32/0x33/0x34 等内容时，必须先查 `用户手册/匿名通信协议V7.pdf` 和 `用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`。手册与记忆冲突时以手册为准。
- 严禁阻塞调度循环，严禁动态内存，协议结构体必须 `__packed__`，发送 CMD 前必须检查 `dt.wait_ck == 0`。
- 遇到新问题或解决卡点后，必须追加到 `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`，格式：`[日期] [问题] → [根因] → [解决方案] → [教训]`。
- 记忆维护细则见 `记忆迁移/codex记忆迁移/CODEX_UPDATE_RULES.md`。
- 每次代码变更后，优先运行 `./scripts/build.sh` 做 GCC/CMake 编译验证；不要主动运行最终飞行程序，实机运行由用户执行。

## 不要自动导入

不要把任何非飞控项目规则当成本项目规则。本迁移包已经剔除混合来源、历史迁移说明和 `.bak` 备份；如果在其他目录看到旧副本，也不要导入。
