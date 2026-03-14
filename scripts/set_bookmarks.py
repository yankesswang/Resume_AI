"""
Read interested_candidates.csv and print a browser console command
that sets all those candidates as bookmarked (interested) in the app.

Usage:
    uv run python scripts/set_bookmarks.py

Then paste the printed command into your browser's DevTools console
while the app is open at http://localhost:5173.
"""

import csv
import json
import sys
from pathlib import Path

CSV_PATH = Path(__file__).resolve().parent.parent / "interested_candidates.csv"
STORAGE_KEY = "resume-ai-bookmarks"


def main():
    if not CSV_PATH.exists():
        print(f"ERROR: {CSV_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    ids = []
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = row.get("ID", "").strip()
            if raw.isdigit():
                ids.append(int(raw))

    if not ids:
        print("No candidate IDs found in CSV.", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(ids)} candidates: {ids}\n")
    print("Paste this into your browser DevTools console (F12 → Console):\n")
    print(f"localStorage.setItem('{STORAGE_KEY}', JSON.stringify({json.dumps(ids)})); location.reload();")


if __name__ == "__main__":
    main()
