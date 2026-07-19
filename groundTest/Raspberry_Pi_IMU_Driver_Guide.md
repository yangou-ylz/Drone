x= 12:
            return {
                'mag_x': _s16(p, 0), 'mag_y': _s16(p, 2), 'mag_z': _s16(p, 4),
                'baro_alt_cm': _s32(p, 6),
                'temp_c': _s16(p, 10) * 0.1,
            }
        # ── 0x03 欧拉角（低频，仅供参考） ─────────────────────────
        elif cmd == 0x03 and n >= 7:
            return {
                'roll_deg':  _s16(p, 0) * 0.01,
                'pitch_deg': _s16(p, 2) * 0.01,
                'yaw_deg':   _s16(p, 4) * 0.01,
                'fusion_sta': p[6],
            }
        # ── 0x04 四元数（推荐！67 Hz） ───────────────────────────
        elif cmd == 0x04 and n >= 9:
            w = _s16(p, 0) * 0.0001
            x = _s16(p, 2) * 0.0001
            y = _s16(p, 4) * 0.0001
            z = _s16(p, 6) * 0.0001
            # 在此直接算欧拉角，减少外部调用。
            # 以凌霄 0x03 欧拉角为基准：四元数常规公式转出的 pitch/yaw 需翻号。
            roll  = math.degrees(math.atan2(2*(w*x+y*z), 1-2*(x*x+y*y)))
            sinp  = max(-1.0, min(1.0, 2*(w*y-z*x)))
            pitch = -math.degrees(math.asin(sinp))
            yaw   = -math.degrees(math.atan2(2*(w*z+x*y), 1-2*(y*y+z*z)))
            return {
                'w': w, 'x': x, 'y': y, 'z': z,
                'roll_deg': roll, 'pitch_deg': pitch, 'yaw_deg': yaw,
                'fusion_sta': p[8],
            }
        # ── 0x05 融合高度 ────────────────────────────────────────
        elif cmd == 0x05 and n >= 9:
            return {
                'alt_fused_cm': _s32(p, 0),
                'alt_add_cm':   _s32(p, 4),
                'sta': p[8],
            }
        # ── 0x06 飞控状态 ────────────────────────────────────────
        elif cmd == 0x06 and n >= 5:
            mode_map = {0: 'attitude', 1: 'alt_hold', 2: 'pos_hold', 3: 'mission'}
            return {
                'mode':     p[0],
                'mode_str': mode_map.get(p[0], f'unknown({p[0]})'),
                'unlocked': bool(p[1]),
                'cmd_cid':  p[2],
                'cmd_0':    p[3],
                'cmd_1':    p[4],
            }
        # ── 0x07 飞行速度 ────────────────────────────────────────
        elif cmd == 0x07 and n >= 6:
            return {
                'vel_x_cms': _s16(p, 0),
                'vel_y_cms': _s16(p, 2),
                'vel_z_cms': _s16(p, 4),
            }
        # ── 0x08 XY位移 ──────────────────────────────────────────
        elif cmd == 0x08 and n >= 8:
            return {
                'pos_x_cm': _s32(p, 0),
                'pos_y_cm': _s32(p, 4),
            }
        # ── 0x09 风速 ────────────────────────────────────────────
        elif cmd == 0x09 and n >= 4:
            return {
                'wind_x_cms': _s16(p, 0),
                'wind_y_cms': _s16(p, 2),
            }
        # ── 0x0D 电池 ────────────────────────────────────────────
        elif cmd == 0x0D and n >= 4:
            return {
                'voltage_v':  _u16(p, 0) * 0.01,
                'current_a':  _u16(p, 2) * 0.01,
            }
        # ── 0x0E 外接模块状态 ────────────────────────────────────
        elif cmd == 0x0E and n >= 4:
            sta_str = {0: 'no_data', 1: 'unavail', 2: 'ok', 3: 'good'}
            return {
                'sta_gvel': sta_str.get(p[0], '?'),
                'sta_gpos': sta_str.get(p[1], '?'),
                'sta_gps':  sta_str.get(p[2], '?'),
                'sta_alt':  sta_str.get(p[3], '?'),
            }
        # ── 0x20 电机PWM ─────────────────────────────────────────
        elif cmd == 0x20 and n >= 2:
            n_motors = n // 2
            return {f'M{i+1}': _u16(p, i*2) for i in range(n_motors)}
        # ── 0x40 遥控器 ──────────────────────────────────────────
        elif cmd == 0x40 and n >= 20:
            names = ['roll','pitch','throttle','yaw',
                     'aux1','aux2','aux3','aux4','aux5','aux6']
            return {names[i]: _s16(p, i*2) for i in range(10)}
        # ── 0x41 实时控制 ────────────────────────────────────────
        elif cmd == 0x41 and n >= 14:
            return {
                'roll_deg':  _s16(p, 0) * 0.01,
                'pitch_deg': _s16(p, 2) * 0.01,
                'thr_pct':   _s16(p, 4) * 0.1,
                'yaw_rate':  _s16(p, 6),
                'vel_x_cms': _s16(p, 8),
                'vel_y_cms': _s16(p, 10),
                'vel_z_cms': _s16(p, 12),
            }
        # ── 0xA0 日志字符串 ──────────────────────────────────────
        elif cmd == 0xA0 and n >= 1:
            color = {0: 'black', 1: 'red', 2: 'green'}.get(p[0], '?')
            return {
                'color': color,
                'text':  p[1:].decode('utf-8', errors='replace').rstrip('\x00'),
            }
        # ── 0x00 CK 应答 ─────────────────────────────────────────
        elif cmd == 0x00 and n >= 3:
            return {'for_cmd': p[0], 'sc': p[1], 'ac': p[2]}
        # ── 0xE0 CMD ─────────────────────────────────────────────
        elif cmd == 0xE0 and n >= 3:
            return {'cid': p[0], 'cmd_0': p[1], 'cmd_1': p[2]}

    except Exception as e:
        return {'error': str(e), 'raw': p.hex()}

    # 未知帧 / 长度不足
    return {'raw': p.hex()}


