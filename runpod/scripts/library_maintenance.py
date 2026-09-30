"""
Footage library maintenance: check the old library rows (clips still in the
app's storage), move the good ones to the R2 library bucket and mark the bad
ones removed (saved=false, analysis.removedReason - reversible in the app).

Every plan/build job already runs a short pass of this in the background
(library.start_maintenance: LIBRARY_MAINTENANCE_MAX rows in
LIBRARY_MAINTENANCE_SECONDS). This script runs a whole pass at once.

Inside a worker job (a pod or serverless worker with the template's env - R2
keys, STORAGE_BROKER_URL - while the app shows that job's project as
rendering; the broker authorises only the running job):

    python scripts/library_maintenance.py --project <project id> --job <job id> \
        [--seconds 1800] [--max 1000] [--dry-run]

Offline dry run over exported rows (a JSON list of footage_library rows, each
with a readable URL in "readUrl"); judges every file and writes nothing:

    python scripts/library_maintenance.py --rows rows.json [--out verdicts.json]

Set LOCAL_VISION_DIR to the CLIP model folder off RunPod (the relevance and
text/slide checks are skipped without it). Prints the counts as JSON.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config, library  # noqa: E402


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=os.getenv("PROJECT_ID", ""))
    ap.add_argument("--job", default=os.getenv("JOB_ID", ""))
    ap.add_argument("--rows", help="offline dry run over these exported rows (JSON list)")
    ap.add_argument("--seconds", type=float, default=1800.0)
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--parallel", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", help="write the full result (with every verdict) here")
    a = ap.parse_args(argv)

    if a.rows:
        with open(a.rows, encoding="utf-8") as fh:
            rows = json.load(fh)
        lib = library.Library("offline", "offline")
        lib.entries = [e for e in (library._from_row(r) for r in rows if isinstance(r, dict)) if e]
        lib.loaded = lib.db = True
        result = lib.maintain(seconds=a.seconds, max_items=a.max, dry_run=True, parallel=a.parallel)
    else:
        if not (a.project and a.job):
            ap.error("--project and --job (the running job) are required, or --rows for an offline dry run")
        lib = library.Library(a.project, a.job)
        if not lib.enabled:
            ap.error("no storage broker here (STORAGE_BROKER_URL / SUPABASE_URL unset, or a service key is set)")
        if not lib._load_db():
            ap.error("the app has no footage_library actions")
        result = lib.maintain(seconds=a.seconds, max_items=a.max, dry_run=a.dry_run, parallel=a.parallel)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
    summary = {k: v for k, v in result.items() if k != "verdicts"}
    summary["local_clip"] = bool(os.path.isdir(config.LOCAL_VISION_DIR))
    print(json.dumps(summary, indent=1))
    return result


if __name__ == "__main__":
    main()
