# 凌霄无人机 GUI 上位机 Ubuntu 22.04 完整复现说明

## 目的

把当前仓库里的 `gui` 桌面上位机界面与功能，在 Ubuntu 22.04 上尽量“完完全全一模一样”复现出来。

本说明面向 Ubuntu 侧 Codex/开发者，目标是：

1. 明确需要打包交付哪些目录和文件；
2. 明确 GUI 依赖哪些 Python/系统库；
3. 明确 GUI 是否依赖 STM32 工程源码；
4. 明确 Windows 专用串口层在 Ubuntu 上必须如何适配；
5. 给出从解压、建环境、安装依赖、适配串口、运行、测试到真机验证的完整步骤。

结论先行：

- GUI 主体是 Python + PySide6 桌面程序，入口是 `python -m gui.main`。
- GUI **不需要编译或链接 STM32 工程源码**，也不依赖 Keil、STM32 HAL、`.uvprojx`、`ProjectSTM32F407`、`FcSrc` 等工程文件才能启动界面。
- GUI **运行时依赖匿名通信协议组帧/解帧代码**：当前通过 `gui/io/protocol.py` 复用 `groundTest/ano_protocol.py`。
- GUI **当前硬件串口 I/O 层是 Windows 专用实现**：`gui/io/serial_worker.py` 复用 `groundTest/win_serial.py`，该文件使用 `ctypes.windll.kernel32/CreateFile/ReadFile/WriteFile`，Ubuntu 上不能直接工作。
- Ubuntu 复现如果只跑离线界面和 FakeWorker 仿真，基本原样可跑；如果要连接真实飞控/匿名数传，必须把串口层替换为 Linux/pyserial 版本。

## 需要打包给 Ubuntu 侧的内容

最小可复现包建议从仓库根目录打包这些内容：

```text
ANO_LX_FC/
├── gui/
│   ├── __init__.py
│   ├── main.py
│   ├── README.md
│   ├── requirements.txt
│   ├── config.json
│   ├── path_viz_master_plan.md
│   ├── replay_fix.py
│   ├── assets/
│   ├── commands/
│   ├── io/
│   ├── services/
│   ├── sources/
│   ├── widgets/
│   └── test/
├── groundTest/
│   ├── ano_protocol.py
│   ├── win_serial.py
│   ├── requirements.txt
│   ├── README.md
│   ├── send_f1.py
│   ├── send_param.py
│   ├── send_xyz.py
│   ├── monitor.py
│   ├── list_ports.py
│   ├── test_uart1.py
│   ├── read_uart5.py
│   ├── ano_rpi_driver.py
│   └── Raspberry_Pi_IMU_Driver_Guide.md
├── 数据帧.md
└── dev.md
```

推荐压缩命令（Windows PowerShell，在仓库根目录执行）：

```powershell
Compress-Archive -Force `
  -Path gui, groundTest, 数据帧.md, dev.md `
  -DestinationPath lingxiao_gui_ubuntu22_port.zip
```

不要只发 `gui/` 一个目录。原因：

- `gui/io/protocol.py` 会把仓库根目录下的 `groundTest/` 加进 `sys.path`，然后导入 `ano_protocol.py`；
- `gui/io/serial_worker.py` 当前会导入 `groundTest/win_serial.py`；
- `dev.md` 与 `数据帧.md` 是以前开发记忆/协议记录的一部分，可帮助 Ubuntu 侧 Codex 对齐功能和协议语义；
- `groundTest/send_f1.py`、`send_param.py`、`send_xyz.py` 是命令下发逻辑的命令行参照实现，虽然 Windows 串口部分要适配，但组帧语义有参考价值。

不需要打包这些内容来复现 GUI：

```text
ProjectSTM32F407/
ProjectMSP432/
ProjectTM4C123/
DriversMcu/
DriversBsp/
FcSrc/
用户手册/
wave/
sim_pid/
pid_test/
Project*/build/
__pycache__/
.pytest_cache/
.venv/
gui/logs/
gui/data/*.jsonl
```

说明：

