---
name: drone-task-sequence
description: '生成凌霄飞控程控任务序列代码（模式3）。使用场景：需要编写自主飞行程序，如起飞→悬停→平移→旋转→降落等有序动作序列。关键词：程控任务、自主飞行、任务序列、起飞降落、路径规划、CMD序列、状态机任务、autonomous flight、task planning。'
argument-hint: '任务描述，如：起飞50cm→前进100cm→右移50cm→降落'
---

# 生成程控任务序列

## 适用场景
- 程控模式（模式3）下的自主飞行任务
- 多个动作按顺序执行（起飞→移动→旋转→降落）
- 需要等待动作完成后再执行下一步

## 步骤

### 1. 收集任务描述
用户描述任务序列，如：
- 起飞到高度H厘米（B类CMD：CID=0x10, CMD0=0x00, CMD1=0x05）
- 向特定方向平移X厘米（C类CMD：CID=0x10, CMD0=0x02, CMD1=0x03）
- 旋转角度A度（左旋CMD1=0x07，右旋CMD1=0x08）
- 降落（B类CMD：CID=0x10, CMD0=0x00, CMD1=0x06）

### 2. 参照协议规范
加载 `.github/instructions/lingxiao-protocol.instructions.md`，确认每个动作对应的CMD类别和参数格式。

**重要约束**：
- B类CMD（起飞/降落）：模式1/2/3均可，在模式3中使用
- C类CMD（平移/旋转）：**仅程控模式3有效**
- CMD发送必须检查 `dt.wait_ck == 0`

### 3. 生成状态机代码
参照 [任务序列模板](./assets/task_sequence_template.c) 生成：
- 每个动作对应一个 `case`
- 发送CMD后进入等待case（检查 `dt.wait_ck == 0` 后推进）
- 可选：加入超时计时防止死锁（`task_timer`）

### 4. 完成判断策略
| 动作类型 | 完成判断方式 |
|----------|-------------|
| 起飞 | CK确认 + `ABS(fc_alt - target) < 5cm` |
| 平移 | CK确认 + `ABS(fc_pos_x - target) < 10cm` |
| 旋转 | CK确认 + 等待固定时间（如 `task_timer > 100` 个50Hz周期） |
| 降落 | CK确认 + `fc_sta.unlock_sta == 0`（已自动上锁） |

### 5. 放置位置
函数放在 `User_Task.c` 中，在 `UserTask_OneKeyCmd()` 的 50Hz 循环中调用。
