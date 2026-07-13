# -*- coding: utf-8 -*-
"""分析 CW90 末尾 5 秒 yaw 是否仍在变（用户报：cube 停下后继续逆时针转 120°）"""
import json, os
f = os.path.join(os.path.dirname(__file__), '顺时针90°20260527_123356.jsonl')
ys = []
with open(f, 'r', encoding='utf-8') as fp:
    for line in fp:
        line = line.strip()
        if not line: continue
        try: d = json.loads(line)
        except: continue
        if '_meta' in d: continue
        if d.get('cmd') == '0x03':
            t = d.get('t_mono'); y = d.get('fields', {}).get('yaw_deg')
            if y is not None: ys.append((t, y))

# 取整段 33s 每秒抽 1 个点看趋势
t0 = ys[0][0]
print('CW90 yaw 每 2 秒采样:')
bucket = -1
for t, y in ys:
    b = int((t - t0) // 2)
    if b != bucket:
        bucket = b
        print(f'  t={t-t0:5.1f}s  yaw={y:7.2f}°')

# 同时计算每 0.5s 区间的角速度，看运动停下后角速度有没有真正归零
print('\n后 5 秒（应已停旋转）yaw 时序：')
last = ys[-1][0]
for t, y in ys:
    if t > last - 5.0:
        print(f'  t={t-t0:5.2f}s  yaw={y:7.2f}°')