- `FcSrc/Uplink_Cmd.c/.h` 是 F1/F2/F3 飞控固件回执协议的来源参考，但 GUI 运行不 import 它；
- `用户手册/匿名通信协议V7.pdf` 对后续协议核验有帮助，但不是 GUI 启动必需项，文件较大时可不打包；
- `gui/logs/` 和 `gui/data/*.jsonl` 是历史运行日志/记录文件，不是复现必需项；
- `__pycache__`、`.venv` 是本机生成物，不要打包。

## GUI 项目功能范围

当前 `gui` 是“凌霄无人机桌面上位机”，主要由以下模块组成。

### 入口与主窗口

- 入口：`gui/main.py`
- 运行方式：`python -m gui.main`
- 主窗口类：`MainWindow`
- 窗口标题：`凌霄无人机 上位机 v0.1.0-A`
- 中心布局：
  - 顶部连接栏 `ConnectionBar`
  - 命令面板 `CommandPanel`
  - 日志视图 `LogView`
  - 上下可拖动 `QSplitter`
  - 右侧/底部可停靠功能 Dock

### 连接栏

文件：

```text
gui/widgets/connection_bar.py
gui/io/serial_ports.py
gui/io/serial_worker.py
gui/io/fake_worker.py
```

功能：

- 枚举串口；
- 手动输入串口名；
- 连接/断开；
- 显示当前连接状态；
- 未连接时禁用命令发送；
- 支持 `LINGXIAO_GUI_FAKE=1` 离线仿真模式。

Windows 当前实现：

- `serial_ports.py` 只在 `sys.platform == "win32"` 时读取注册表；
- `serial_worker.py` 使用 `groundTest/win_serial.py`；
- `win_serial.py` 使用 Win32 API：`CreateFileW`、`ReadFile`、`WriteFile`、`SetCommTimeouts`。

Ubuntu 必须适配：

- 串口枚举从 Windows 注册表改为 `/dev/ttyUSB*`、`/dev/ttyACM*`、`/dev/ttyAMA*` 等；
- 串口读写从 `Win32Serial` 改为 `pyserial.Serial` 或兼容封装类。

### 命令面板

文件：

```text
gui/widgets/command_panel.py
gui/widgets/confirm_dialog.py
gui/widgets/stable_spinbox.py
gui/services/command_registry.py
gui/services/ack_matcher.py
gui/commands/__init__.py
gui/commands/cmd_f1.py
gui/commands/cmd_f2.py
gui/commands/cmd_f3.py
gui/commands/cmd_placeholder.py
gui/io/protocol.py
groundTest/ano_protocol.py
```

已实现命令：

1. `链路验证 F1`
   - CMD：`0xF1`
   - DATA：`S16 x + S16 y`，小端，共 4 字节；
   - 组帧函数：`build_f1_xy(dest, x, y)`；
   - 回执文本：`F1: X=.. Y=..`；
   - 主要用于链路验证。

2. `参数写入 F2`
   - CMD：`0xF2`
   - DATA：`U8 param_id + float32_LE value`，共 5 字节；
   - 参数 ID：
     - `0x01`：目标 X 位置，cm；
     - `0x02`：目标 Y 位置，cm；
     - `0x03`：目标 Z 位置，cm；
   - GUI 输入范围：`-600.0 ~ 600.0 cm`；
   - 飞控侧限幅提示：`±500 cm`；
   - 回执：
     - `P01=50.0`：成功；
     - `P01=500.0 CLP`：被飞控限幅；
     - `P?? UNK`：未知 ID。

3. `三轴目标 F3`
   - CMD：`0xF3`
   - DATA：`float32_LE x + float32_LE y + float32_LE z`，共 12 字节；
   - 组帧函数：`build_f3_xyz(dest, x, y, z)`；
   - 原子写入三轴目标，避免三帧拆开发送时状态撕裂；
   - 回执：
     - `P*=30.0,44.0,55.0`：成功；
     - `P*=500.0,44.0,55.0 CLP`：至少一个轴触发限幅。

4. 占位命令
   - `飞行控制（占位）`：CMD `0xE1`，不发送；
   - `模式切换（占位）`：CMD `0xE2`，不发送；
   - UI 中显示“开发中/固件未实现”，发送按钮永久禁用。

命令通用机制：

