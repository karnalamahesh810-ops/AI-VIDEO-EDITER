"""Put the laptop kit's used moments into a customer's ledger (src/stormledger.py), once, at deploy:
  python scripts/seed_storm_ledger.py <owner id> <used_moments.json> [channel] [--write]
Without --write it only says what it would do. Needs the R2_* settings in the environment. Moments already there stay."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SKIP_DOTENV", "1")
from src import r2, stormledger  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    owner, path = args[0], args[1]
    channel = args[2] if len(args) > 2 else ""
    key = stormledger.key_for(owner, channel)
    raw = r2.get_bytes(key)
    have = json.loads(raw).get("moments", []) if raw else []
    seen = {tuple(m[:3]) for m in have}
    new = [list(m[:3]) + ["laptop"] for m in json.load(open(path, encoding="utf-8")) if tuple(m[:3]) not in seen]
    print(f"{key}: {len(have)} there, {len(new)} to add")
    if write:
        r2.upload_bytes(json.dumps({"moments": have + new}, separators=(",", ":")).encode(), key)
        print("written")


if __name__ == "__main__":
    main()
