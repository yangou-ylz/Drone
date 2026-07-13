# groundTest — 上行指令地面测试脚本

通过电脑直连匿名数传（USB 转串口）→ 凌霄IMU → STM32F407，发送/监听协议帧。  
- **阶段1**：`0xF1` 灵活帧上行 + `0xA0` 字符串回显链路（已验证）
- **阶段2**：`0xF2` 参数写入帧，运行时改 PID3D 三轴目标坐标（已验证）

## 依赖

```powershell
pip install -r requirements.txt
```

## 串口约定

- 波特率：**500000**（飞控 `Drv_BSP.c` 设定，已在脚本中默认）
- 帧格式：`0xAA | dest | CMD | LEN | DATA[LEN] | SC | AC`
- 校验：SC/AC 对前 `LEN+4` 字节累加（详见 `ano_protocol.py`）

## 脚本

### 1. 列出当前可用串口

```powershell
python list_ports.py
```

输出例：
```
COM5  USB-SERIAL CH340 (COM5)
COM7  USB Serial Device (COM7)
```

### 2. 发送 0xF1 帧并监听回显

最常用 — 同时启监听线程，发完帧立刻看到飞控的 0xA0 回显：

```powershell
# 发一帧 X=1234 Y=-4562，并监听 3 秒
python send_f1.py --port COM5 --x 1234 --y -4562

# 以 10Hz 连发 60 秒（稳定性测试，对应阶段1 验收 §3）
python send_f1.py --port COM5 --x 1234 --y -4562 --rate 10 --duration 60

# 自定义目标地址（默认广播 0xFF；也可指定 0x61 = STM32飞控）
python send_f1.py --port COM5 --x 100 --y 200 --dest 0x61
```

### 3. 仅监听并解析所有入站帧

```powershell
python monitor.py --port COM5
```

实时打印每一帧：帧头/目标/CMD/LEN/DATA(hex)/SC/AC，对 0xA0 帧额外解 ASCII 字符串。

## 阶段1 验收建议流程

1. STM32 上电（数传连到电脑 USB）
2. `python list_ports.py` 找到数传所在 COM 口
3. `python send_f1.py --port COMx --x 1234 --y -4562` → 期望终端看到 `[RX 0xA0 GREEN] F1: X=1234 Y=-4562`
4. `python send_f1.py --port COMx --x 1234 --y -4562 --rate 10 --duration 60` → 1 分钟无中断、无丢帧
5. PID3D_EN=0 重新编译烧录，再跑步骤 3，确认零行为差异（仅链路功能）

---

## 阶段2：运行时改 PID3D 三轴目标坐标（0xF2 帧）

**用途**：在不重新烧录的情况下，远程改写飞控里 `PID3D_GOAL_X/Y/Z_CM` 三个目标坐标。  
**已硬件验证**（2026-05-24）：5/5 case 通过，含正常写入、负值、限幅、白名单拒绝。

### 4. 发送 0xF2 参数写入帧

```powershell
# 设 X 轴目标 = 30 cm
python send_param.py --port COM11 --id 1 --value 30

# 设 Y 轴目标 = -50 cm（支持负值）
python send_param.py --port COM11 --id 2 --value -50

# 设 Z 轴目标 = 80 cm
python send_param.py --port COM11 --id 3 --value 80

# 测试限幅：超 500cm 飞控自动钳到 500
python send_param.py --port COM11 --id 1 --value 800
# → [RX 0xA0 GREEN] P01=500.0 CLP

# 测试白名单：未知 ID 被拒绝
python send_param.py --port COM11 --id 9 --value 0
# → [RX 0xA0 RED] P09 UNK
```

### send_param.py 参数说明

