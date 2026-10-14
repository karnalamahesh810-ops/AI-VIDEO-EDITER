import json, sys
def runs(rows, key, thr, minlen=2, gap=2):
    out, cur, miss = [], None, 0
    for r in rows:
        on = key(r) > thr
        if on:
            if cur is None: cur = [r[0], r[0], key(r)]
            cur[1] = r[0]; cur[2] = max(cur[2], key(r)); miss = 0
        elif cur is not None:
            miss += 1
            if miss > gap:
                if (cur[1]-cur[0])*6+1 >= minlen: out.append(cur)
                cur = None; miss = 0
    if cur: out.append(cur)
    return out
for vid in sys.argv[1:]:
    rows = json.load(open(f"{__import__('os').path.dirname(__file__)}/scan_{vid}.json"))
    pops = runs(rows, lambda r: r[2], 120)
    red = runs(rows, lambda r: r[3], 150)
    fl = runs(rows, lambda r: r[5], 0.9, 1, 0)
    capfrac = sum(1 for r in rows if r[1] > 40) / len(rows)
    green = sum(1 for r in rows if r[4] > 300) / len(rows)
    print(f"== {vid} dur {rows[-1][0]:.0f}s captions-on {capfrac:.0%} green {green:.0%}")
    print(" pops", len(pops), [f"{a:.1f}-{b:.1f}" for a,b,_ in pops])
    print(" red ", len(red), [f"{a:.1f}-{b:.1f}" for a,b,_ in red])
    print(" flash", len(fl), [f"{a:.1f}" for a,b,_ in fl])
