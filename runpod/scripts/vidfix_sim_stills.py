"""Replay media.stills_to_chains' decisions on the Hoover timeline (real eligibility + relevance guard, the three
passes: forward chains, backward chains, spares for stills still next to a still), with assumed success rates for
the network steps; reports clip share and still runs before/after."""
import json
import os
import random
import statistics
import sys
from unittest import mock

sys.path.insert(0, r"C:\ThumGenius-vidfix\runpod")
os.environ["SKIP_DOTENV"] = "1"
from src import config, media  # noqa: E402

HERE = os.environ.get("VIDFIX_DIR", r"C:\Users\karna\AppData\Local\Temp\claude\C--ThumGenius\fb8006a8-4f91-444b-ac5f-2627f24f9164\scratchpad\vidfix")
r = json.load(open(os.path.join(HERE, 'hoover_full.json'), encoding='utf-8'))
sc = r['scenes']
fps = 60
rows = json.load(open(os.path.join(HERE, 'rows.json')))
jobs = []
for i, s in enumerate(sc):
    sm = s['semanticMetadata']
    jobs.append({"index": i, "seconds": s['durationInFrames'] / fps, "visual_type": s.get('visualType') or 'footage',
                 "subject_type": sm.get('subjectType') or '', "subject": sm.get('subject') or '',
                 "scene_intent": sm.get('sceneIntent') or {}})
MAX_RUN = 3


def stats(kinds):
    tot = sum(x['d'] for x in rows)
    share = sum(rows[i]['d'] for i in range(len(rows)) if kinds[i] == 'video') / tot
    longest, cur, runs2, lt, ct = 0, 0, 0, 0.0, 0.0
    for i in range(len(rows) + 1):
        if i < len(rows) and kinds[i] == 'image':
            cur += 1
            ct += rows[i]['d']
            longest, lt = max(longest, cur), max(lt, ct)
        else:
            runs2 += cur >= 2
            cur, ct = 0, 0.0
    return share, longest, lt, runs2


def run(p_cont, p_spare, seed):
    random.seed(seed)
    kinds = [x['mt'] for x in rows]
    vid = [sc[i]['semanticMetadata'].get('assetId') if kinds[i] == 'video' else None for i in range(len(rows))]
    vid = [v.split('@')[0] if v else v for v in vid]
    with mock.patch.multiple(config, CLIPS_FIRST=True, CLIPS_FIRST_STILLS=True, PREFER_GENERATED_IMAGES=False), \
            mock.patch.object(media, "youtube_only", lambda: False):
        elig = [i for i in range(len(rows)) if kinds[i] == 'image' and not rows[i]['ai']
                and media.still_may_be_clip(jobs[i], media.MediaAsset(kind="image", source=rows[i]['src'] or '', url="x"))]
    runs = []
    for i in elig:
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    def rel(a, b):
        return bool(media._story_words(jobs[a]) & media._story_words(jobs[b]))

    def yt(j):
        return 0 <= j < len(rows) and kinds[j] == 'video' and str(vid[j]).startswith('yt:')

    def runlen(j, step):
        n, v = 0, vid[j]
        while 0 <= j < len(rows) and kinds[j] == 'video' and vid[j] == v:
            n += 1
            j += step
        return n
    for rn in runs:
        for i in rn:
            if not (yt(i - 1) and runlen(i - 1, -1) < MAX_RUN and rel(i, i - 1)) or random.random() >= p_cont:
                break
            kinds[i], vid[i] = 'video', vid[i - 1]
        for i in reversed(rn):
            if kinds[i] == 'video':
                break
            if not (yt(i + 1) and runlen(i + 1, 1) < MAX_RUN and rel(i, i + 1)) or random.random() >= p_cont:
                break
            kinds[i], vid[i] = 'video', vid[i + 1]
        for i in rn:
            if kinds[i] != 'image':
                continue
            if not any(0 <= j < len(rows) and kinds[j] == 'image' for j in (i - 1, i + 1)):
                continue
            # another moment of a related clip >= 120 s away on the timeline, its video under 4 scenes
            donors = sorted((j for j in range(len(rows)) if yt(j) and rel(i, j)), key=lambda j: abs(j - i))[:3]
            done = False
            for j in donors:
                v = vid[j]
                placed = [k for k in range(len(rows)) if kinds[k] == 'video' and vid[k] == v]
                if len(placed) >= 4 or any(abs(rows[k]['t'] - rows[i]['t']) < 120 for k in placed):
                    continue
                if random.random() < p_cont * 0.8:
                    kinds[i], vid[i] = 'video', v
                    done = True
                break
            if not done and random.random() < p_spare:
                kinds[i], vid[i] = 'video', f'spare{i}'
    return stats(kinds) + (len(elig),)


before = stats([x['mt'] for x in rows])
print(f"before: clip share {100 * before[0]:.1f}%  longest still run {before[1]} stills / {before[2]:.1f} s  "
      f"runs of 2+ {before[3]}")
for pc, ps in ((0.6, 0.2), (0.7, 0.3), (0.8, 0.35)):
    res = [run(pc, ps, s) for s in range(300)]
    print(f"after (continuation {pc:.0%}, spare {ps:.0%}): clip share {100 * statistics.mean(x[0] for x in res):.1f}%  "
          f"longest still run {statistics.mean(x[1] for x in res):.1f} stills / {statistics.mean(x[2] for x in res):.1f} s  "
          f"runs of 2+ {statistics.mean(x[3] for x in res):.1f}  (replaceable stills {res[0][4]})")

if "--why" in sys.argv:
    import types
    random.seed(0)
    kinds = [x['mt'] for x in rows]
    res = run(1.0, 0.0, 0)
    print("structural (every continuation works, no spares):", res)