- 命令模块导入即注册到 `REGISTRY`；
- 敏感命令走二次确认弹窗；
- 发送前先登记 `AckMatcher`，避免极快回执漏匹配；
- 跨线程发送必须使用 `QByteArray(frame)`；
- 回执超时不自动重发，只提示用户手动“重发上次”。

### 日志、报警、状态栏

文件：

```text
gui/widgets/log_view.py
gui/services/log_service.py
gui/services/alarm_service.py
```

功能：

- 彩色分级日志：DEBUG/INFO/WARN/ERROR；
- 日志保存到 `gui/logs/gui_YYYYMMDD_HHMMSS.txt`；
- 日志视图可暂停滚动、清屏、导出；
- `ERROR` 弹窗；
- `WARN` 状态栏提示；
- 状态栏显示连接状态、RX/TX 字节计数、最后接收时刻；
- 文件菜单可导出日志、打开日志目录、退出。

Ubuntu 注意：

- `MainWindow._on_open_log_dir()` 当前使用 `os.startfile(folder)`，这是 Windows 专用 API；
- Ubuntu 需要替换为 `xdg-open` 或 `QDesktopServices.openUrl(QUrl.fromLocalFile(folder))`。

### 配置持久化和主题

文件：

```text
gui/services/config_service.py
gui/services/theme_service.py
gui/assets/*.svg
gui/config.json
```

功能：

- 配置文件位置：当前项目内 `gui/config.json`；
- 持久化内容：
  - `last_port`
  - 窗口大小/位置
  - `splitter_sizes`
  - 主题
  - 日志目录
  - Dock 显隐状态
  - Dock 布局 `ui.main_window_state`
  - 路径可视化所有设置
  - 数字面板/HUD 设置
- 主题支持暗色/浅色；
- 下拉箭头 SVG 资源来自 `gui/assets/`。

注意：

- README 里旧说法写过 `%APPDATA%/Lingxiao_GUI/config.json`，但当前 `ConfigService` 实际使用的是项目内 `gui/config.json`；
- Ubuntu 复现时应保留 `gui/config.json`，否则首次运行会用 `_DEFAULTS` 自动生成/补齐。

### 遥测解码、路径追踪、数据总线

文件：

```text
gui/services/telemetry_decoder.py
gui/services/telemetry_models.py
gui/services/path_tracker.py
gui/services/telemetry_bus.py
```

接收帧来源：

- 所有串口入站帧都会进入 `MainWindow._on_frame()`；
- 先喂给 `TelemetryBus.feed_frame(fr)`；
- 再判断是否是 `0xA0` 字符串回执；
- 非 `0xA0` 普通遥测帧只写 DEBUG 日志。

解码帧：

- `0x03`：欧拉角姿态 fallback；
- `0x04`：四元数姿态，优先级高于 `0x03`；
- `0x05`：高度；
- `0x07`：速度；
- 坐标/单位根据 `path_viz_master_plan.md` 里的 P0 结论：
  - 机体系：FLU，机头 `x+`、左侧 `y+`、上方 `z+`；
  - 世界系/地理系：NWU，北 `x+`、西 `y+`、天 `z+`；
  - `0x07` 速度是大地 NWU 系下的量，单位 cm/s；
  - `0x05` 高度单位 cm。

路径追踪：

- 后台积分常驻；
- 渲染开关只控制是否广播 `path_updated`；
- 开启路径可视化时快照 `yaw0`；
- 世界系不随之后 yaw 旋转；
- X/Y 来自速度积分；
- Z 来自 `0x05` 绝对高度；
- 路径支持时间衰减和点数上限。

### 3D/2D 路径可视化

文件：

```text
gui/widgets/path_visualization_widget.py
gui/widgets/path_2d_view_widget.py
gui/widgets/_path_segments.py
gui/widgets/hud_overlay_widget.py
gui/widgets/numeric_panel_dock.py
gui/widgets/_hud_model.py
gui/sources/interfaces.py
```

3D 视图：

