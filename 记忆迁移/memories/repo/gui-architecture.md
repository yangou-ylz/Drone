# 凌霄 GUI 上位机 — 架构备忘

## 模块边界（3 层）

1. **UI**：`gui/widgets/` + `gui/main.py`
   - 只与 Service 层信号槽通信，不直接拿 worker、protocol
2. **Service**：`gui/services/`
   - `REGISTRY`（命令注册表）/ `AckMatcher`（发送-回执 token 配对）/ `LogService` / `AlarmService` / `ConfigService` / `ThemeService`
3. **I/O**：`gui/io/`
   - `SerialWorker`（真硬件，moveToThread）/ `FakeWorker`（鸭子类型，相同信号）/ `protocol.py`

## 关键设计决策

### 决策 1：单命令一文件 + REGISTRY 自注册

每条 `cmd_xxx.py` 在模块顶层 `REGISTRY.register(CmdXxx())`，
`gui/commands/__init__.py` 只负责 `from . import cmd_xxx`。
**好处**：新增命令完全本地化，CommandPanel/AckMatcher/LogService 不动一行。

### 决策 2：AckMatcher 在主线程 + token

worker 拿到字节流 → 解析 0xA0 → 信号 → 主线程 `_on_frame` → `AckMatcher.handle_text`。
每次发送返回 token，超时由 QTimer 在主线程触发，**无需任何锁**。

### 决策 3：FakeWorker = SerialWorker 鸭子类型

`LINGXIAO_GUI_FAKE=1` 时替换 worker；信号集合、槽签名完全一致；
echo 帧由 QTimer 80ms 延迟构造，模拟回执往返。
**好处**：无飞机也能 8/8 端到端烟雾。

### 决策 4：跨线程发送统一 QByteArray

`Q_ARG(QByteArray, QByteArray(frame))` + `@Slot(QByteArray)`。
Python `bytes` 不是注册的 QMetaType，原生 bytes 跨线程会静默丢。

### 决策 5：Win32 直调 CreateFileW + SetCommTimeouts

`groundTest/win_serial.py` 不走 pyserial（匿名数传不接受 SetCommState）。
`SetCommTimeouts(ReadIntervalTimeout=MAXDWORD)` 让 ReadFile 立即返回，
配合 worker 循环里 `QCoreApplication.processEvents()` 才能响应 `close_port`。

### 决策 6：占位命令也走 REGISTRY

`cmd_placeholder.py` 注册 0xE1/0xE2，`build_frame` 抛 NotImplementedError，
面板按钮永久禁用。UI 一致性 > 特殊路径。

### 决策 7：主题 = 模块级 QSS 字符串

不引入资源文件、不依赖 qt-material 之类的第三方主题包；
`THEMES = {"dark": _DARK_QSS, "light": _LIGHT_QSS}` 直接内联，
切换即 `QApplication.setStyleSheet`，全控件即时刷新。
日志区刻意保留暗背景（长时间盯屏护眼）。

## 测试矩阵

| 烟雾文件 | 覆盖 |
|---------|------|
| `_smoke_phase_d.py` | F1/F2 注册 + 组帧 + 解析 + FakeWorker 端到端 |
| `_smoke_phase_e.py` | 占位命令 + 主题 + 视图菜单 |
| `_smoke_disconnect.py` | FAKE 模式断开按钮 |
| `_smoke_real_disconnect.py` | 真 Win32Serial（mock 句柄）断开 |

## 反模式（已踩过的坑）

1. **SerialWorker tight loop 不 processEvents** → QueuedConnection 永远不被消费
2. **send_bytes(bytes)** → QMetaType "bytes" 找不到，静默
3. **Win32 默认 COMMTIMEOUTS=0** → ReadFile 无限阻塞
4. **占位命令直接不注册** → CommandPanel 看不到，无法在 UI 里"亮槽位"
5. **每个面板自己实现状态灯** → 改一次 6 个文件；改为 CommandPanelBase.set_ack_state 接口
