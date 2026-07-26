# 凌霄无人机项目 — 关键规则速查

## ⚡ 强约束：每次解决问题后必须记录（最高优先）

> 不记录 = 下次重蹈覆辙。格式固定，不可省略：

```
[日期] [遇到的问题] → [根本原因] → [解决方案] → [教训/下次避免方法]
```

**记录位置**：`/memories/repo/dev-log.md` 的"问题与解决方案记录"节  
**记录时机**：解决问题后立即写，完成功能后更新"当前总进度"表  
**思考约束**：每次回答必须紧贴当前任务目标，禁止偏离（如被问PID时不要扯无关的传感器驱动）

---

## 开发前必做（按顺序）

1. 读取 `/memories/repo/dev-log.md` — 当前进度 + 未解决问题
2. 读取 `/memories/repo/project-structure.md` — 模块结构
3. 读取 `/memories/repo/architecture.md` — 设计决策

---

## 最容易犯的错误（红色警戒）

1. **发CMD前忘记检查`dt.wait_ck == 0`** → 校验混乱，CMD失效
2. **在程控模式未激活时发送0x41帧** → 飞控忽略，无效指令
3. **结构体忘记加`__packed__`** → 字节对齐错误，数据解析乱码
4. **在调度循环里用阻塞延时** → 整个调度死住，飞机失控
5. **`ANO_DT_LX.c`原始代码bug**：两个`else if`都是`0x03`（第二个应为`0x04`四元数），四元数永远不被解析
6. **RC_Data_Task()在100Hz覆写vel_x/y** → PID任务写入的速度指令被下一帧清零，任务无响应；改速度指令前先查ANO_LX.c的RC任务
7. **烧录后不断电重启** → 旧代码仍在运行，"功能不生效"的第一排查项
8. **XY保高逻辑和Z控高混用** → Z轴任务不需要固定thr=500，拆开处理
9. **Win32 串口未设 COMMTIMEOUTS** → 默认 ReadFile 阻塞等数据，工作线程卡死，UI 投递的 close_port 槽永远不执行（"点断开没反应"）。修复：open() 后调 SetCommTimeouts(ReadIntervalTimeout=MAXDWORD)
10. **QThread worker 主循环忘记 `QCoreApplication.processEvents()`** → 通过 `QueuedConnection` 投递的槽（open_port/send_bytes 等）永远不会被派发；表现为"点连接没反应、串口连不上"；修复：在 while 循环顶部加 `processEvents()`
11. **PySide6 `Q_ARG(bytes, ...)` 跨线程报错 `qArgDataFromPyType: Unable to find a QMetaType for "bytes"`** → Python 原生 `bytes` 不是注册的 QMetaType；修复：UI 端用 `Q_ARG(QByteArray, QByteArray(frame))`，slot 用 `@Slot(QByteArray)` 并在函数内 `bytes(payload)` 转回
12. **无 `0x0D` 电池电压时先别追光流协议** → 现场已确认：`0x0D` 电压消失/归零会联动导致光流、激光高度、通用速度、`0x33/0x34` 和 `0x0E` 外部传感状态异常，并可能出现 `[A0 红] 运动解算失效复位`；恢复后会出现 `[A0 绿] 运动解算启动`。排查顺序固定为：电压/供电/地线/串口桥硬件 → `0x0E` 状态 → 光流/激光协议。
13. **UART2 串口桥故障和 USART5 误接 TX 是两个独立问题，不能互相覆盖** → 异常 ANO `SWD&UART V2.0` 类 DAP/UART 复合模块接树莓派 USB 会让电压/外部传感异常；另一个独立故障是把 USB-TTL `TX` 接入 `UART5/USART5` 主通信总线，也会立刻破坏电压和外部传感数据。两条原因都保留，后续都要查。
14. **USART5 只能旁路监听，不能主动接树莓派 TX** → `UART5/USART5` 是 STM32 ↔ 凌霄 IMU 主通信口。板上 `RX/TX` 是相对 STM32：`RX`=STM32接收IMU数据，`TX`=STM32发送给IMU。树莓派建图只读IMU数据时固定接法是 `飞控USART5 RX → USB-TTL RX`、`GND ↔ GND`，USB-TTL `TX/VCC` 和飞控 `USART5 TX` 全部不接。这个“RX接RX”不是普通串口互联，而是高阻旁路监听 IMU→STM32 数据线。

---

## 协议三要素速记
- 帧头：`0xAA`
- 发给IMU/广播：`dest=0xFF`；回复上位机CK：`dest=0xAF`
- 校验：`for(i=0;i<len+4;i++){SC+=data[i]; AC+=SC;}`（范围是LEN+4字节，含帧头）

---

## 项目语言：纯C，不是C++，不用malloc/free

- 新增或修改的代码默认补充简洁中文注释，优先说明用途、触发条件、关键字段和开关方式。
- 只要对协议、模式、地址、功能码或字段有不确定，必须先回查工作区"用户手册/匿名通信协议V7.pdf"和"用户手册/匿名--凌霄--飞控手册.V1.07pdf.pdf"；memory 和 md 规则若冲突，以官方手册为准。
