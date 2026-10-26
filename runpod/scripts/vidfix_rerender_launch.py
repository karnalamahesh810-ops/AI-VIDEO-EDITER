"""
Launch / check / delete the before-after re-render pod for the Hoover Dam fixes (needs RunPod credit; ~$0.15).
Never prints a key.

  python rerender_launch.py start     # uploads the saved timeline to R2 tmp/, starts a 16-vCPU cpu3c pod
  python rerender_launch.py status
  python rerender_launch.py results   # index.json, log.txt, the sheet and the mp4s -> C:\\ThumGenius\\docs\\vidfix-2026-10-26\\pod\\
  python rerender_launch.py delete    # ALWAYS run when done (the pod keeps serving until deleted)

The pod: the LIVE worker image (8b570fd), no template, no secrets in its env; it renders BEFORE with the image's
own renderer, patches this branch's files from GitHub at BRANCH_SHA, re-applies the passes and renders AFTER
(runpod/scripts/vidfix_rerender_pod.py).
"""
import json
import os
import subprocess
import sys

import boto3
import requests

HERE = os.environ.get("VIDFIX_DIR", r"C:\Users\karna\AppData\Local\Temp\claude\C--ThumGenius\fb8006a8-4f91-444b-ac5f-2627f24f9164\scratchpad\vidfix")
TOOLS = r"C:\Users\karna\AppData\Local\Temp\claude\C--ThumGenius\7bdcd241-daa1-45bb-abcc-fca27af8754a\scratchpad"
sys.path.insert(0, TOOLS)
from rp import KEY  # noqa: E402

ID_FILE = os.path.join(HERE, "rerender_pod_id.txt")
H = {"Authorization": f"Bearer {KEY}"}
REPO_DIR = r"C:\ThumGenius-vidfix"
DOC_KEY = "tmp/vidfix-2026-10-26/hoover_doc.json"
OUT = r"C:\ThumGenius\docs\vidfix-2026-10-26\pod"


def live_image() -> str:
    from rp import gql, q
    t = next(x for x in gql(q)["myself"]["podTemplates"] if x["id"] == "rksecohuvp")
    return t["imageName"]                          # read only: the live CPU pod template's image


def branch():
    sha = subprocess.run(["git", "-C", REPO_DIR, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    files = subprocess.run(["git", "-C", REPO_DIR, "diff", "--name-only", "origin/thumbgenius-video-worker", sha,
                            "--", "runpod"], capture_output=True, text=True).stdout.split()
    files = [f[len("runpod/"):] for f in files
             if not f.startswith(("runpod/tests/", "runpod/docs/")) and f.endswith((".py", ".tsx", ".ts", ".json"))]
    return sha, files


cmd = sys.argv[1]
if cmd == "start":
    S = json.load(open(os.path.join(TOOLS, "cf_secret.json")))
    s3 = boto3.client("s3", endpoint_url=S["endpoint"], aws_access_key_id=S["access_key_id"],
                      aws_secret_access_key=S["secret_access_key"], region_name="auto")
    doc = json.load(open(os.path.join(HERE, "hoover_full.json"), encoding="utf-8"))
    doc["top"].pop("audio", None)                  # the narration's signed link stays private
    slim = {"top": doc["top"], "scenes": doc["scenes"], "meta": {}}
    tmp = os.path.join(HERE, "hoover_doc_upload.json")
    json.dump(slim, open(tmp, "w", encoding="utf-8"))
    s3.upload_file(tmp, "thumbgenius-videos", DOC_KEY, ExtraArgs={"ContentType": "application/json"})
    sha, files = branch()
    print("branch", sha[:10], len(files), "files")
    script = f"https://raw.githubusercontent.com/karnalamahesh810-ops/ai-video-editer/{sha}/runpod/scripts/vidfix_rerender_pod.py"
    env = {"DOC_URL": f"{S['public_base'].rstrip('/')}/{DOC_KEY}", "BRANCH_SHA": sha, "BRANCH_FILES": ",".join(files)}
    body = {"name": "vidfix-rerender", "computeType": "CPU", "cloudType": "SECURE",
            "cpuFlavorIds": ["cpu3c"], "cpuFlavorPriority": "custom", "vcpuCount": 16,
            "containerDiskInGb": 30, "volumeInGb": 0, "imageName": live_image(),
            "dockerStartCmd": ["sh", "-c", f"cd /app && curl -sL {script} -o /tmp/rr.py && python -u /tmp/rr.py"],
            "ports": ["8888/http"], "env": env}
    r = requests.post("https://rest.runpod.io/v1/pods", headers=H, json=body, timeout=60)
    d = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text[:300]}
    if r.status_code >= 300:
        print("create failed", r.status_code, json.dumps(d)[:400])
        sys.exit(1)
    open(ID_FILE, "w").write(d["id"])
    print("POD", d["id"], d.get("costPerHr"), d.get("vcpuCount"))
elif cmd == "status":
    pid = open(ID_FILE).read().strip()
    d = requests.get(f"https://rest.runpod.io/v1/pods/{pid}", headers=H, timeout=60).json()
    print({k: d.get(k) for k in ("id", "desiredStatus", "costPerHr", "lastStartedAt")})
    r = requests.get(f"https://{pid}-8888.proxy.runpod.net/log.txt", timeout=60)
    print(r.status_code, r.text[-2000:])
elif cmd == "results":
    pid = open(ID_FILE).read().strip()
    os.makedirs(OUT, exist_ok=True)
    base = f"https://{pid}-8888.proxy.runpod.net/"
    idx = requests.get(base + "index.json", timeout=60).json()
    names = ["index.json", "log.txt", idx.get("sheet") or ""] + [w[k] for w in idx.get("windows", [])
                                                                 for k in ("before", "after")]
    for n in [n for n in names if n]:
        r = requests.get(base + n, timeout=300)
        open(os.path.join(OUT, n), "wb").write(r.content)
        print(n, r.status_code, len(r.content))
elif cmd == "delete":
    pid = open(ID_FILE).read().strip()
    r = requests.delete(f"https://rest.runpod.io/v1/pods/{pid}", headers=H, timeout=60)
    print("delete", r.status_code, r.text[:200])
