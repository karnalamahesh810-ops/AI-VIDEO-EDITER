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
  # pod_job.py deletes this pod itself (POD_EXIT=terminate; a pod started by
  # hand is stopped) once its result is saved. When it could not - it died
  # before getting there (an import error, a broken image) or RunPod refused
  # its request - the pod would sit here billing: ask again from here. A
  # request for a pod already going is harmless. The key is never printed.
  key="${POD_STOP_KEY:-${FANOUT_API_KEY:-${RUNPOD_API_KEY:-}}}"
  if [ -n "${RUNPOD_POD_ID:-}" ] && [ -n "$key" ]; then
    sleep 60
    for attempt in 1 2 3; do
      if [ "${POD_EXIT:-}" = "terminate" ]; then
        code=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE -H "Authorization: Bearer $key" \
          "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID") || code=000
      else
        code=$(curl -s -o /dev/null -w "%{http_code}" -X POST -H "Authorization: Bearer $key" \
          "https://rest.runpod.io/v1/pods/$RUNPOD_POD_ID/stop") || code=000
      fi
      echo "[pod] still here after the job: ${POD_EXIT:-stop} requested again (HTTP $code)"
      case "$code" in 2??) break ;; esac
      sleep 30
    done
  fi
fi
sleep infinity