class AnoProtocol:
    """
    凌霄匿名协议驱动类。
    
    用法：
        proto = AnoProtocol('/dev/ttyAMA0', 500000)
        proto.start()
        
        while True:
            f = proto.get_frame(0x04)          # 阻塞直到拿到四元数帧
            print(f['roll_deg'], f['pitch_deg'], f['yaw_deg'])
        
        proto.stop()
    """

    def __init__(self, port: str, baudrate: int = 500000):
        self._ser     = serial.Serial(port, baudrate, timeout=0.02)
        self._buf     = bytearray()
        self._lock    = threading.Lock()
        self._frames  = {}          # {cmd: (decoded_dict, raw_bytes, timestamp)}
        self._callbacks = defaultdict(list)  # {cmd: [callable, ...]}
        self._running = False
        self._thread  = None
        self._stats   = defaultdict(int)     # {cmd: count}
        self._err_cnt = 0

    # ── 控制 ────────────────────────────────────────────────────

    def start(self):
        """启动后台接收解析线程"""
        self._running = True
        self._thread  = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止接收线程，关闭串口"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._ser.close()

    # ── 数据获取 ─────────────────────────────────────────────────

    def get_frame(self, cmd: int, timeout: float = None) -> dict | None:
        """
        获取指定 CMD 帧的最新解码数据。
        timeout=None → 立即返回（可能为 None）
        timeout=0.1  → 最多等 0.1 秒，还没数据返回 None
        """
        deadline = time.monotonic() + timeout if timeout else None
        while True:
            with self._lock:
                entry = self._frames.get(cmd)
            if entry:
                return entry[0]   # decoded dict
            if deadline is None or time.monotonic() >= deadline:
                return None
            time.sleep(0.002)

    def get_frame_raw(self, cmd: int) -> bytes | None:
        """返回最新一帧的原始字节（含帧头和校验），用于转发"""
        with self._lock:
            entry = self._frames.get(cmd)
        return entry[1] if entry else None

    def get_frame_age(self, cmd: int) -> float | None:
        """返回该帧距今多少秒，None 表示从未收到"""
        with self._lock:
            entry = self._frames.get(cmd)
        return time.monotonic() - entry[2] if entry else None

    def wait_frame(self, cmd: int, timeout: float = 2.0) -> dict | None:
        """阻塞等待，直到收到指定帧或超时"""
        return self.get_frame(cmd, timeout=timeout)

    def stats(self) -> dict:
        """返回各帧接收计数统计"""
        with self._lock:
            return dict(self._stats), self._err_cnt

    # ── 回调注册 ─────────────────────────────────────────────────

    def register_callback(self, cmd: int, fn):
        """
        注册帧回调。每次收到 cmd 帧时，自动调用 fn(decoded_dict)。
        注意：回调在接收线程中执行，避免阻塞操作。
        """
        self._callbacks[cmd].append(fn)

    # ── 发送 ─────────────────────────────────────────────────────

    def send(self, dest: int, cmd: int, data: bytes = b'') -> None:
        """发送任意帧"""
        frame = build_frame(dest, cmd, data)
        self._ser.write(frame)

    def send_cmd(self, cid: int, cmd_0: int, cmd_1: int = 0) -> None:
        """发送 0xE0 CMD 帧（目标地址 0xFF 广播）"""
        self.send(0xFF, 0xE0, bytes([cid, cmd_0, cmd_1]))

    def send_ctrl(self, roll_deg: float, pitch_deg: float,
                  thr_pct: float, yaw_rate: int,
                  vel_x: int = 0, vel_y: int = 0, vel_z: int = 0) -> None:
        """
        发送 0x41 实时控制帧（需飞控处于程控模式 mode=3）。
        roll/pitch 单位: 度   thr_pct: 0~100   yaw_rate: 度/秒   vel: cm/s
        """
        data = struct.pack('<7h',
                           int(roll_deg * 100),
                           int(pitch_deg * 100),
                           int(thr_pct * 10),
                           int(yaw_rate),
                           int(vel_x), int(vel_y), int(vel_z))
        self.send(0xFF, 0x41, data)

    # ── 内部接收循环 ─────────────────────────────────────────────

    def _recv_loop(self):
        while self._running:
            try:
                chunk = self._ser.read(512)
                if chunk:
                    self._buf.extend(chunk)
                self._parse_buf()
            except Exception:
                pass

    def _parse_buf(self):
        buf = self._buf
        while len(buf) >= 6:
            idx = buf.find(0xAA)
            if idx == -1:
                self._buf = bytearray()
                return
            if idx > 0:
                buf = buf[idx:]
            if len(buf) < 4:
                break

            ln   = buf[3]
            need = ln + 6
            if len(buf) < need:
                break

            frame = buf[:need]
            buf   = buf[need:]

            if verify_frame(frame):
                cmd     = frame[2]
                payload = bytes(frame[4:4 + ln])
                decoded = decode_frame(cmd, payload)
                ts      = time.monotonic()
                with self._lock:
                    self._frames[cmd] = (decoded, bytes(frame), ts)
                    self._stats[cmd] += 1
                # 触发回调
                for fn in self._callbacks.get(cmd, []):
                    try:
                        fn(decoded)
                    except Exception:
                        pass
            else:
                self._err_cnt += 1
                buf = buf[1:]   # 跳一字节重新同步

        self._buf = buf
