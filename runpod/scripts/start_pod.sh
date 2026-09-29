#!/bin/sh
# Pod entrypoint: the PO-token server, then one video (scripts/pod_job.py),
# then stay up quietly so the container is not restarted into a second run
# before the pod stops itself.
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
# The done-marker lives on the pod volume, so starting this stopped pod again
# never re-runs a video it already made (give the pod a new JOB_B64 instead).
dir=/workspace; [ -d "$dir" ] || dir=/tmp
mark="$dir/.pod_job_$(printf '%s' "${JOB_B64:-}${JOB_URL:-}" | md5sum | cut -c1-16).done"
if [ -z "${JOB_B64:-}${JOB_URL:-}" ]; then
  echo "[pod] no JOB_B64 or JOB_URL; idling"
elif [ -f "$mark" ]; then
  echo "[pod] this job already ran on this pod; idling"
else
  touch "$mark"
  python -u scripts/pod_job.py 2>&1 | tee "$dir/pod_job.log"
fi
sleep infinity
