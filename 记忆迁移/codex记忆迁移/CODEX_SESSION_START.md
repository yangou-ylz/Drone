# Codex 会话启动检查清单

每次 Codex 在 `ANO_LX_FC` 项目中开始新会话、恢复上下文或接到新任务时，先执行本清单。

## 1. 确认项目

- 当前仓库应为 `/home/ubuntu22/stm32/ANO_LX_FC`。
- 项目类型：匿名凌霄 STM32F407 无人机飞控 + Python GUI 上位机。
- 不要加载任何非飞控项目记忆。

## 2. 固定必读

按顺序读：

1. `AGENTS.md`
2. `记忆迁移/codex记忆迁移/CODEX_MEMORY_INDEX.md`
3. `记忆迁移/codex记忆迁移/CODEX_FOUNDATION.md`
4. `记忆迁移/codex记忆迁移/CODEX_GIT_BACKUP_RULES.md`
5. `记忆迁移/codex记忆迁移/review.md`
6. `记忆迁移/codex记忆迁移/memories/user/drone-lingxiao-rules.md`
7. `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`
8. `记忆迁移/codex记忆迁移/memories/repo/project-structure.md`
9. `记忆迁移/codex记忆迁移/memories/repo/architecture.md`

## 3. 判断任务类型

- 飞控固件：读 C 规范、协议规则、`User_Task.c` 附近实现。
- 协议/串口：读协议规则、`数据帧.md`、groundTest README、协议 skill。
- GUI/上位机：读 GUI 架构、IMU测试工具、path-viz计划、GUI README。
- 新模块/传感器/任务序列：读对应 drone skill。
- 代码审查：使用 review 姿态，优先找风险、回归、缺测试。

## 3.5 自动执行流程

每次任务都按以下流程执行：

1. 任务分类：飞控固件 / 协议串口 / GUI / IMU测试台 / 路径可视化 / STM32工具链 / 文档。
2. 读取 `CODEX_MEMORY_INDEX.md` 对应分组，加载专项文档和 drone skill。
3. 查 `dev-log.md` 中相关历史坑，避免重复方案。
4. 先用 `CODEX_FOUNDATION.md` 判断 STM32/凌霄 IMU/数传的数据所有权，不能把 IMU 闭源输出误判为 STM32 可直接控制。
5. 外部传感器、光流、激光高度、`0x33/0x34/0x0E` 异常时，先查 `0x0D` 电池电压是否存在且稳定；若插上树莓派 UART2 USB-TTL/DAP-UART 模块后电压归零或出现 `[A0 红] 运动解算失效复位`，优先排查串口桥硬件、反灌电、地线、电平和供电，不要先改光流/IMU协议。
6. 先用 `CODEX_GIT_BACKUP_RULES.md` 判断是否需要备份；禁止执行任何 Git/项目历史回滚命令，回滚必须由用户亲手做。
7. 定位现有源码/文档的真实实现，再决定修改点。
8. 若任务涉及树莓派 ↔ STM32 正式对接、`0xF5`、SLAM/视觉目标或串口联调，必须进入“双端同步阶段闸门”流程：先确认当前阶段编号和双方状态；只完成本侧最小阶段；汇报本侧进度；给出树莓派侧必须执行的脚本、期望日志和失败材料；等待用户回传通过结果后再推进下一阶段。
9. 修改后做最小充分验证：C 编译、GUI smoke/截图、协议帧校验或文档关键词扫描。
10. 若解决问题或纠正旧记忆，按 `CODEX_UPDATE_RULES.md` 立即追加记录。

## 4. 回答前说明上下文

开始实际回答或动手前，先用一句话说明当前判断的上下文，例如：

- “这是飞控固件任务，我先读 User_Task 和协议规则。”
- “这是 GUI 上位机任务，我先读 GUI 架构和 IMU 测试工具记忆。”

## 5. 验证原则

- 代码修改后优先运行 `./scripts/build.sh`。
- 不主动运行最终飞行程序或实机动作，实机运行由用户执行。
- 如果无法验证，明确说明原因和可替代检查。

## 6. 完成后记录

解决问题后，追加 `记忆迁移/codex记忆迁移/memories/repo/dev-log.md`。

## 7. 继承边界

Codex 的长期继承依赖本仓库内 `AGENTS.md` + `CODEX_*.md` + `memories/` + `project_docs/`。不要依赖聊天残留记忆；每次新会话都必须重新读取上述文件来恢复上下文。
