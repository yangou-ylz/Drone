# Codex 完整继承审计

更新时间：2026-07-18

本文件记录 Codex 对 `ANO_LX_FC` 迁移包的接入状态。目标是让后续任务不依赖聊天残留，而是通过仓库内规则自动恢复原有开发记忆、经验、流程和历史踩坑。

## 已完成的配置

- 已读取 `AGENTS.md`，并把它作为项目规则入口。
- 已读取 `CODEX_FIRST_PROMPT.md` 指定的首次接入清单。
- 已读取核心记忆：`review.md`、`CODEX_MEMORY_INDEX.md`、`CODEX_SESSION_START.md`、`CODEX_UPDATE_RULES.md`。
- 已读取用户/仓库记忆：`drone-lingxiao-rules.md`、`dev-log.md`、`project-structure.md`、`architecture.md`、`encoding.md`、`intellisense.md`。
- 已读取原 Copilot 指令：`copilot-instructions.md`、协议规则、飞控 C 规范、STM32/Keil5 规则。
- 已读取项目文档：`dev.md`、`数据帧.md`、`树莓派飞控对接文档.md`、`最终验收清单.md`、`验收题目.md`、`groundTest/README.md`。
- 已读取 GUI/IMU/路径可视化记忆：`gui-architecture.md`、`imu-test-tool.md`、`path-viz-plan.md`、`project_docs/gui/path_viz_master_plan.md`、`project_docs/gui/README.md`、`github_config/chat-log.md`。
- 已读取 6 个 Copilot drone skill：新增传感器、代码审查、新模块、协议调试、协议发送、任务序列。
- 已读取 VS Code 配置迁移记录：C/C++ include/define、推荐扩展、OpenOCD debug、CMake/Ninja build tasks。

## 已固化的后续自用流程

- `AGENTS.md` 增加“后续任务固定自用流程”和“任务类型自动路由”。
- `CODEX_MEMORY_INDEX.md` 增加完整继承审计入口、私有帧占用速记、GUI/IMU/路径可视化验证注意事项。
- `CODEX_SESSION_START.md` 增加自动执行流程和继承边界说明。
- 2026-07-19 新增 `CODEX_FOUNDATION.md`，固化 STM32F407 与凌霄 IMU 的职责边界、数传数据链路、手册优先和匿名系列传感器资料归档规则。
- 2026-07-19 新增 `CODEX_GIT_BACKUP_RULES.md`，固化“Git/项目历史回滚必须由用户亲手执行”、实时更新进度记忆、必要时备份源码/补丁的规则。

## 本次继承时纠正的旧记忆冲突

- `project_docs/数据帧.md`：`0xF3` 总长从旧写法 `15B` 修正为已验证的 `18B = 4 + 12 + 2`。
- `project_docs/数据帧.md` 与 `dev-log.md`：私有帧表更新为 `0xF1`/`0xF2`/`0xF3` 已占用，`0xF5` 为树莓派位置帧规划。
- `project_docs/dev.md`：旧扩展建议不再使用 `0xF3 SAVE` 或 `0xF5 READ`，后续必须重新分配未占用帧号。
- 以上纠错已追加到 `memories/repo/dev-log.md`。

## 后续必须坚持的恢复方式

1. 不把当前聊天上下文当永久记忆。
2. 每次新任务先读 `AGENTS.md`、`CODEX_SESSION_START.md`、`CODEX_MEMORY_INDEX.md`。
3. 按任务类型读取专项文档和 skill。
4. 修改后验证并更新 `dev-log.md`。
5. 遇到协议不确定，以 `用户手册/` 官方 PDF 为最终依据。

## 审计结论

截至 2026-07-18，本迁移包内与飞控项目相关的核心记忆、规则、文档、GUI 历史、协议历史、工具链配置和专项 workflow 已完成接入，并已写入仓库级自启动规则。后续开发应能通过这些文件恢复原有开发经验与流程。
