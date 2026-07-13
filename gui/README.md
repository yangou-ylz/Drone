# 凌霄无人机 GUI 上位机

桌面调参与命令下发软件，配合 STM32F407 飞控 + 匿名数传使用。

## 1. 环境准备

这套 GUI 之前实际开发和验证通过的解释器不是仓库里的 `.venv`，而是固定使用：

```powershell
C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe
```

仓库根目录的 `.venv` 来自 Python 3.14，默认缺 GUI 可视化依赖，**不要把它当成当前可用环境**。

最稳的做法是直接用仓库根目录的 [run_gui.bat](../run_gui.bat)，它已经把解释器锁死到 Python 3.13：

```powershell
cd D:\原E盘\桌面\无人机\凌霄\5.飞控MCU源码工程\ANO_LX_FC\ANO_LX_FC
.\run_gui.bat
```

如果你要在终端里手动运行，也直接用这个解释器：

```powershell
cd D:\原E盘\桌面\无人机\凌霄\5.飞控MCU源码工程\ANO_LX_FC\ANO_LX_FC
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" -m gui.main
```

如果只是想确认当前是不是正确环境，执行：

```powershell
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" -c "import sys; print(sys.executable); import PySide6, numpy, pyqtgraph, OpenGL; print('OK')"
```

当前 GUI 用到的关键三方包：

- `PySide6`：Qt 界面框架
- `numpy`：轨迹/姿态数据计算
- `pyqtgraph`：2D/3D 可视化
- `PyOpenGL`：3D 视图依赖

上面这套 Python 3.13 已确认能导入这些依赖；仓库 `.venv` 目前不能替代它。

## 2. 启动

```powershell
# 真硬件：
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" -m gui.main

# 离线仿真（无飞机，FakeWorker 模拟回执）：
$env:LINGXIAO_GUI_FAKE = "1"
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" -m gui.main
```

也可以直接运行：

```powershell
.\run_gui.bat
```

说明：真正稳定的是“固定 Python 3.13 + `-m gui.main`”这一组合；不要直接信任当前 shell 里的 `python` 指向哪个版本。

## 3. 功能总览

- **连接栏**：选 COM 口、连接/断开，断开后挂起命令自动取消。
- **命令面板**：
  - `链路验证 F1`：发 2 个 S16，飞控回 `F1: X=.. Y=..`（绿）。
  - `参数写入 F2`：选目标轴（X/Y/Z 位置）+ float 值，飞控回 `P01=50.0` 或 `P01=500.0 CLP`（限幅）或 `P?? UNK`（未知 ID，红）。
  - `三轴写入 F3`（命令面板待接）：一帧同时带 X+Y+Z三个 float，原子批量覆盖 GOAL_X/Y/Z；飞控回 `P*=30.0,44.0,55.0` 或末尾带 `CLP`。命令行工具：`python groundTest\send_xyz.py --port COM11 --x 30 --y 44 --z 55`。
  - `飞行控制（占位）` / `模式切换（占位）`：UI 槽位预留，固件未实现，发送按钮永久禁用。
- **日志视图**：彩色分级（DEBUG/INFO/WARN/ERROR），等宽字体，可暂停滚动、清屏、导出。
- **报警**：ERROR 弹窗 + WARN 状态栏闪烁。
- **状态栏**：连接灯、RX/TX 字节计数、最后接收时刻。
- **菜单**：文件（导出日志/打开日志文件夹/退出）、视图（清屏 Ctrl+L、暂停滚动、主题暗/浅）、帮助（关于）。
- **持久化**：窗口大小/位置、分割条比例、主题、日志目录均存 `%APPDATA%/Lingxiao_GUI/config.json`。

## 4. 扩展一条新命令（3 步）

> 注：`0xF1`/`0xF2`/`0xF3` 已占用；下面以预留的 `0xF4 设定增益` 为例。

### Step 1：写组帧函数（`groundTest/ano_protocol.py`）

```python
def build_f4_gain(dest: int, kp: float, ki: float) -> bytes:
    payload = struct.pack("<ff", kp, ki)
    return _wrap_frame(dest, 0xF4, payload)
```

