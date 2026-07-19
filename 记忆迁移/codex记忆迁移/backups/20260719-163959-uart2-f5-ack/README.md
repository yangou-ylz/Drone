# 20260719-163959-uart2-f5-ack

备份原因：树莓派侧已完成 0xF5 黄金帧构造与发送准备，要求飞控侧完成 UART2 RX、0xF5 解析和 UART2 TX 0xA0 ACK。

备份范围：
- `FcSrc/Uplink_Cmd.c`
- `FcSrc/Uplink_Cmd.h`
- `DriversMcu/STM32F407/Drivers/Drv_Uart.c`

目标状态：
- UART2 RX（PD6）进入 0xF5 专用解析器，避免和 UART5/IMU 共享 `ANO_DT_LX_Data_Receive_Prepare()` 的 static 状态机。
- 每收到一帧合法 0xF5，立即从 UART2 TX（PD5）发 `0xA0` 字符串 ACK。
- 当前仍不接 PID、不写 0x41、不改变飞行输出。
