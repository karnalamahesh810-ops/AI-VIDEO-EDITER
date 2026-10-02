"""
Build or refresh a niche footage pack (src/packbuild.py): the shelf of
pre-checked clips the fallback ladder takes from (src/packs.py).

Sources are only NASA, Wikimedia Commons (public domain / CC0 / CC BY / CC BY-SA),
the Internet Archive (explicit public-domain or CC0 licence URL) and the owner's
own unused library clips - never YouTube or a stock site. See packbuild.py.

A free listing of what a build would fetch (no download, no keys):

    python scripts/build_pack.py --niche water --dry-run [--resolve] [--max-clips 40]

A real build needs the CLIP model (LOCAL_VISION_DIR), ffmpeg and, to upload, the R2
env of a worker (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
R2_LIBRARY_BUCKET, R2_LIBRARY_PUBLIC_BASE). It adds up to --max-clips new clips,
writes packs/<niche>/index.json as it goes and can be run again to continue:

    python scripts/build_pack.py --niche water --max-clips 60 --seconds 3000

Build into a local folder first to look at the result (set PACKS_DIR to that
folder to try it in a job):

    python scripts/build_pack.py --niche water --max-clips 5 --local-dir ./packs_out

The owner's unused library clips (never shown in a video) are catalogued too, from
a running job's project (the broker authorises only the running job) or from
exported rows:

    python scripts/build_pack.py --niche water --project <id> --job <id> --sources nasa,wikimedia,archive,library
    python scripts/build_pack.py --niche water --library-rows rows.json --sources library

On the endpoint or a pod, the same build is the handler action
{"action": "pack_build", "niche": "water", "max_clips": 40}. Prints the summary as JSON.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import library, packbuild, packs  # noqa: E402


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--niche", help=f"one of {', '.join(packs.NICHES)}")
    ap.add_argument("--max-clips", type=int, default=40, help="new clips to add in this run")
    ap.add_argument("--sources", default="nasa,wikimedia,archive", help="comma list of nasa, wikimedia, archive, library")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched; download nothing")
    ap.add_argument("--resolve", action="store_true", help="with --dry-run: also look up each item's video file link")
    ap.add_argument("--seconds", type=float, default=1500.0, help="stop starting new sources after this long")
    ap.add_argument("--parallel", type=int, default=2, help="source videos processed at once")
    ap.add_argument("--local-dir", default="", help="write the pack to this folder instead of R2")
    ap.add_argument("--project", default=os.getenv("PROJECT_ID", ""))
    ap.add_argument("--job", default=os.getenv("JOB_ID", ""))
    ap.add_argument("--library-rows", help="exported footage_library rows (JSON list) to catalogue offline")
    ap.add_argument("--list-niches", action="store_true")
    ap.add_argument("--out", help="also write the summary here")
    a = ap.parse_args(argv)

    if a.list_niches:
        result = {n.name: [t.name for t in n.topics] for n in packs.NICHES.values()}
        print(json.dumps(result, indent=2))
        return result
    if not a.niche:
        ap.error("--niche is required (or --list-niches)")
    lib = None
    if "library" in a.sources and not a.dry_run:
        if a.library_rows:
            with open(a.library_rows, encoding="utf-8") as fh:
                rows = json.load(fh)
            lib = library.Library("offline", "offline")
            lib.entries = [e for e in (library._from_row(r) for r in rows if isinstance(r, dict)) if e]
            lib.loaded = lib.db = True
        elif a.project and a.job:
            lib = library.Library(a.project, a.job)
            if not lib.enabled or not lib._load_db():
                ap.error("the library could not be read (no storage broker here, or the job is not running)")
        else:
            ap.error("--sources library needs --project and --job, or --library-rows")
    result = packbuild.run(a.niche, max_clips=a.max_clips, sources=[s.strip() for s in a.sources.split(",") if s.strip()],
                           dry_run=a.dry_run, resolve=a.resolve, seconds=a.seconds, local_dir=a.local_dir, library=lib,
                           parallel=a.parallel)
    text = json.dumps(result, indent=2, default=str)
    print(text)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    return result


if __name__ == "__main__":
    out = main()
    sys.exit(0 if out.get("ok", True) else 1)