- 基于 `pyqtgraph.opengl`；
- 依赖 `PyOpenGL`；
- 包含 3D 网格、路径线、小立方体、机头小球、速度箭头、坐标轴、标尺、HUD 叠加层；
- 支持设置面板；
- 支持路径渐隐；
- 支持视角预设；
- 支持导出轨迹 CSV；
- 支持开始/停止传感器帧 JSONL 记录；
- 如果缺少 `pyqtgraph.opengl` 或 `PyOpenGL`，会显示降级提示。

2D 视图：

- 基于 `pyqtgraph.PlotWidget`；
- 三个 Dock：
  - `路径可视化 · XY`
  - `路径可视化 · XZ`
  - `路径可视化 · YZ`
- 支持固定范围/自动范围；
- 支持网格；
- 支持路径渐隐；
- 支持机体图标和航向来源设置。

数字面板：

- 独立 Dock；
- 显示 X/Y/Z/H、roll/pitch/yaw、vx/vy/vz、速度模长等；
- 可按 HUD 设置控制显示项。

### 传感器帧记录与回放辅助

文件：

```text
gui/services/frame_recorder.py
gui/replay_fix.py
gui/data/*.py
```

功能：

- 可从文件菜单或 3D 可视化面板开始/停止记录；
- 记录格式：JSON Lines，默认文件名 `lingxiao_frames_YYYYMMDD_HHMMSS.jsonl`；
- 记录白名单主要是姿态/高度/速度等遥测帧；
- `gui/data/*.py` 是历史分析、验证、回放修复脚本，不是 GUI 启动必需项，但建议一并保留以便调试路径可视化。

## Python 和系统依赖

### Python 包依赖

当前 `gui/requirements.txt`：

```text
PySide6==6.11.1
numpy
pyqtgraph>=0.14,<0.15
PyOpenGL
```

Ubuntu 真机串口适配还需要：

```text
pyserial>=3.5
```

建议 Ubuntu 22.04 使用 Python 3.10 或 3.11。Ubuntu 22.04 默认 Python 3.10 可用。

建议生成的 Ubuntu 版 requirements：

```text
PySide6==6.11.1
numpy
pyqtgraph>=0.14,<0.15
PyOpenGL
pyserial>=3.5
```

### Ubuntu 系统包依赖

建议安装：

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  libgl1 libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xfixes0 \
  mesa-utils xdg-utils
```

说明：

- PySide6/Qt 在 Ubuntu 上常见缺库是 `xcb` 系列；
- 3D 视图依赖 OpenGL/Mesa/GPU 环境；
- `xdg-utils` 用于替代 Windows 的 `os.startfile` 打开日志目录。

## STM32 依赖判断

### 不依赖 STM32 工程源码的部分

以下 GUI 功能不需要 STM32 源码即可运行：

- 主窗口；
- 连接栏 UI；
- 命令面板 UI；
- F1/F2/F3 组帧；
- 回执匹配逻辑；
- 日志/报警/主题/配置；
- FakeWorker 离线仿真；
- 3D/2D 路径可视化；
- 数字面板；
- 传感器帧记录；
- 大多数 smoke 测试。

### 依赖飞控固件“协议兼容”的部分

这些功能不依赖源码文件，但依赖真实飞控固件已经实现相同协议：

- F1/F2/F3 命令被飞控接收和执行；
- 飞控通过 `0xA0` 字符串帧回执；
- 飞控持续上报 `0x03/0x04/0x05/0x07` 遥测帧；
- F2/F3 限幅、UNK、CLP 回执语义与 GUI 正则一致。

### 仅作为参考的 STM32 文件

这些文件是协议来源/对照，不是 GUI 运行依赖：

```text
FcSrc/Uplink_Cmd.c
FcSrc/Uplink_Cmd.h
FcSrc/ANO_DT_LX.c
FcSrc/ANO_DT_LX.h
```

如果 Ubuntu 侧只复现上位机，不需要编译这些文件。

如果 Ubuntu 侧要继续扩展命令，则建议让 Codex 查阅这些文件或让用户额外提供相关片段。

## Ubuntu 22.04 复现步骤

以下步骤给 Ubuntu 侧 Codex 直接执行。

### 1. 解压并进入项目根目录

```bash
unzip lingxiao_gui_ubuntu22_port.zip -d lingxiao_gui_port
cd lingxiao_gui_port
```

确认目录：

```bash
find . -maxdepth 3 -type f | sort | sed -n '1,200p'
test -f gui/main.py
test -f gui/requirements.txt
test -f groundTest/ano_protocol.py
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

