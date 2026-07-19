# 20260719-155019-rpi-f5-stage1

备份原因：树莓派 ↔ STM32 正式对接第一阶段，涉及 0xF5 协议解析、对接文档和地面测试资料，属于协议/飞控安全相关修改。

备份范围：
- `FcSrc/Uplink_Cmd.c`
- `FcSrc/Uplink_Cmd.h`
- `FcSrc/ANO_DT_LX.c`
- `树莓派飞控对接文档.md`
- `记忆迁移/codex记忆迁移/project_docs/数据帧.md`
- `groundTest/README.md`

目标状态：先实现 0xF5 接收解析和 0xA0 日志确认，不接入 PID、不改变飞控输出。

验证状态：备份创建于修改前，待本次补丁后离线编译/脚本测试验证。
