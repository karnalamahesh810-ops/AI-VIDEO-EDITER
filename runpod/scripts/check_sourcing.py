"""Bounded live proxy/search check; --download verifies a three-second clip.

Reads the worker environment. Never prints proxy credentials or raw errors.
Run this inside the deployed image too: local success does not verify RunPod.
"""
import argparse
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src import config, media


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true')
    parser.add_argument('--require-cc', action='store_true',
                        help='Also test the worker Creative Commons filter')
    parser.add_argument('--query', default='Grand Canyon landscape')
    parser.add_argument('--out', default='out/sourcing-check')
    args = parser.parse_args()
    result = {'proxyConfigured': bool(config.YTDLP_PROXIES),
              'proxyCount': len(config.YTDLP_PROXIES)}
    for package in ('yt-dlp', 'yt-dlp-ejs'):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = 'missing'
    # Diagnostic only: an unfiltered result tests transport, not reuse rights.
    # This never changes the worker's REQUIRE_CC sourcing setting.
    candidates = media._yt_candidates('ytsearch1:' + args.query, args.require_cc,
                                      limit=1, timeout=90)
    result['creativeCommonsFilter'] = args.require_cc
    result['searchResults'] = len(candidates)
    result['ok'] = bool(candidates)
    if args.download and candidates:
        Path(args.out).mkdir(parents=True, exist_ok=True)
        candidate = candidates[0]
        start = min(30, max(0, candidate['duration'] - 5))
        path = media._yt_fetch(candidate['id'], args.out, start, 3, timeout=120)
        result['downloaded'] = bool(path)
        result['ok'] = False
        if path:
            probe = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration:stream=codec_type,width,height',
                '-of', 'json', path], capture_output=True, text=True, timeout=20)
            data = json.loads(probe.stdout) if probe.returncode == 0 else {}
            duration = float(data.get('format', {}).get('duration', 0))
            video = any(s.get('codec_type') == 'video' for s in data.get('streams', []))
            result.update(duration=duration, bytes=os.path.getsize(path),
                          ok=video and 2 <= duration <= 5,
                          output=str(Path(path).resolve()))
    print(json.dumps(result, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({'ok': False, 'errorType': type(exc).__name__}))
        sys.exit(1)