并在 `gui/io/protocol.py` 里 `from groundTest.ano_protocol import build_f4_gain`，加入 `__all__`。

### Step 2：新建 `gui/commands/cmd_f4.py`（参照 `cmd_f2.py`）

```python
from ..services.command_registry import REGISTRY, Command, CommandPanelBase, AckResult
from ..io.protocol import build_f4_gain

class CmdF4(Command):
    cmd_id = 0xF4
    name = "增益写入 F4"
    category = "参数"
    requires_confirm = True
    ack_timeout_ms = 1500

    def build_frame(self, params):
        return build_f4_gain(0xFF, params["kp"], params["ki"])

    def parse_ack(self, text):
        # 用正则识别飞控回的 "G: Kp=... Ki=..."
        ...

    def create_panel(self, parent=None):
        return F4Panel(parent)  # 自行实现 QWidget 子类 + send_requested 信号

REGISTRY.register(CmdF4())
```

### Step 3：在 `gui/commands/__init__.py` 加 1 行 import

```python
from . import cmd_f4  # noqa: F401
```

启动 GUI，新命令立即出现在分类下拉中。**菜单、状态栏、AckMatcher、日志通通不用动**。

## 5. 关键架构

```
┌───────────────────────────────────────────────────────────┐
│            UI (widgets/ + main.py)                         │
│   ConnectionBar    CommandPanel    LogView                 │
└──────────┬──────────────┬───────────────────┬─────────────┘
           │              │                   │
┌──────────▼──────────────▼───────────────────▼─────────────┐
│              Services (services/)                          │
│   REGISTRY  AckMatcher  LogService  AlarmService  Config   │
│              ThemeService                                  │
└──────────┬─────────────────────────────────────────────────┘
           │ QueuedConnection (跨线程)
┌──────────▼─────────────────────────────────────────────────┐
│         I/O 线程 (io/)                                      │
│   SerialWorker  ←→  FakeWorker (LINGXIAO_GUI_FAKE=1)        │
│   protocol.py: parse_frames / build_f1 / build_f2 / ...    │
└────────────────────────────────────────────────────────────┘
```

要点：

- **跨线程 send_bytes 必须用 `QByteArray`**，Python `bytes` 不是注册的 QMetaType。
- **SerialWorker 主循环必须 `QCoreApplication.processEvents()`**，否则 QueuedConnection 入队的 `close_port` 永远收不到。
- **Win32 串口必须 `SetCommTimeouts(ReadIntervalTimeout=MAXDWORD)`**，否则 ReadFile 在空闲时无限阻塞，导致断开按钮无响应。

## 6. 常见故障

| 现象 | 原因 | 修复 |
|------|------|------|
| 点击断开无反应 | Win32 串口没设 COMMTIMEOUTS | 已在 [groundTest/win_serial.py](../groundTest/win_serial.py) 修复 |
| 跨线程 send 报 `Unable to find a QMetaType for "bytes"` | bytes 没被 Qt 注册 | 调用前 `QByteArray(frame)` |
| 命令面板按钮不可点 | 串口未连接 | 先连接 |
| 一打开就提示缺少 pyqtgraph / PyOpenGL | 用错了解释器，跑到了默认 Python 3.14 / `.venv` | 改用 [run_gui.bat](../run_gui.bat) 或 `C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe -m gui.main` |
| 占位命令按钮永远灰 | 设计如此，固件未实现 | 待飞控侧 0xE1/0xE2 实装后再写真实命令模块 |
| 主题切换后日志区底色不变 | 故意：日志暗背景对长时间盯屏更友好 | 不需要改 |

## 7. 开发者自测

```powershell
# 阶段 D：命令注册 + F2 + FakeWorker 端到端（8 项）
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" gui\_smoke_phase_d.py

# 阶段 E：占位命令 + 主题 + 视图菜单
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" gui\_smoke_phase_e.py

# 断开按钮回归
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" gui\_smoke_disconnect.py
& "C:\Users\20399\AppData\Local\Programs\Python\Python313\python.exe" gui\_smoke_real_disconnect.py
```

完整长期计划见 `/memories/session/plan.md`，架构备忘见 `/memories/repo/gui-architecture.md`。
