# 20260719-162748-sync-gated-workflow

备份原因：用户明确要求把树莓派侧与 STM32 飞控侧“同步沟通、阶段闸门推进”的协作方式写入记忆配置和相关调度，防止后续会话忘记。

备份范围：
- `AGENTS.md`
- `CODEX_SESSION_START.md`
- `CODEX_MEMORY_INDEX.md`
- `树莓派飞控对接文档.md`
- `project_docs/树莓派飞控对接文档.md`
- `memories/repo/dev-log.md`

目标状态：后续树莓派/飞控联调不是单线开发，而是 Codex 先完成飞控侧一个小阶段并汇报，再明确树莓派侧要完成的测试/日志，用户回传验收结果后，Codex 再继续下一个飞控阶段。
