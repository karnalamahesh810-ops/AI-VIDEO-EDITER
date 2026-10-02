"""
Write remotion/src/templates/editor_only.json: the looks the planner never
places on its own (the owner's bans, the bar-text and old date looks -
templates.BANNED and treatments.auto_ok). The editor can still add them by
hand; the app's Brand Kit page leaves them out of the picks grid, since a
pick there could never show. Looks the registry itself marks "autoPick":
false are read from the registry by the app. tests/test_brand_kit.py keeps
this file current: run this script when that test says it is stale.

    python scripts/write_editor_only.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("SKIP_DOTENV", "1")

from src import templates, treatments  # noqa: E402

PATH = os.path.join(ROOT, "remotion", "src", "templates", "editor_only.json")


def editor_only() -> list:
    # (A look flagged "autoPick": false is left to the registry's own flag, so
    # this file does not change when such looks are added or switched on.)
    return sorted(t["id"] for t in templates.all_templates()
                  if templates.auto_pick(t) and (templates.banned_always(t["id"]) or not treatments.auto_ok(t["id"])))


if __name__ == "__main__":
    with open(PATH, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"note": "Looks the planner never places on its own (scripts/write_editor_only.py).",
                   "ids": editor_only()}, fh, indent=1)
        fh.write("\n")
    print(f"wrote {PATH}")
