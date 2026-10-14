# grid.py video out.jpg cols width t1 t2 ... (crop=x,y,w,h in source px via env CROP)
import subprocess, sys, os, io
from PIL import Image, ImageDraw
v, out, cols, w = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
ts = [float(x) for x in sys.argv[5:]]
crop = os.environ.get("CROP")
ims = []
for t in ts:
    vf = (f"crop={crop.replace(',',':')}," if crop else "") + f"scale={w}:-2"
    p = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", v, "-frames:v", "1", "-vf", vf, "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True)
    im = Image.open(io.BytesIO(p.stdout)).convert("RGB")
    ImageDraw.Draw(im).rectangle([0, 0, 58, 16], fill=(0, 0, 0)); ImageDraw.Draw(im).text((3, 3), f"{t:.2f}", fill=(255, 255, 255))
    ims.append(im)
h = ims[0].height
rows = (len(ims) + cols - 1) // cols
g = Image.new("RGB", (cols * w, rows * h))
for i, im in enumerate(ims): g.paste(im, ((i % cols) * w, (i // cols) * h))
g.save(out, quality=88); print(out, g.size)
