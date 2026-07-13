# -*- coding: utf-8 -*-
"""向左测试：看主动段时 yaw_rate 是否超 5°/s 把横移误冻结"""
import json, os, math
f = os.path.join(os.path.dirname(__file__), '向左20260527_123311.jsonl')
ys, vs = [], []
with open(f, 'r', encoding='utf-8') as fp:
    for line in fp:
        line = line.strip()
        if not line: continue
        try: d = json.loads(line)
        except: continue
        if '_meta' in d: continue
        c = d.get('cmd')
        if c == '0x03':
            t = d.get('t_mono'); y = d.get('fields', {}).get('yaw_deg')
            if y is not None: ys.append((t, y))
        elif c == '0x07':
            t = d.get('t_mono'); f7 = d.get('fields', {})
            vs.append((t, f7.get('vx_cmps', 0), f7.get('vy_cmps', 0)))

# 算 yaw_rate
t0 = ys[0][0]
rates = []
for i in range(1, len(ys)):
    dt = ys[i][0] - ys[i-1][0]
    if dt <= 0: continue
    dy = ys[i][1] - ys[i-1][1]
    if dy > 180: dy -= 360
    if dy < -180: dy += 360
    rates.append((ys[i][0], dy/dt))

# 用 EMA 模拟我的滤波
ema = 0.0
ema_series = []
for t, r in rates:
    ema = 0.3 * ema + 0.7 * r
    ema_series.append((t, ema))

# 关键：看横移主动段（|vy|>5 cm/s 的时间窗）yaw_rate EMA 是否被错冻结
print('|vy|>5 cm/s 横移段时 yaw_rate EMA 分布：')
v_by_t = {round(t, 3): (vx, vy) for t, vx, vy in vs}
gated_count = 0
total_count = 0
for t, e in ema_series:
    # 找最近 0.05s 内的 v 样本
    near = [v for tt, v in [(tt, v_by_t.get(round(tt,3))) for tt in [t-0.01, t, t+0.01]] if v]
    if not near: continue
    vy = near[0][1]
    if abs(vy) > 5:
        total_count += 1
        if abs(e) > 5:
            gated_count += 1
        if gated_count <= 5 or total_count % 5 == 0:
            print(f'  t={t-t0:5.2f}s vy={vy:+.0f} yaw_rate_ema={e:+.2f}°/s {"门控冻结!" if abs(e)>5 else ""}')

print(f'\n横移段 yaw_rate>5 门控冻结比例: {gated_count}/{total_count}')

# 看尾段（飞机静止）yaw_rate 的分布
print(f'\n后 3 秒 yaw_rate EMA 分布:')
last = ema_series[-1][0]
tail = [e for t, e in ema_series if t > last - 3.0]
print(f'  样本 n={len(tail)}, mean={sum(tail)/len(tail):+.2f}°/s, max|e|={max(abs(e) for e in tail):.2f}°/s')
