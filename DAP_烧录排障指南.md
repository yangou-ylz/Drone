# STM32F407 DAP 烧录排障指南

更新时间：2026-07-04

本文档只针对当前工程的 Ubuntu 22.04 + VS Code + Arm GCC + xPack OpenOCD + CMSIS-DAP 路线。

## 1. 推荐验收顺序

在插入 DAP 和 STM32F407 板子后执行：

```bash
cd /home/ubuntu22/stm32/ANO_LX_FC
./scripts/check-dap.sh
./scripts/probe-dap.sh
./scripts/flash-dap.sh
```

含义：

- `check-dap.sh`：只检查 USB 是否能看到调试器。
- `probe-dap.sh`：只连接目标芯片，不擦除、不烧录。
- `flash-dap.sh`：烧录 `build-gcc/ANO_LX.elf` 并 verify。

如果出错，先执行：

```bash
./scripts/diagnose-dap.sh
```

诊断日志会保存到：

```text
ANO_LX_FC/logs/dap-diagnostics-YYYYMMDD-HHMMSS.log
```

## 2. 常见问题判断

### 2.1 `lsusb` 完全看不到 DAP

优先检查：

- DAP 是否插在电脑 USB 口，不要先经过不稳定扩展坞。
- USB 线是否是数据线，不是只能充电的线。
- DAP 指示灯是否亮。
- 换一个 USB 口后重新运行 `./scripts/check-dap.sh`。

这类问题通常不是 OpenOCD 配置问题，因为系统层面还没有识别到设备。

### 2.2 能看到 DAP，但 OpenOCD 报 `Permission denied`

根因通常是普通用户没有 USB HID/libusb 访问权限。

处理原则：

- 不长期用 root 启动 VS Code。
- 优先添加 udev 规则。
- 需要实际 DAP 的 VID:PID 后才能写精确规则，例如 `xxxx:yyyy`。

获取 VID:PID：

```bash
lsusb
```

也可以运行项目内建议脚本：

```bash
./scripts/suggest-udev-rule.sh
```

该脚本只打印建议，不会写入 `/etc/udev/rules.d/`，不会执行 `sudo`。

规则形态通常类似：

```text
SUBSYSTEM=="usb", ATTR{idVendor}=="xxxx", ATTR{idProduct}=="yyyy", MODE="0666", GROUP="plugdev", TAG+="uaccess"
```

是否写入 `/etc/udev/rules.d/` 需要用户确认，因为这是系统配置变更。

### 2.3 OpenOCD 报 `unable to open CMSIS-DAP device`

可能原因：

- DAP 没插好或被其他程序占用。
- udev 权限未配置。
- DAP 固件不兼容 CMSIS-DAP v1/v2。
- 当前 OpenOCD `adapter driver cmsis-dap` 与设备类型不匹配。

排查顺序：

1. 运行 `./scripts/check-dap.sh` 确认 USB 可见。
2. 关闭可能占用 DAP 的程序。
3. 运行 `./scripts/diagnose-dap.sh` 保存日志。
4. 根据 VID:PID 判断是否需要 udev 规则。

### 2.4 OpenOCD 报 `Error: init mode failed` 或找不到 target

可能原因：

- SWDIO/SWCLK/GND/3V3 接线错误。
- 板子没有供电。
- NRST 连接方式和 `reset_config` 不匹配。
- 目标芯片处于低功耗或被旧程序占用 SWD 引脚。

排查顺序：

1. 确认 GND 共地。
2. 确认 DAP 的 SWDIO 接 MCU SWDIO，SWCLK 接 MCU SWCLK。
3. 确认目标板供电稳定。
4. 如果接了 NRST，保留当前配置再试；如果没接 NRST，可尝试后续改为更宽松的 reset 配置。
5. 若仍失败，再降低 `adapter speed`，例如从 `4000` 改为 `1000`。

当前已经准备好低速无 NRST 备用配置：

```bash
./scripts/probe-dap-low-speed.sh
./scripts/flash-dap-low-speed.sh
```

对应 OpenOCD 配置：

```text
openocd/stm32f407-cmsis-dap-low-speed-no-srst.cfg
```

这个备用配置适合以下情况：

- DAP 没有连接 NRST。
- SWD 线较长或接触不稳定。
- 默认 `adapter speed 4000` 连接失败。
- 默认 `reset_config srst_only ... connect_assert_srst` 连接失败。

### 2.5 烧录 verify 失败

可能原因：

- Flash 写入过程中供电不稳。
- 目标芯片读写保护或锁定。
- 目标芯片型号/Flash 容量与配置不符。
- 连接线过长或 SWD 速度过高。

优先动作：

1. 降低 `openocd/stm32f407-cmsis-dap.cfg` 中的 `adapter speed`。
2. 重新运行 `./scripts/probe-dap.sh`。
3. 再运行 `./scripts/flash-dap.sh`。

## 3. 当前工程路径

- 工程根目录：`/home/ubuntu22/stm32/ANO_LX_FC`
- 构建产物：`build-gcc/ANO_LX.elf`
- OpenOCD 配置：`openocd/stm32f407-cmsis-dap.cfg`
- 低速无 NRST OpenOCD 配置：`openocd/stm32f407-cmsis-dap-low-speed-no-srst.cfg`
- 便携 OpenOCD：`/home/ubuntu22/stm32/tools/xpack-openocd-0.12.0-7/bin/openocd`
- 配置日志：`/home/ubuntu22/stm32/STM32F407_Ubuntu_VSCode_配置日志.md`

## 4. 安全边界

当前已完成的脚本和配置不会：

- 删除系统文件。
- 清理系统缓存。
- 修改系统 Python。
- 修改系统默认 GCC/CMake。
- 写入 `/etc/udev/rules.d/`。
- 自动以 root 权限运行。

真正烧录只会在用户主动运行 `./scripts/flash-dap.sh` 或 VS Code 的 `STM32: Flash with DAP` 任务时发生。