| 参数 | 必填 | 取值 | 含义 |
|---|---|---|---|
| `--port` | ? | `COM11` 等 | 匿名数传所在串口；不知道就先跑 `list_ports.py` |
| `--id` | ? | `1` / `2` / `3` | 轴 ID：**1=GOAL_X、2=GOAL_Y、3=GOAL_Z**。其他值被飞控拒绝（用于测拒绝路径） |
| `--value` | ? | 浮点 cm | 目标坐标。**范围 ±500.0 cm**，越界飞控端钳到 ±500 并回 `CLP` |
| `--listen` | ? | 秒数，默认 2 | 发送后继续监听回显的时间；正常 1-2 秒足够 |
| `--dest` | ? | 默认 `0xFF`（广播） | 目标地址；广播即可，`0x61` 显式指定 STM32 |
| `--baud` | ? | 默认 500000 | **仅作记录**，本脚本用 Win32 CreateFile 直接打开，波特率由数传驱动固化 |

### 回显含义速查

| 终端看到 | 含义 |
|---|---|
| ? `[RX 0xA0 GREEN] P01=30.0` | X 轴写入成功（飞控 RAM 已更新） |
| ? `[RX 0xA0 GREEN] P02=-50.0` | Y 轴写入成功 |
| ? `[RX 0xA0 GREEN] P03=80.0` | Z 轴写入成功 |
| ? `[RX 0xA0 GREEN] P01=500.0 CLP` | 输入越界，已限幅到 500（`CLP` = Clamped） |
| ? `[RX 0xA0 RED] P09 UNK` | ID 不在 1/2/3 白名单，写入被拒（`UNK` = Unknown） |
| **没有任何 P0x 回显** | 单帧丢失（链路偶发，~80% 通过率），重发即可 |

### 帧格式（参考）

```
AA FF F2 05 | id(1B) | float_LE(4B) | SC AC
                 │           │
                 │           └─ IEEE754 float，小端序，单位 cm
                 └─ 1=X, 2=Y, 3=Z
```
示例：`AA FF F2 05 01 00 00 F0 41 D2 D4` = 设 X=30.0cm

### 阶段2 完整使用流程（让新目标真正生效）

写入只改飞控 RAM 副本，**任务运行中不会突变**（const 锁定语义，确保飞行安全）。要让新值生效：

1. 把 CH6 拨回（停止 PID3D 任务）
2. 用 `send_param.py` 写入三轴新目标
3. 再次拨 CH6 触发 PID3D 任务
4. 任务启动会在终端打印一行 `3D INIT gx:33.0 gy:44.0 gz:55.0` 确认采用新值
5. 单次飞行结束想换目标 → **回到第 1 步**

?? **断电会丢值**：所有 GOAL 是 RAM 变量，不持久化。重启后回默认值（X=50, Y=0, Z=0），每次开机需重新写。

### 阶段2 故障排查

| 现象 | 排查 |
|---|---|
| `OSError: CreateFile ... GetLastError=0` | 匿名上位机V7 没关，或上一个脚本没退干净。关掉占用进程重试 |
| 没收到任何 `P0x` 回显 | 1) 单帧偶发丢失，重发；2) 飞控未烧录阶段2固件；3) 飞控未上电；4) 串口选错 |
| 收到 `P0x` 但任务行为不变 | CH6 没重新触发；或飞控真的没烧录阶段2 |
| `COM11` 突然消失 | 拔插数传 USB 重新枚举 |

## 故障排查（阶段1 通用）

| 现象 | 排查 |
|------|------|
| 终端无任何 RX 帧 | 串口选错；数传未上电；STM32 没烧录新代码（断电重启过没？）|
| RX 有其他帧（0x03/0x07 等）但无 0xA0 | F1 没解析成功；查 STM32 端 `Uplink_Cmd_Dispatch` 是否被调用 |
| 0xA0 内容是空或乱码 | `s_log_str` 缓冲共享冲突；缩小回显频率 |
| 数传完全不放行 F1 帧 | 切到阶段计划 fallback：用 0xE2 探路（修改 `send_f1.py` 的 CMD 即可） |