```

---

## 7. 使用示例

### 7.1 基础：读取姿态和速度

```python
from ano_protocol import AnoProtocol
import time

proto = AnoProtocol('/dev/ttyAMA0', 500000)
# USB串口: AnoProtocol('/dev/ttyUSB0', 500000)
proto.start()

print("等待 IMU 数据...")
time.sleep(0.5)

while True:
    # 四元数帧（67 Hz，延迟最低）
    att = proto.get_frame(0x04, timeout=0.05)
    vel = proto.get_frame(0x07, timeout=0.05)
    alt = proto.get_frame(0x05, timeout=0.05)
    bat = proto.get_frame(0x0D)   # 低频，不等待

    if att:
        print(f"Roll={att['roll_deg']:+7.2f}°  "
              f"Pitch={att['pitch_deg']:+7.2f}°  "
              f"Yaw={att['yaw_deg']:+7.2f}°")
    if vel:
        print(f"Vx={vel['vel_x_cms']:+5d}  Vy={vel['vel_y_cms']:+5d}  "
              f"Vz={vel['vel_z_cms']:+5d} cm/s")
    if alt:
        print(f"Alt={alt['alt_fused_cm']} cm")
    if bat:
        print(f"Battery: {bat['voltage_v']:.2f}V  {bat['current_a']:.2f}A")
    
    time.sleep(0.05)   # 20Hz 读取循环
```

### 7.2 回调模式（最低延迟，推荐用于控制）

```python
from ano_protocol import AnoProtocol

proto = AnoProtocol('/dev/ttyAMA0', 500000)

latest_att = {}
latest_vel = {}

def on_attitude(d):
    latest_att.update(d)
    # 在这里直接做控制计算，每帧触发（67 Hz）
    roll  = d['roll_deg']
    pitch = d['pitch_deg']
    yaw   = d['yaw_deg']
    # your_control_loop(roll, pitch, yaw)

def on_velocity(d):
    latest_vel.update(d)

proto.register_callback(0x04, on_attitude)
proto.register_callback(0x07, on_velocity)
proto.start()

import time
while True:
    time.sleep(1)   # 主线程做其他事，回调自动在后台触发
```

### 7.3 查询电量

```python
import time
bat = proto.get_frame(0x0D, timeout=3.0)   # 电池帧约1秒一次，等3秒保证拿到
if bat:
    print(f"电压: {bat['voltage_v']:.2f} V")
    if bat['voltage_v'] < 10.5:
        print("? 电量低！")
