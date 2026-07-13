# -*- coding: utf-8 -*-
"""检查 0x08 位置帧是否有数据；多文件统计 + 时序"""
import json, os, glob

files = sorted(glob.glob(os.path.join(os.path.dirname(__file__), '*.jsonl')))
for f in files:
    cnt = {}
    pos08 = []
    pos03_yaw = []
    with open(f, 'r', encoding='utf-8') as fp:
        for line in fp:
            line = line.strip()
            if not line: continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if '_meta' in d: continue
            c = d.get('cmd', '?')
            cnt[c] = cnt.get(c, 0) + 1
            fields = d.get('fields', {})
            if c == '0x08':
                pos08.append((d.get('t_mono'), fields))
            if c == '0x03':
                pos03_yaw.append((d.get('t_mono'), fields.get('yaw_deg')))
    name = os.path.basename(f)
    print(f'=== {name} ===')
    print('  cmd统计:', cnt)
    if pos08:
        print(f'  0x08 帧数={len(pos08)}; 首条 fields={pos08[0][1]}; 末条 fields={pos08[-1][1]}')
    else:
        print('  0x08 无数据')
    if pos03_yaw:
        yaws = [y for _, y in pos03_yaw if y is not None]
        if yaws:
            print(f'  0x03 yaw n={len(yaws)} 首={yaws[0]:.2f} 末={yaws[-1]:.2f} 极差={max(yaws)-min(yaws):.2f}')
