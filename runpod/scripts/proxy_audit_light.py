"""
Light YouTube proxy audit: network only, no ffmpeg, no encode (safe on a laptop).

For every proxy in the pool (the template's YTDLP_PROXY list, or a good_proxies.json list), one at a time:
  1. exit IP + country (ipinfo.io through the proxy);
  2. one flat YouTube search (3 results) - search passes even on refused addresses, so it is only a sign of life;
  3. one metadata extraction of a real video (yt-dlp -j, the worker's network args: node JS runtime) - where
     YouTube's "Sign in to confirm you're not a bot" shows (BOT);
  4. one 512 KB range request of the chosen 1080p-or-lower video stream through the same proxy - where a refused
     session shows as googlevideo 403 (STREAM_REFUSED).
A proxy PASSES when 3 and 4 succeed. Credentials are never printed: labels are proxy_NN plus decodo:<port> or
webshare:<ip>. One proxy at a time, one extraction each (YouTube flags bursts of probes from one address).

    python proxy_audit_light.py --pool FILE [--video ID] [--out results.jsonl]
    FILE: a JSON list of proxy URLs, or a text file with one URL per line / comma separated.

Also runs on a pod (same yt-dlp + node): copy this file and the pool file, run it there.
"""
import argparse
import json
import os
import re
import subprocess
import time

import requests

FMT = ("bv*[height<=1080][ext=mp4][protocol^=https]/bv*[height<=1080][ext=mp4]"
       "/bv*[height<=1080]/b[height<=1080]")


def load_pool(path: str) -> list:
    raw = open(path, encoding="utf-8").read().strip()
    try:
        got = json.loads(raw)
        if isinstance(got, list):
            return [str(p) for p in got if str(p).strip()]
    except ValueError:
        pass
    return [p for p in re.split(r"[,\s]+", raw) if p.startswith("http")]


def label(i: int, url: str) -> str:
    host = url.split("@")[-1]
    return f"proxy_{i:02d} " + (f"decodo:{host.split(':')[-1]}" if "decodo" in host else
                                 f"webshare:{host.split(':')[0]}")


def clean(text: str, proxy: str) -> str:
    text = (text or "").replace(proxy, "<proxy>")
    text = re.sub(r"https?://\S+", "<url>", text)
    return re.sub(r"\s+", " ", text)[:200]


def ytdlp(args: list, proxy: str, timeout: int = 90) -> tuple:
    cmd = ["yt-dlp", "--ignore-config", "--js-runtimes", "node", "--socket-timeout", "20",
           "--no-warnings", "--proxy", proxy] + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return p.returncode, p.stdout or "", p.stderr or ""
    except subprocess.TimeoutExpired:
        return -9, "", "timed out"


def verdict_of(stderr: str, rc: int) -> str:
    low = (stderr or "").lower()
    if "not a bot" in low or "sign in to confirm" in low:
        return "BOT"
    if rc == -9:
        return "TIMEOUT"
    if "403" in low:
        return "STREAM_REFUSED"
    if "proxy" in low or "tunnel" in low or "407" in low:
        return "PROXY_FAILURE"
    return "FAIL"


def check(i: int, proxy: str, video: str) -> dict:
    out = {"proxy": label(i, proxy)}
    kw = {"proxies": {"https": proxy, "http": proxy}, "timeout": 20}
    try:
        j = requests.get("https://ipinfo.io/json", **kw).json()
        out["ip"], out["where"] = j.get("ip"), f"{j.get('country')}/{j.get('region')}"
    except Exception as e:  # noqa: BLE001
        out.update(ip="", verdict="DEAD", why=type(e).__name__)
        return out
    t = time.time()
    rc, so, se = ytdlp(["--flat-playlist", "--print", "%(id)s", "--playlist-items", "1-3",
                        "ytsearch3:river flood drone footage"], proxy)
    out["search"] = len([x for x in so.split() if len(x) == 11])
    out["search_s"] = round(time.time() - t, 1)
    t = time.time()
    rc, so, se = ytdlp(["-j", "--skip-download", "--no-playlist", "-f", FMT, "-S", "res:1080",
                        f"https://www.youtube.com/watch?v={video}"], proxy, timeout=120)
    out["meta_s"] = round(time.time() - t, 1)
    if rc != 0 or not so.strip():
        out.update(verdict=verdict_of(se, rc), why=clean(se.strip().splitlines()[-1] if se.strip() else "", proxy))
        return out
    try:
        info = json.loads(so.strip().splitlines()[-1])
    except ValueError:
        out.update(verdict="FAIL", why="metadata not JSON")
        return out
    fmts = info.get("requested_formats") or [info]
    vfmt = next((f for f in fmts if f.get("vcodec") not in (None, "none")), fmts[0])
    out["format"] = f"{vfmt.get('format_id')}|{vfmt.get('height')}|{vfmt.get('protocol')}"
    url = vfmt.get("url") or ""
    if not url or not str(vfmt.get("protocol", "")).startswith("http"):
        out.update(verdict="FAIL", why=f"no direct stream ({vfmt.get('protocol')})")
        return out
    t = time.time()
    try:
        headers = dict(vfmt.get("http_headers") or {})
        headers["Range"] = "bytes=0-524287"
        r = requests.get(url, headers=headers, proxies=kw["proxies"], timeout=30, stream=True)
        got = 0
        for chunk in r.iter_content(65536):
            got += len(chunk)
            if got >= 524288:
                break
        r.close()
        out["stream"] = f"{r.status_code} {got // 1024}KB"
        out["stream_s"] = round(time.time() - t, 1)
        if r.status_code in (200, 206) and got > 100_000:
            out["verdict"] = "PASS"
        else:
            out["verdict"] = "STREAM_REFUSED" if r.status_code == 403 else "FAIL"
    except Exception as e:  # noqa: BLE001
        out.update(verdict="FAIL", why=f"stream: {type(e).__name__}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pool", required=True)
    ap.add_argument("--video", default="ka2S39HhLsM")
    ap.add_argument("--out", default="proxy_audit_light.jsonl")
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between proxies")
    a = ap.parse_args()
    pool = load_pool(a.pool)
    print(f"{len(pool)} proxies; video {a.video}", flush=True)
    rows = []
    for i, p in enumerate(pool, 1):
        o = check(i, p, a.video)
        print(json.dumps(o), flush=True)
        rows.append(o)
        time.sleep(a.gap)
    with open(a.out, "w", encoding="utf-8") as fh:
        for o in rows:
            fh.write(json.dumps(o) + "\n")
    ok = [o["proxy"] for o in rows if o.get("verdict") == "PASS"]
    print(f"PASS {len(ok)}/{len(rows)}: {ok}")
    print("NOT:", [(o["proxy"], o.get("verdict")) for o in rows if o.get("verdict") != "PASS"])


if __name__ == "__main__":
    main()