```

### 7.4 获取飞控状态（模式/解锁状态）

```python
sta = proto.get_frame(0x06, timeout=0.1)
if sta:
    print(f"模式: {sta['mode_str']}  解锁: {sta['unlocked']}")
```

### 7.5 发送 CMD 指令

```python
# 一键起飞（CID=0x10, CMD_0=0x03）
proto.send_cmd(0x10, 0x03)

# 一键降落
proto.send_cmd(0x10, 0x04)
```

### 7.6 统计帧率

```python
import time

stats_before, _ = proto.stats()
time.sleep(1.0)
stats_after, _ = proto.stats()

for cmd, cnt in stats_after.items():
    hz = cnt - stats_before.get(cmd, 0)
    from ano_protocol import FRAME_NAME
    print(f"0x{cmd:02X} {FRAME_NAME.get(cmd,'?'):<15s}: {hz} Hz")
```

---

## 8. 发送自定义帧

### 8.1 发送任意帧（通用方法）

```python
import struct

# 例：发送自定义 0x50 帧，DATA = [val1(s16), val2(u32)]
val1 = -100
val2 = 99999
data = struct.pack('<hi', val1, val2)   # 6字节
proto.send(dest=0xFF, cmd=0x50, data=data)
```

### 8.2 手动构造帧（不依赖库）

```python
def build_frame(dest, cmd, data):
    ln  = len(data)
    buf = bytearray([0xAA, dest, cmd, ln]) + bytearray(data)
    sc = ac = 0
    for b in buf:
        sc = (sc + b) & 0xFF
        ac = (ac + sc) & 0xFF
    buf += bytearray([sc, ac])
    return bytes(buf)
```

### 8.3 上报传感器数据（0x32 通用位置，供 IMU 融合）

如果树莓派运行了定位算法（视觉/UWB），可上报给 IMU：

```python
import struct

def send_position(proto, x_cm, y_cm, z_cm, quality=100):
    """上报位置给 IMU（0x32 帧），IMU 会融合进位置估计"""
    data = struct.pack('<iii B', x_cm, y_cm, z_cm, quality)
    proto.send(0x60, 0x32, data)   # 目标是 IMU (0x60)

def send_distance(proto, dist_cm):
    """上报测距（0x34 帧），IMU 用于辅助高度融合"""
    data = struct.pack('<i', dist_cm)
    proto.send(0x60, 0x34, data)
```

---

## 9. 未来扩展指引

### 9.1 增加新帧解析

在 `ano_protocol.py` 的 `decode_frame()` 函数中，在 `elif cmd == 0xE0` 之前
添加新的 `elif cmd == 0xXX` 分支即可：

```python
# 例：解析新增 0x50 帧
elif cmd == 0x50 and n >= 6:
    return {
        'val1': _s16(p, 0),
        'val2': _u32(p, 2),
    }
```

添加后无需其他修改，`proto.get_frame(0x50)` 立即可用。

### 9.2 增加帧名称

在 `FRAME_NAME` 字典中添加一行：

```python
0x50: 'My_Custom_Frame',
```

### 9.3 多帧同时订阅

```python
# 同时订阅姿态、速度、高度、状态、电池
for cmd in [0x04, 0x07, 0x05, 0x06, 0x0D]:
    proto.register_callback(cmd, lambda d, c=cmd: handle(c, d))

def handle(cmd, data):
    print(f"Received 0x{cmd:02X}:", data)
```

### 9.4 数据录制与回放

```python
import json, time

# 录制
records = []
def record(d):
    records.append({'t': time.time(), 'data': d})

proto.register_callback(0x04, record)
proto.start()
time.sleep(30)   # 录制30秒
proto.stop()
with open('attitude_log.json', 'w') as f:
    json.dump(records, f)
```

---

## 附录：快速接线核对清单

```
□ PD2 (STM32 UART5_RX) ── 树莓派 GPIO15 (RXD)     ?
□ GND ─────────────────── 树莓派 GND                ?  
□ 电平 3.3V，无需电平转换                             ?
□ 波特率：500000 bps                                 ?
□ 格式：8N1，无流控                                   ?
□ 禁用树莓派蓝牙串口（/boot/config.txt dtoverlay=disable-bt） ?
□ 优先使用 0x04（四元数，67Hz）而非 0x03（欧拉角，0.67Hz）  ?
```

---

*文档版本：v1.0 | 基于凌霄匿名通信协议 V7 | STM32F407 飞控固件*