### 3. 安装依赖

```bash
pip install -r gui/requirements.txt
pip install 'pyserial>=3.5'
```

验证：

```bash
python - <<'PY'
import sys
print(sys.executable)
import PySide6, numpy, pyqtgraph, OpenGL, serial
print("deps ok")
PY
```

### 4. 先跑离线 FakeWorker 模式

FakeWorker 不需要串口硬件，也不需要 Windows 串口层，适合先验证 UI 和命令链路。

```bash
export LINGXIAO_GUI_FAKE=1
python -m gui.main
```

预期：

- 窗口能打开；
- 日志提示进入 FakeWorker 离线仿真模式；
- 命令面板能看到 F1/F2/F3/占位命令；
- 功能菜单能打开 3D/XY/XZ/YZ/数字面板；
- 3D 视图如有可用 OpenGL，应显示网格/路径/机体元素；
- 如果 OpenGL 不可用，3D 视图应显示“缺少 pyqtgraph.opengl / PyOpenGL”的降级提示，不应导致整个 GUI 崩溃。

### 5. 运行 smoke 测试

先跑不需要真串口的核心测试：

```bash
export LINGXIAO_GUI_FAKE=1
python -m gui.test._smoke_phase_a
python -m gui.test._smoke_phase_b
python -m gui.test._smoke_phase_c
python -m gui.test._smoke_phase_d
python -m gui.test._smoke_phase_e
python -m gui.test._smoke_phase_p1
python -m gui.test._smoke_phase_p2
python -m gui.test._smoke_phase_p5_5
python -m gui.test._smoke_phase_p6
python -m gui.test._smoke_phase_p7
python -m gui.test._smoke_phase_p8
python -m gui.test._smoke_phase_p9
python -m gui.test._smoke_phase_p10
```

说明：

- 某些测试会设置 `QT_QPA_PLATFORM=offscreen`；
- offscreen/headless 下 OpenGL 可能无法创建上下文，这种情况下视觉渲染相关测试可能跳过或只验证非 GL 部分；
- 如果要完整验证 3D 视觉，应在真实桌面会话中运行 `python -m gui.main`。

### 6. Ubuntu 串口适配

当前不能直接在 Ubuntu 真机连接飞控，因为：

- `gui/io/serial_worker.py` 固定导入 `from win_serial import Win32Serial`；
- `groundTest/win_serial.py` 使用 Windows `ctypes.windll.kernel32`；
- `gui/io/serial_ports.py` 在非 Windows 直接返回空列表。

Ubuntu 侧 Codex 应做下面两处最小改动。

#### 6.1 新增 Linux 串口封装

新增文件：`groundTest/linux_serial.py`

```python
# -*- coding: utf-8 -*-
from __future__ import annotations

import time
import serial


class LinuxSerial:
    """与 Win32Serial 兼容的最小 Linux 串口封装。"""

    def __init__(self, port: str, baudrate: int = 500000):
        self._port = port
        self._baudrate = baudrate
        self._ser: serial.Serial | None = None

    def open(self) -> None:
        self._ser = serial.Serial(
            self._port,
            self._baudrate,
            timeout=0,
            write_timeout=0.2,
        )

    def write(self, data: bytes) -> int:
        if self._ser is None:
            raise RuntimeError("port not open")
        return int(self._ser.write(data))

    def read_nonblocking(self, max_bytes: int = 4096, wait_s: float = 0.05) -> bytes:
        if self._ser is None:
            raise RuntimeError("port not open")
        deadline = time.time() + wait_s
        while time.time() < deadline:
            n = int(self._ser.in_waiting or 0)
            if n > 0:
                return bytes(self._ser.read(min(max_bytes, n)))
            time.sleep(0.005)
        return b""

    def close(self) -> None:
        if self._ser is not None:
            self._ser.close()
            self._ser = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
```

#### 6.2 修改 `gui/io/serial_worker.py`

把原来的固定导入：

```python
from win_serial import Win32Serial
```

改为跨平台导入：

