#!/usr/bin/env python3
"""
Fetches WTI crude oil price history from FRED's DCOILWTICO series and writes
data/oil-price.json -- same file name/shape as the earlier (abandoned)
API-Ninjas-backed version, so OilPriceService.kt on the Android side didn't need
to change at all, just point at wherever this file lives.

UNLIKE that earlier version, this does NOT need to slowly accumulate day by day.
FRED has a real historical archive (same as the app's own direct FRED calls for
us2y/vix), so every run just re-fetches a fresh rolling window and OVERWRITES the
file completely -- no cold-start wait, and a day this Action fails to run on
self-heals automatically on the next successful run (the window just includes it
again), rather than being a permanently missing date. That's the whole reason this
is worth rebuilding with FRED instead of reviving the API Ninjas approach.

FRED's own missing-value marker for a day it didn't publish (a weekend, a US
market holiday) is the literal string "." in the observations response -- skipped
here the same way the Android app's own FRED parsing already does, rather than
treated as a real 0.0 reading.

Requires FRED_API_KEY as an environment variable (a GitHub Actions repository
secret -- Settings -> Secrets and variables -> Actions -> New repository secret
-- never committed to this file or the repo). Get a free key at
https://fred.stlouisfed.org/docs/api/api_key.html if the repo doesn't already
have one from elsewhere in this project.
"""
import json
import os
import sys
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "oil-price.json"
SERIES_ID = "DCOILWTICO"

# How far back each run re-fetches, fresh, every time. Generous relative to what the
# app actually needs (a 5-day change with a couple of days' tolerance) so the file
# comfortably covers even a run that was missed for several days in a row.
LOOKBACK_DAYS = 60


def fetch_series(api_key: str, start: date, end: date) -> list[dict]:
    params = {
        "series_id": SERIES_ID,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "asc",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
    }
    url = f"https://api.stlouisfed.org/fred/series/observations?{urllib.parse.urlencode(params)}"
    try:
        with urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR: HTTP {e.code} from FRED: {body}", file=sys.stderr)
        raise
    return data.get("observations", [])


def main() -> None:
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("ERROR: FRED_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)

    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    observations = fetch_series(api_key, start, end)

    entries = []
    for obs in observations:
        raw_value = obs.get("value", ".")
        if raw_value == ".":
            continue  # FRED's own "no observation this day" marker -- not a real 0.0
        try:
            entries.append({"date": obs["date"], "price": round(float(raw_value), 4)})
        except (KeyError, ValueError):
            continue

    entries.sort(key=lambda e: e["date"])

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(entries, indent=2) + "\n")

    if entries:
        print(f"Wrote {len(entries)} real observation(s), {entries[0]['date']} to {entries[-1]['date']}.")
    else:
        print("WARNING: FRED returned zero real observations for this window -- check the key/series ID.", file=sys.stderr)


if __name__ == "__main__":
    main()
