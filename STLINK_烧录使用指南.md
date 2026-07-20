# STM32 ST-Link Ubuntu 烧录使用指南

本文档是独立 ST-Link 线路，不替代现有 CMSIS-DAP 或 J-Link 脚本。

## 1. 文件说明

- `scripts/check-stlink.sh`：检查 USB 是否能看到 ST-Link，同时显示 udev 和用户组状态。
- `scripts/install-stlink-udev-rule.sh`：安装本机 ST-Link udev 权限规则，需要 sudo 密码。
- `scripts/probe-stlink.sh`：只连接目标芯片，不擦除、不烧录。
- `scripts/diagnose-stlink.sh`：收集 ST-Link USB、udev、OpenOCD direct/HLA 探测日志，不烧录。
- `scripts/flash-stlink.sh`：通过 ST-Link 烧录指定固件。
- `scripts/verify-stlink-env.sh`：本地自检 ST-Link 脚本、OpenOCD 配置和 dry-run 命令。

## 2. 支持目标

`scripts/probe-stlink.sh` 和 `scripts/flash-stlink.sh` 当前支持：

- `f103c8t6`：STM32F103C8T6 / Blue Pill 类板子。
- `f407`：STM32F407 类板子。

目标必须显式写出，脚本不会默认烧录任何已有产物。

## 3. 第一次配置 Ubuntu

进入工程目录：

```bash
cd /home/ubuntu22/stm32/ANO_LX_FC
```

安装 ST-Link udev 规则：

```bash
./scripts/install-stlink-udev-rule.sh --dry-run
```

确认输出无误后再真正安装：

```bash
./scripts/install-stlink-udev-rule.sh
```

这个脚本会写入：

```text
/etc/udev/rules.d/60-stlink-local.rules
```

执行后拔下并重新插入 ST-Link，然后检查：

```bash
./scripts/check-stlink.sh
```

能看到 `STMicroelectronics`、`ST-LINK` 或 `0483:3748` / `0483:374b` / `0483:3752` 等 VID:PID，就说明 USB 层可见。

`check-stlink.sh` 还会显示 `/etc/udev/rules.d/60-stlink-local.rules` 是否存在，以及当前用户是否在 `plugdev` 用户组。

## 4. 接线

ST-Link 走 SWD，常用接线：

- `SWDIO` -> 目标芯片 `SWDIO`
- `SWCLK` -> 目标芯片 `SWCLK`
- `GND` -> 目标板 `GND`
- `3V3` / `VTref` -> 目标板 `3.3V` 参考电压
- `NRST` 可选；当前脚本默认 no-SRST，没接 NRST 也可以尝试。

STM32F103C8T6 常见 Blue Pill 引脚：

- `SWDIO` -> `PA13`
- `SWCLK` -> `PA14`

## 5. 本地自检

不连接硬件也可以先跑本地自检：

```bash
./scripts/verify-stlink-env.sh
```

它会检查：

- ST-Link 脚本语法。
- OpenOCD ST-Link direct / HLA 配置解析。
- F103/F407 dry-run 烧录命令生成。
- F103 目标拒绝误用 F407 `build-gcc/ANO_LX.hex`。
- ST-Link USB 是否可见，非致命。
- udev 规则是否已经安装，非致命。

## 6. 探测，不烧录

先探测 F103：

```bash
./scripts/probe-stlink.sh f103c8t6
```

探测 F407：

```bash
./scripts/probe-stlink.sh f407
```

如果默认 ST-Link backend 对很老的 ST-Link/V2 固件失败，再试 HLA 后备：

```bash
./scripts/probe-stlink.sh --hla f103c8t6
```

## 7. 诊断

如果探测失败，运行诊断脚本。它会尝试 direct 和 HLA 两种连接方式，并把日志保存到 `logs/`：

```bash
./scripts/diagnose-stlink.sh f103c8t6
```

诊断脚本不会擦除或烧录 flash。

## 8. 烧录

F103 `.elf`：

```bash
./scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.elf
```

F103 `.hex`：

```bash
./scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.hex
```

F103 `.bin` 默认写到 `0x08000000`：

```bash
./scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.bin
```

如果需要显式地址：

```bash
./scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.bin 0x08000000
```

F407 示例：

```bash
./scripts/flash-stlink.sh f407 build-gcc/ANO_LX.hex
```

老 ST-Link/V2 固件后备：

```bash
./scripts/flash-stlink.sh --hla f103c8t6 /path/to/f103_app.elf
```

## 9. dry-run

烧录前可以先 dry-run，确认最终 OpenOCD 命令：

```bash
./scripts/flash-stlink.sh --dry-run f103c8t6 /path/to/f103_app.elf
```

dry-run 不会启动 OpenOCD，不会擦除或写入 flash。

## 10. VS Code 任务

也可以在 VS Code 里运行：

1. 打开 Command Palette。
2. 选择 `Tasks: Run Task`。
3. 选择下面任一 ST-Link 任务。

已新增的 ST-Link 任务：

- `STM32: Verify ST-Link Environment`
- `STM32: Check ST-Link USB`
- `STM32: Install ST-Link udev Rule`
- `STM32: Probe ST-Link F103C8T6`
- `STM32: Diagnose ST-Link F103C8T6`
- `STM32: Probe ST-Link F103C8T6 HLA`
- `STM32: Probe ST-Link F407`
- `STM32: Diagnose ST-Link F407`
- `STM32: Flash F103C8T6 with ST-Link Dry Run`
- `STM32: Flash F103C8T6 with ST-Link`
- `STM32: Flash F407 with ST-Link`

F103 烧录任务会要求输入 F103 固件路径，不会默认使用 F407 的 `build-gcc/ANO_LX.hex`。

## 11. 安全边界

- ST-Link 脚本独立于原 DAP 脚本。
- 原 F407 DAP 烧录仍使用 `./scripts/flash-dap.sh`。
- F103 ST-Link 烧录必须显式传入 F103 固件文件。
- `scripts/flash-stlink.sh f103c8t6 build-gcc/ANO_LX.hex` 会被拒绝，防止把 F407 固件误烧进 F103。

## 12. 成功标志

真实烧录成功时，OpenOCD 输出里应出现类似：

```text
** Verified OK **
```

如果探测失败，优先检查：

- ST-Link 是否被 `./scripts/check-stlink.sh` 看到。
- udev 规则是否安装并拔插过 ST-Link。
- SWDIO/SWCLK/GND/3V3 是否接对。
- 目标板是否单独供电或由 ST-Link 正确供电。
- 是否需要 `--hla` 后备模式。