```python
if sys.platform == "win32":
    from win_serial import Win32Serial as SerialImpl  # noqa: E402
else:
    from linux_serial import LinuxSerial as SerialImpl  # noqa: E402
```

并把：

```python
self._ser: Optional[Win32Serial] = None
...
ser = Win32Serial(port_name)
```

改为：

```python
self._ser: Optional[SerialImpl] = None
...
ser = SerialImpl(port_name)
```

类型注解如果引起 linter 问题，可直接改为 `Optional[object]`。

#### 6.3 修改 `gui/io/serial_ports.py`

保留 Windows 逻辑，在 Linux 上增加 glob 枚举。

建议实现：

```python
from __future__ import annotations

import glob
import os
import sys


def list_serial_ports() -> list[tuple[str, str]]:
    """枚举串口。失败回空列表，绝不抛异常。"""
    if sys.platform == "win32":
        try:
            import winreg  # type: ignore
        except Exception:
            return []
        results: list[tuple[str, str]] = []
        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM"
            ) as key:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)
                    except OSError:
                        break
                    results.append((str(value), str(name)))
                    i += 1
        except FileNotFoundError:
            return []
        except Exception:
            return []

        def _sort_key(item: tuple[str, str]) -> tuple[int, str]:
            port = item[0]
            try:
                return (int(port.lstrip("COM")), port)
            except ValueError:
                return (10_000, port)

        results.sort(key=_sort_key)
        return results

    patterns = [
        "/dev/ttyUSB*",
        "/dev/ttyACM*",
        "/dev/ttyAMA*",
        "/dev/ttyS*",
    ]
    ports: list[str] = []
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    ports = sorted(set(ports))
    return [(p, os.path.basename(p)) for p in ports]
```

#### 6.4 修改打开日志目录

`gui/main.py` 的 `_on_open_log_dir()` 当前使用：

```python
os.startfile(folder)
```

Ubuntu 应改为 Qt 跨平台方式：

```python
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
```

这是比 `subprocess.run(["xdg-open", folder])` 更适合 PySide6 的实现。

### 7. 真机串口运行

确认设备：

```bash
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
dmesg | tail -50
```

把当前用户加入串口权限组：

```bash
sudo usermod -aG dialout "$USER"
```

然后注销/重新登录，再确认：

```bash
groups
```

运行：

```bash
unset LINGXIAO_GUI_FAKE
python -m gui.main
```

在连接栏选择或手动输入：

```text
/dev/ttyUSB0
```

或：

```text
/dev/ttyACM0
```

根据实际设备为准。

### 8. 真机功能验证

建议顺序：

1. 打开 GUI；
2. 连接真实串口；
3. 观察状态栏“已连接”；
4. 观察 RX 字节计数是否增长；
5. 观察“最后接收”时间是否刷新；
6. 发送 F1：
   - X 填 `1234`
   - Y 填 `-456`
   - 预期日志出现 `F1: X=1234 Y=-456` 或等价回执；
7. 发送 F2：
   - ID `0x01`
   - Value `30.0`
   - 预期回执 `P01=30.0`；
8. 发送 F2 限幅测试：
   - ID `0x01`
   - Value `600.0`
   - 预期回执带 `CLP`；
9. 发送 F3：
   - X `30.0`
   - Y `44.0`
   - Z `55.0`
   - 预期回执 `P*=30.0,44.0,55.0`；
10. 打开“功能”菜单：
    - 勾选 `路径可视化（3D）`
    - 勾选 `路径可视化 · XY`
    - 勾选 `数字面板`
11. 晃动/移动飞机，检查轨迹、姿态、速度、数字面板是否更新；
12. 开始传感器帧记录，保存 JSONL；
13. 导出轨迹 CSV；
14. 断开串口，确认界面不卡死，挂起命令被取消。

## 建议给 Ubuntu 侧 Codex 的任务提示词

可以把下面这段直接发给 Ubuntu 侧 Codex：

