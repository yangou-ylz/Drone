# 给 Codex 的完整首次接入提示词

下面整段可以直接复制给 Codex。目标是让 Codex 先按顺序阅读迁移文档，然后在仓库内建立它自己的项目级规则入口和记忆索引，使后续每次进入本项目时都能自动读取，不需要用户反复提醒。

---

```text
你现在接手的是 `/home/ubuntu22/stm32/ANO_LX_FC` 项目。

这是匿名凌霄 STM32F407 室内四旋翼无人机项目，不是新项目。你必须完整继承以前 VS Code Copilot 阶段积累的所有飞控、协议、GUI、调试、编码、历史问题和安全约束。不要把任何非飞控项目规则混入本项目。

你的第一阶段任务不是写功能代码，而是完成“Codex 自己的项目记忆配置”。请严格按下面顺序执行。

一、先确认工作区

1. 确认当前目录是 `/home/ubuntu22/stm32/ANO_LX_FC`。
2. 确认存在 `记忆迁移/codex记忆迁移/`。
3. 如果目录不存在，立刻停止并告诉用户迁移包缺失。

二、按顺序完整阅读这些文件，不要跳读

必须先读：

1. `记忆迁移/codex记忆迁移/review.md`
2. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
3. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
4. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
5. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`
6. `记忆迁移/codex记忆迁移/github_config/copilot-instructions.md`
7. `记忆迁移/codex记忆迁移/github_config/instructions/lingxiao-protocol.instructions.md`
8. `记忆迁移/codex记忆迁移/github_config/instructions/drone-c-conventions.instructions.md`
9. `记忆迁移/codex记忆迁移/github_config/instructions/keil5-stm32f407.instructions.md`
10. `记忆迁移/codex记忆迁移/project_docs/dev.md`
11. `记忆迁移/codex记忆迁移/project_docs/数据帧.md`
12. `记忆迁移/codex记忆迁移/project_docs/树莓派飞控对接文档.md`
13. `记忆迁移/codex记忆迁移/project_docs/最终验收清单.md`

涉及 GUI 或路径可视化时，还必须读：

14. `记忆迁移/codex记忆迁移/memories/repo/gui-architecture.md`
15. `记忆迁移/codex记忆迁移/memories/repo/imu-test-tool.md`
16. `记忆迁移/codex记忆迁移/memories/repo/path-viz-plan.md`
17. `记忆迁移/codex记忆迁移/project_docs/gui/path_viz_master_plan.md`
18. `记忆迁移/codex记忆迁移/project_docs/gui/README.md`
19. `记忆迁移/codex记忆迁移/project_docs/groundTest/README.md`

涉及专项任务时，按需读：

20. `记忆迁移/codex记忆迁移/copilot_skills/drone-add-sensor/SKILL.md`
21. `记忆迁移/codex记忆迁移/copilot_skills/drone-code-review/SKILL.md`
22. `记忆迁移/codex记忆迁移/copilot_skills/drone-new-module/SKILL.md`
23. `记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-debug/SKILL.md`
24. `记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-send/SKILL.md`
25. `记忆迁移/codex记忆迁移/copilot_skills/drone-task-sequence/SKILL.md`

三、阅读后，创建或更新 Codex 自己的项目规则结构

请在仓库根目录创建或更新以下文件。若文件已存在，必须合并，不得覆盖用户已有内容。

1. `AGENTS.md`

用途：Codex 每次进入仓库时的自动入口。

要求写入以下核心规则：

