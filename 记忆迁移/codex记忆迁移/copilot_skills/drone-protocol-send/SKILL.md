---
name: drone-protocol-send
description: '生成凌霄匿名通信协议发送函数代码。使用场景：需要向凌霄IMU发送CMD指令、向IMU上报传感器数据（0x32/0x33/0x34/0x30）、手动构建任意协议帧时。关键词：发送协议帧、生成发送函数、CMD发送、传感器上报、SC/AC校验、build frame、send frame。告知帧ID和数据字段即可生成完整C代码。'
argument-hint: '帧ID（如0x34）和要发送的数据字段描述'
---

# 生成协议帧发送函数

## 适用场景
- 向 IMU 发送 `0xE0` CMD 命令
- 上报传感器数据（0x30/0x32/0x33/0x34）
- 构建自定义协议帧并计算 SC/AC

## 步骤

### 1. 确认帧参数
- **帧ID**：如 `0x34`、`0xE0`、`0x32`
- **目标地址**：`0xFF`（广播/发CMD用）、`0x60`（读写IMU参数）、`0xAF`（回CK给上位机）
- **DATA字段**：每个字段的名称、C类型、含义、单位

### 2. 参照协议规范
加载 `.github/instructions/lingxiao-protocol.instructions.md`，确认字段定义和注意事项。

### 3. 生成数据结构体（如需要）
```c
typedef struct {
    /* 按协议小端序排列字段 */
    类型 字段名;
    ...
} __attribute__((__packed__)) _帧名_send_st;
```

### 4. 生成发送函数
按 [发送函数模板](./assets/send_template.c) 生成：
- 手动填充 buf[] 各字节（小端序，低字节在前）
- 用 `for (i=0; i < buf[3]+4; i++) { SC += buf[i]; AC += SC; }` 计算校验
- 调用 `Drv_Uart_Send()` 发送

### 5. CMD帧（0xE0）特殊检查
- 确认 `dt.wait_ck == 0` 后才能发送
- LEN 固定为 **11**（CID + CMD[0]~CMD[9]）
- 确认 CID 和 CMD0/CMD1 值与 `LX_FC_Fun.c` 源码一致
- 发送后 `dt.wait_ck` 会自动置非0，等待CK返回