```text
你现在拿到的是凌霄无人机 GUI 上位机的最小复现包。请先阅读 gui/UBUNTU22_PORTING_GUIDE.md、gui/README.md、gui/path_viz_master_plan.md、dev.md、数据帧.md，然后完成 Ubuntu 22.04 复现。

要求：
1. 保持 GUI 功能和现有结构不变，入口仍为 python -m gui.main。
2. 不要重写 UI，不要删除 F1/F2/F3、日志、报警、路径可视化、2D 视图、数字面板、记录/导出等功能。
3. 先安装依赖并跑 LINGXIAO_GUI_FAKE=1 的离线模式。
4. 再做最小 Linux 串口适配：
   - 新增 groundTest/linux_serial.py，用 pyserial 实现 open/write/read_nonblocking/close；
   - 修改 gui/io/serial_worker.py，在 win32 用 Win32Serial，在 Linux 用 LinuxSerial；
   - 修改 gui/io/serial_ports.py，在 Linux 枚举 /dev/ttyUSB*、/dev/ttyACM*、/dev/ttyAMA*、/dev/ttyS*；
   - 修改 gui/main.py 的 os.startfile 为 QDesktopServices.openUrl(QUrl.fromLocalFile(folder))。
5. 跑 gui/test 下的 smoke 测试，优先保证 FakeWorker、命令、配置、路径追踪、2D/3D 非硬件逻辑通过。
6. 真机验证时使用 /dev/ttyUSB0 或 /dev/ttyACM0，必要时把用户加入 dialout 组。
7. 如果 OpenGL 在 headless/offscreen 下失败，不要误判为 GUI 失败；需要在真实桌面会话中验证 3D 视图。
```

## 注意事项

1. 不要把 Windows 本机 `.venv` 打包给 Ubuntu。
2. 不要在 Ubuntu 上沿用 README 里的 `C:\Users\20399\...Python313\python.exe`。
3. 不要直接运行 `python gui/main.py` 作为首选；推荐 `python -m gui.main`。
4. `gui/config.json` 里 `last_port` 可能是 `COM15`，Ubuntu 首次运行后应改成 `/dev/ttyUSB0` 或实际设备。
5. 当前 `gui/io/protocol.py` 依赖 `groundTest/ano_protocol.py`，所以 `groundTest` 必须和 `gui` 同级放在仓库根目录。
6. Ubuntu 真机串口必须适配 `win_serial.py`，否则导入阶段或打开串口阶段会失败。
7. `FakeWorker` 是跨平台的，用它可以先确认 UI、命令注册、回执匹配、路径可视化管线是否正常。
8. `pyqtgraph.opengl` 需要 OpenGL；SSH/headless/offscreen 环境可能失败，真实显示器/桌面环境更可靠。
9. 如果 Qt 报 `xcb` 插件错误，优先补装本文“Ubuntu 系统包依赖”里的 `libxcb-*` 包。
10. 如果串口打开权限不足，执行 `sudo usermod -aG dialout "$USER"` 后必须注销重登。
11. F1/F2/F3 的飞控执行效果依赖 STM32 固件已经烧录对应上行命令处理逻辑；GUI 自身不包含也不编译该固件。
12. 旧文档中提到 `/memories/session/plan.md`、`/memories/repo/gui-architecture.md`、`gui/requirements_lock_checklist.md`，但当前交付包/仓库未发现这些文件；可用 `dev.md`、`gui/README.md`、`gui/path_viz_master_plan.md` 作为现有开发记忆来源。

## 最终验收标准

Ubuntu 侧复现完成后，至少满足：

- `python -m gui.main` 能启动；
- `LINGXIAO_GUI_FAKE=1 python -m gui.main` 能离线运行；
- F1/F2/F3 命令面板存在并能在 FakeWorker 下看到回执；
- 连接栏在 Linux 能列出 `/dev/ttyUSB*` 或 `/dev/ttyACM*`；
- 真机串口能连接、断开且 UI 不假死；
- RX/TX 字节计数和最后接收时间能更新；
- 日志、导出日志、清屏、暂停滚动可用；
- 主题切换可用；
- 功能菜单里的 3D、XY、XZ、YZ、数字面板 Dock 可开关；
- 传感器帧 JSONL 记录可开始/停止；
- 轨迹 CSV 可导出；
- 关闭窗口能保存配置；
- 重启后窗口尺寸、Dock 显隐、路径可视化设置能恢复。
