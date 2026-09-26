#!/bin/sh
# Worker entrypoint: the YouTube PO-token server beside the RunPod handler.
#
# yt-dlp's bgutil plugin fetches a proof-of-origin token from this server for
# every YouTube request; with it, an IP YouTube would otherwise answer with
# "Sign in to confirm you're not a bot" (every RunPod machine, some proxies)
# is served normally. The handler runs whether or not the server comes up -
# without it, downloads simply go through the proxies as before.
set -u
if [ -f /opt/bgutil/server/build/main.js ]; then
  node /opt/bgutil/server/build/main.js --port 4416 > /tmp/bgutil.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sf http://127.0.0.1:4416/ping > /dev/null 2>&1; then
      echo "[start] PO-token server ready" ; break
    fi
    sleep 1
  done
fi
exec python -u handler.py
