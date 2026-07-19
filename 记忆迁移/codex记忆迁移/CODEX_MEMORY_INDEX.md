# Codex 项目记忆索引

本文件是 Codex 在 `ANO_LX_FC` 项目中的记忆索引。每次接到任务时，先根据任务类型决定读取哪些文件，不要只凭上下文残留回答。

## 必读入口

每次开始开发、分析、审查或调试前，先读：

1. `AGENTS.md`
2. `记忆迁移/codex记忆迁移/review.md`
3. `记忆迁移/codex记忆迁移/CODEX_FOUNDATION.md`
4. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
5. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
6. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
7. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`

## 完整继承审计

当前迁移包已按 `CODEX_FIRST_PROMPT.md` 全量接入，审计记录见：

- `记忆迁移/codex记忆迁移/CODEX_INHERITANCE_AUDIT.md`

以后若迁移包新增或删除文件，必须同步更新该审计记录；否则不能声称已经完整继承。

## 飞控固件任务

适用：修改 `FcSrc/`、PID任务、遥控通道、0x41速度指令、凌霄IMU交互、飞行安全逻辑。

必须读：

- `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
- `记忆迁移/codex记忆迁移/CODEX_FOUNDATION.md`
- `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
- `记忆迁移/codex记忆迁移/memories/repo/architecture.md`
- `记忆迁移/codex记忆迁移/github_config/copilot-instructions.md`
- `记忆迁移/codex记忆迁移/github_config/instructions/drone-c-conventions.instructions.md`
- `记忆迁移/codex记忆迁移/github_config/instructions/lingxiao-protocol.instructions.md`

重点代码入口：

- `FcSrc/User_Task.c::UserTask_OneKeyCmd()`
- `FcSrc/User_Task.h`
- `FcSrc/ANO_LX.c::RC_Data_Task()`
- `FcSrc/ANO_DT_LX.c`
- `FcSrc/Uplink_Cmd.c/h`

补充记忆：

- `记忆迁移/codex记忆迁移/project_docs/dev.md`
- `记忆迁移/codex记忆迁移/project_docs/最终验收清单.md`（涉及 Ubuntu/GCC/OpenOCD 验收时）
- `记忆迁移/codex记忆迁移/memories/repo/encoding.md`（修改遗留中文文件时）

## 协议/串口任务

适用：0xF1/0xF2/0xF3、0x41、0xA0、0x32/0x33/0x34、上行/下行帧、校验失败、数传调试。

必须读：

- `记忆迁移/codex记忆迁移/github_config/instructions/lingxiao-protocol.instructions.md`
- `记忆迁移/codex记忆迁移/project_docs/数据帧.md`
- `记忆迁移/codex记忆迁移/project_docs/树莓派飞控对接文档.md`
- `记忆迁移/codex记忆迁移/project_docs/groundTest/README.md`
- `记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-debug/SKILL.md`
- `记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-send/SKILL.md`

官方手册优先：协议字段、地址、模式响应不确定时，查 `用户手册/匿名通信协议V7.pdf` 和 `用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf`。

当前私有帧占用速记：

- `0xF1`：链路验证灵活帧
- `0xF2`：单轴目标写入
- `0xF3`：三轴目标同帧写入，总长 18B
- `0xF5`：树莓派位置帧规划（cur/tar/flags）
- 后续新帧必须先查 `数据帧.md`、`dev-log.md` 和源码冲突，不能复用已占用帧号。

## GUI/上位机任务

适用：`gui/`、IMU测试台、路径可视化、PySide6、串口上位机、数据帧监视。

必须读：

- `记忆迁移/codex记忆迁移/memories/repo/gui-architecture.md`
- `记忆迁移/codex记忆迁移/memories/repo/imu-test-tool.md`
- `记忆迁移/codex记忆迁移/memories/repo/path-viz-plan.md`
- `记忆迁移/codex记忆迁移/project_docs/gui/path_viz_master_plan.md`
- `记忆迁移/codex记忆迁移/project_docs/gui/README.md`
- `记忆迁移/codex记忆迁移/github_config/chat-log.md`

GUI 关键运行/验证记忆：

- Ubuntu GUI 主环境：`.venv-linux`，真实 3D 需要 `DISPLAY=:1` / `QT_QPA_PLATFORM=xcb`。
- Windows GUI 历史运行入口以 `project_docs/gui/README.md` 为准。
- FakeWorker 只模拟部分回执，不产生 0x01/0x04 等 IMU 数据；IMU 测试台必须用注入测试或真硬件验证。
- 路径可视化改动必须按 `path_viz_master_plan.md` 阶段约束和对应 smoke 回归执行。

## 新增模块/传感器/任务序列

按任务选择：

- 新建飞控模块：`记忆迁移/codex记忆迁移/copilot_skills/drone-new-module/SKILL.md`
- 添加外部传感器：`记忆迁移/codex记忆迁移/copilot_skills/drone-add-sensor/SKILL.md`
- 生成协议发送函数：`记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-send/SKILL.md`
- 调试协议异常：`记忆迁移/codex记忆迁移/copilot_skills/drone-protocol-debug/SKILL.md`
- 程控任务序列：`记忆迁移/codex记忆迁移/copilot_skills/drone-task-sequence/SKILL.md`
- 代码审查：`记忆迁移/codex记忆迁移/copilot_skills/drone-code-review/SKILL.md`

外部传感器资料规则：

- 匿名系列传感器（如匿名光流 + 激光高度）同属凌霄生态，适配性高，但仍必须查权威资料确认字段和打包规则。
- 本地没有权威资料时，可以联网查找官方/权威资料；查到后保存到 `记忆迁移/codex记忆迁移/project_docs/sensors/` 或明确的本地传感器文档目录。
- 保存资料后同步更新本索引和 `dev-log.md`，避免后续重复猜测。

## 更新义务

- 每解决一个问题，立即追加到 `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`。
- 每完成一个功能，更新或追加阶段记录。
- 涉及飞行安全，记录安全影响。
- 新增运行、烧录、GUI使用步骤时，同步更新相关 `project_docs/` 或 GUI 文档。
- 发现旧记忆错误时，记录旧结论为何错、新结论依据是什么。

## 禁止导入

只使用本迁移包内与 `ANO_LX_FC` 相关的文件。不要读取或套用任何非飞控项目记忆。