- 本项目是匿名凌霄 STM32F407 无人机项目。
- 每次开始任何开发、分析、审查或修复前，必须先读：
  1. `记忆迁移/codex记忆迁移/review.md`
  2. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
  3. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
  4. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
  5. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`
- 涉及协议时必须读 `lingxiao-protocol.instructions.md`。
- 涉及飞控 C 代码时必须读 `drone-c-conventions.instructions.md`。
- 涉及 STM32、外设、编译烧录时必须读 `keil5-stm32f407.instructions.md`。
- 涉及 GUI、IMU 测试台、路径可视化时必须读 GUI 相关记忆和计划文档。
- 用户逻辑主入口是 `FcSrc/User_Task.c::UserTask_OneKeyCmd()`。
- 凌霄 IMU 是闭源控制核心，STM32 主要封装上层任务、协议通信、目标/速度指令，不要误以为 STM32 自己实现姿态环和 PWM 闭环。
- 官方手册优先：协议、地址、功能码、模式响应、字段含义不确定时，先查 `用户手册/匿名通信协议V7.pdf` 和 `用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`。
- 严禁阻塞调度循环，严禁动态内存，协议结构体必须 `__packed__`，发 CMD 前检查 `dt.wait_ck == 0`。
- 每次解决问题后必须更新 `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`。
- 不要导入任何非飞控项目记忆。

2. `记忆迁移/codex记忆迁移/CODEX_MEMORY_INDEX.md`

用途：Codex 自己用的记忆索引。以后看到任务时，先查这个索引决定该读哪些文件。

要求包含这些栏目：

- `必读入口`：列出每次都要读的 5 个核心文件。
- `飞控固件任务`：对应 `User_Task.c`、`ANO_LX.c`、`ANO_DT_LX.c`、协议规则、C规范、dev-log。
- `协议/串口任务`：对应协议 instructions、`数据帧.md`、`groundTest/README.md`、相关 skill。
- `GUI/上位机任务`：对应 GUI 架构、IMU 测试工具、path-viz 计划、GUI README。
- `新增模块/传感器/任务序列`：对应 drone skill 文件。
- `更新义务`：解决问题后更新 dev-log；涉及新步骤更新相关文档。
- `禁止导入`：明确只使用本迁移包内文件，不读取其他项目记忆。

3. `记忆迁移/codex记忆迁移/CODEX_SESSION_START.md`

用途：每次新会话开始时，Codex 自己按这个 checklist 执行。

要求包含：

- 先读 `AGENTS.md`。
- 再读 `CODEX_MEMORY_INDEX.md`。
- 再读 5 个核心记忆文件。
- 根据用户任务类型选择专项文档。
- 回答用户前，先简短说明当前处于飞控/GUI/协议/文档哪个上下文。
- 不要主动运行实机程序；可以做源码修改、CMake/GCC 编译验证。

4. `记忆迁移/codex记忆迁移/CODEX_UPDATE_RULES.md`

用途：规定以后 Codex 如何维护这些记忆，防止新阶段开发后旧约束丢失。

要求包含：

- 每解决一个问题，立即追加到 `memories/repo/dev-log.md`。
- 每完成一个功能，更新 dev-log 中的当前进度或新增阶段记录。
- 如果修改了飞控安全相关逻辑，记录安全影响。
- 如果新增运行步骤、烧录步骤、上位机使用步骤，更新对应 project_docs 或 GUI README。
- 如果发现旧记忆错误，不能静默覆盖，必须记录“旧结论为何错、新结论依据是什么”。
- 新增的 Codex 自己总结可以写进 `CODEX_MEMORY_INDEX.md` 或新建明确属于本项目的 `CODEX_*.md` 文件，不得混入其他项目。

四、完成配置后必须自检

请执行以下检查：

1. 列出 `AGENTS.md`、`CODEX_MEMORY_INDEX.md`、`CODEX_SESSION_START.md`、`CODEX_UPDATE_RULES.md` 是否存在。
2. 检查 `记忆迁移/codex记忆迁移/` 里没有 `.bak` 文件。
3. 检查迁移包里没有非飞控项目关键词。
4. 检查 repo 记忆数量仍为 8 个，drone skill 仍为 6 个。
5. 如果检查失败，先修复迁移配置，不要继续开发功能。

五、完成后向用户汇报

汇报时只需要说明：

- 已按顺序阅读了哪些核心文件。
- 已创建/更新哪些 Codex 项目记忆配置文件。
- 以后 Codex 会从哪里自动读取规则。
- 是否发现缺失、冲突或污染项。

六、以后每次回答问题时的固定原则

- 先判断任务属于飞控固件、协议、GUI、文档、测试、烧录还是迁移配置。
- 再按 `CODEX_MEMORY_INDEX.md` 读取对应文件。
- 不要凭记忆猜协议，必须查官方手册或协议规则。
- 不要跳过 `dev-log.md`，因为里面记录了大量已经踩过的坑。
- 不要重做已经证明失败的补丁。
- 不要把非飞控项目经验套用到本项目。
- 修改后能编译就运行 `./scripts/build.sh` 验证；不能验证时说明原因。

请现在开始执行第一阶段：阅读迁移文档，并建立 Codex 自己的项目记忆配置结构。
```