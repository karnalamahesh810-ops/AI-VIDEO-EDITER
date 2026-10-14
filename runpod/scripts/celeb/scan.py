# per-frame colour masks over a reference: yellow (pops vs captions), red (arrows/marks), white flash
import subprocess, sys, json, numpy as np
path, out = sys.argv[1], sys.argv[2]
W, H, FPS = 320, 180, 6
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-vf", f"fps={FPS},scale={W}:{H}", "-f", "rawvideo",
                      "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
rows = []
n = 0
while True:
    b = p.stdout.read(W * H * 3)
    if len(b) < W * H * 3: break
    f = np.frombuffer(b, np.uint8).reshape(H, W, 3).astype(np.int16)
    r, g, bl = f[..., 0], f[..., 1], f[..., 2]
    yellow = (r > 200) & (g > 170) & (bl < 90) & (r - bl > 140)
    red = (r > 170) & (g < 70) & (bl < 70)
    green = (g > 180) & (r < 140) & (bl < 120)
    white = (f.min(axis=2) > 235).mean()
    cap = yellow[int(H * .85):, int(W * .2):int(W * .8)].sum()
    top = yellow[:int(H * .82), :].sum()
    rows.append([round(n / FPS, 2), int(cap), int(top), int(red[:int(H*.85)].sum()), int(green.sum()), round(float(white), 3)])
    n += 1
json.dump(rows, open(out, "w"))
print(path, n)
