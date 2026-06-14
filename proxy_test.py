"""Test whether the Decodo proxy in proxy.txt can actually fetch YouTube (datacenter proxies
are often blocked). Reads creds from the gitignored proxy.txt; never prints the password."""
import subprocess, sys, os, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__))

line = open(os.path.join(HERE, "proxy.txt")).read().strip()
parts = line.split(":")
if len(parts) != 4:
    print("proxy.txt must be host:port:user:password"); sys.exit(2)
host, port, user, pw = parts
if pw == "<password>" or not pw:
    print("!! Put the real Decodo password in serverless/proxy.txt (replace <password>), then re-run.")
    sys.exit(2)

_u = urllib.parse.quote(user, safe=""); _p = urllib.parse.quote(pw, safe="")
PURL = f"http://{_u}:{_p}@{host}:{port}"
print(f"proxy: http://{user}:***@{host}:{port}\n")   # password masked on purpose

def yt(args, timeout=120):
    return subprocess.run([sys.executable, "-m", "yt_dlp", "--proxy", PURL,
                           "--extractor-args", "youtube:player_client=web_safari,android",
                           "--ffmpeg-location", "C:/app/app", "--no-warnings", *args],
                          capture_output=True, text=True, timeout=timeout)

# 0) what IP does YouTube see through this proxy?
ipr = subprocess.run([sys.executable, "-m", "yt_dlp", "--proxy", PURL, "--simulate",
                      "--no-warnings", "https://api.ipify.org"], capture_output=True, text=True, timeout=60)

# 1) can it read a known public video's title?
print("== test 1: fetch a known video's title ==")
r = yt(["--print", "%(title)s", "--skip-download", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
print(" rc", r.returncode, "| title:", (r.stdout.strip()[:90] or "(none)"))
if r.returncode != 0:
    print(" err:", r.stderr.strip()[-400:])

# 2) the real use case: list newest from one of the user's channels
ch = "newyorkreports1"
print(f"\n== test 2: list newest video from @{ch} ==")
r2 = yt(["--flat-playlist", "--print", "%(id)s", "--playlist-end", "1",
         f"https://www.youtube.com/@{ch}/videos"])
print(" rc", r2.returncode, "| id:", (r2.stdout.strip()[:40] or "(none)"))
if r2.returncode != 0:
    print(" err:", r2.stderr.strip()[-400:])

# 3) actually pull 5s of that video (the part that really matters)
vid = r2.stdout.strip().split()[0] if (r2.returncode == 0 and r2.stdout.strip()) else "dQw4w9WgXcQ"
print(f"\n== test 3: download 5s of {vid} through the proxy ==")
out = os.path.join(HERE, "proxy_dl_test.mp4")
if os.path.exists(out): os.remove(out)
r3 = yt(["-f", "b[height<=720]/best", "--download-sections", "*0-5",
         "-o", out, f"https://www.youtube.com/watch?v={vid}"], timeout=180)
ok = os.path.exists(out) and os.path.getsize(out) > 50000
print(" rc", r3.returncode, "| downloaded:", ok, f"({os.path.getsize(out)//1024} KB)" if ok else "")
if not ok:
    print(" err:", r3.stderr.strip()[-400:])

print("\n=== VERDICT:", "PROXY WORKS for YouTube - real download succeeded" if ok else "proxy did NOT complete a real download (throttled/blocked -> may need residential)")
