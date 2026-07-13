# -*- coding: utf-8 -*-
import json, pathlib
DATA = pathlib.Path('gui/data')
fn = 'x移动_20260527_110221.jsonl'
rows = [json.loads(l) for l in (DATA/fn).open(encoding='utf-8') if '_meta' not in l]
att = [r for r in rows if r['cmd'] in ('0x03','0x04')]

for cmd in ('0x03','0x04'):
    sub = [r for r in att if r['cmd']==cmd]
    yaws = [round(r['fields']['yaw_deg'],1) for r in sub[:10]]
    print(cmd + ' yaw前10帧: ' + str(yaws))

print()
cmds = [r['cmd'] for r in att[:30]]
print('前30帧cmd顺序: ' + str(cmds))
