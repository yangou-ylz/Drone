# -*- coding: utf-8 -*-
import json, struct, pathlib

DATA = pathlib.Path(__file__).parent

FILES = {
    "x移动": "x移动_20260527_110221.jsonl",
    "y移动": "y移动_20260527_105859.jsonl",
    "z移动": "z移动_20260527_110412.jsonl",
    "静止":  "静止_20260527_105513.jsonl",
}

def check_file(fn, label):
    print(f"\n=== {label} ===")
    rows = [json.loads(l) for l in (DATA / fn).open(encoding="utf-8") if "_meta" not in l]

    # 0x07 速度
    r07 = [r for r in rows if r["cmd"] == "0x07"]
    vxs = [r["fields"].get("vx_cmps", 0) for r in r07]
    vys = [r["fields"].get("vy_cmps", 0) for r in r07]
    vzs = [r["fields"].get("vz_cmps", 0) for r in r07]
    nonzero = [(r["t_mono"], r["fields"], r["hex"]) for r in r07
               if r["fields"].get("vx_cmps", 0) != 0 or r["fields"].get("vy_cmps", 0) != 0]
    print(f"  0x07帧={len(r07)}, 非零速度帧={len(nonzero)}")
    print(f"  vx范围:[{min(vxs)}, {max(vxs)}]  vy:[{min(vys)}, {max(vys)}]  vz:[{min(vzs)}, {max(vzs)}]")
    if nonzero:
        t, f, h = nonzero[0]
        print(f"  首个非零: t={t:.2f}  {f}")
    else:
        mid = r07[len(r07) // 2]
        raw = bytes.fromhex(mid["hex"])
        print(f"  中间帧 hex={mid['hex']}  raw={list(raw)}")
        if len(raw) >= 6:
            vx, vy, vz = struct.unpack("<hhh", raw[:6])
            print(f"  手动解析<hhh> vx={vx} vy={vy} vz={vz}")
        # 也试试 s16/100 格式
        if len(raw) >= 8:
            a, b, c, d = struct.unpack("<hhhh", raw[:8])
            print(f"  手动解析<hhhh> a={a} b={b} c={c} d={d}")

    # 0x08 XY位置
    r08 = [r for r in rows if r["cmd"] == "0x08"]
    xs = [r["fields"].get("pos_x_cm", 0) for r in r08]
    ys = [r["fields"].get("pos_y_cm", 0) for r in r08]
    print(f"  0x08帧={len(r08)}, x:[{min(xs)}, {max(xs)}]  y:[{min(ys)}, {max(ys)}]")
    if r08:
        mid = r08[len(r08) // 2]
        raw = bytes.fromhex(mid["hex"])
        print(f"  0x08中间帧 hex={mid['hex']}")
        if len(raw) >= 8:
            x, y = struct.unpack("<ii", raw[:8])
            print(f"  手动解析<ii> x={x} y={y}")
        if len(raw) >= 4:
            x2, y2 = struct.unpack("<hh", raw[:4])
            print(f"  手动解析<hh> x2={x2} y2={y2}")

    # 0x05 高度
    r05 = [r for r in rows if r["cmd"] == "0x05"]
    if r05:
        mid = r05[len(r05) // 2]
        print(f"  0x05中间帧 hex={mid['hex']}  fields={mid['fields']}")

for label, fn in FILES.items():
    check_file(fn, label)
