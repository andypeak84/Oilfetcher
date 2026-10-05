#!/usr/bin/env python3
"""
Fetches crude oil price history (WTI and Brent) and writes data/oil-price.json and
data/brent-price.json -- same file shape as the earlier (abandoned) API-Ninjas-backed
version, so OilPriceService.kt/BrentPriceService.kt on the Android side never need to
change, just point at wherever these files live.

Every run re-fetches a fresh rolling window and OVERWRITES each file completely -- no
cold-start wait, and a day this Action fails to run on self-heals automatically on the
next successful run (the window just includes it again), rather than being a
permanently missing date.

FRED's own missing-value marker for a day it didn't publish (a weekend, a US market
holiday) is the literal string "." in the observations response -- skipped here the
same way the Android app's own FRED parsing already does, rather than treated as a
real 0.0 reading.

Requires FRED_API_KEY as an environment variable (a GitHub Actions repository secret
-- Settings -> Secrets and variables -> Actions -> New repository secret -- never
committed to this file or the repo). Get a free key at
https://fred.stlouisfed.org/docs/api/api_key.html if the repo doesn't already have
one from elsewhere in this project.

EIA FALLBACK (added after FRED's DCOILWTICO stalled twice in two weeks -- once for
6+ days, observation_end stuck while last_updated didn't move either): FRED's series
here are its own mirrors of EIA's own spot-price series, synced with their own extra
lag on top of EIA's. When FRED's newest real observation is more than
ANCHOR_TOLERANCE_BUSINESS_DAYS behind today -- the same 1-business-day anchor
tolerance MarketRepository.changeNDaysAgoFromSeries uses for oilChange5d/
brentChange5d, kept in sync deliberately -- this also fetches the matching EIA series
directly and adds any date EIA has that FRED doesn't. FRED entries are never
overwritten by EIA when both have the same date (FRED stays the primary/preferred
source so day-to-day behavior doesn't change on a normal day) -- EIA only ever fills
gaps FRED doesn't have yet. Optional EIA_API_KEY env var (repo secret, free key:
https://www.eia.gov/opendata/register.php); if unset, the fallback is simply skipped
and this behaves as if only FRED existed.

BRENT (added alongside WTI): WTI (Cushing, Oklahoma) is a US-specific, pipeline-bound
benchmark -- Brent is the global benchmark UK/European fuel pricing actually tracks
more closely, and real-world comparison (2026-09) showed Brent running $15-25/barrel
above WTI with FRED's Brent series staying current while WTI's stalled for over a
week. Fetched and written the same way as WTI, as a second, independent benchmark --
not a replacement, since the two carry different information (regional/geopolitical
risk premiums show up in Brent first; US-specific supply/storage dynamics in WTI).
"""
import json
import os
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# How far back each run re-fetches, fresh, every time. Generous relative to what the
# app actually needs (a 5-day change with a couple of days' tolerance) so each file
# comfortably covers even a run that was missed for several days in a row.
LOOKBACK_DAYS = 60

# Kept in sync with MarketRepository.kt's anchorToleranceDays=1 for oilChange5d/
# brentChange5d -- see that function's own doc comment for why this is deliberately
# small (covers a routine single-holiday miss, not a genuine multi-day outage).
ANCHOR_TOLERANCE_BUSINESS_DAYS = 1

BENCHMARKS = [
    # (data file, FRED series, EIA series)
    {"file": "oil-price.json", "fred_series": "DCOILWTICO", "eia_series": "RWTC", "label": "WTI"},
    {"file": "brent-price.json", "fred_series": "DCOILBRENTEU", "eia_series": "RBRTE", "label": "Brent"},
]


def business_days_between(a: date, b: date) -> int:
    """Mirrors AppClock.businessDaysBetween (Kotlin) exactly: count of business days
    (Mon-Fri) strictly after the earlier date through the later date."""
    start, end = (a, b) if a <= b else (b, a)
    count = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:  # Mon=0 .. Sun=6
            count += 1
    return count


def fetch_fred_series(series_id: str, api_key: str, start: date, end: date) -> list[dict]:
    params = {
        "series_id": series_id,
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
        print(f"ERROR: HTTP {e.code} from FRED ({series_id}): {body}", file=sys.stderr)
        raise

    entries = []
    for obs in data.get("observations", []):
        raw_value = obs.get("value", ".")
        if raw_value == ".":
            continue  # FRED's own "no observation this day" marker -- not a real 0.0
        try:
            entries.append({"date": obs["date"], "price": round(float(raw_value), 4)})
        except (KeyError, ValueError):
            continue
    return entries


def fetch_eia_series(series_id: str, api_key: str, start: date, end: date) -> list[dict]:
    params = {
        "api_key": api_key,
        "frequency": "daily",
        "data[]": "value",
        "facets[series][]": series_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": "5000",
    }
    url = f"https://api.eia.gov/v2/petroleum/pri/spt/data/?{urllib.parse.urlencode(params)}"
    try:
        with urlopen(url, timeout=30) as resp:
            data = json.load(resp)
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"WARNING: HTTP {e.code} from EIA ({series_id}, non-fatal, FRED data is still used): {body}",
              file=sys.stderr)
        return []

    entries = []
    for row in data.get("response", {}).get("data", []):
        try:
            entries.append({"date": row["period"], "price": round(float(row["value"]), 4)})
        except (KeyError, ValueError, TypeError):
            continue
    return entries


def fetch_benchmark(benchmark: dict, fred_key: str, eia_key: str | None, start: date, today: date) -> None:
    label = benchmark["label"]
    fred_entries = fetch_fred_series(benchmark["fred_series"], fred_key, start, today)
    by_date = {e["date"]: e["price"] for e in fred_entries}

    fred_newest = max((datetime.fromisoformat(d).date() for d in by_date), default=None)
    staleness = business_days_between(fred_newest, today) if fred_newest else None

    if staleness is not None and staleness > ANCHOR_TOLERANCE_BUSINESS_DAYS:
        print(f"[{label}] FRED's newest observation ({fred_newest}) is {staleness} business day(s) "
              f"stale -- trying EIA's {benchmark['eia_series']} as a fallback for the gap.")
        if not eia_key:
            print(f"[{label}] No EIA_API_KEY set -- skipping the fallback, FRED data only.")
        else:
            eia_entries = fetch_eia_series(benchmark["eia_series"], eia_key, start, today)
            added = 0
            for e in eia_entries:
                if e["date"] not in by_date:  # never overwrite FRED -- it stays primary
                    by_date[e["date"]] = e["price"]
                    added += 1
            eia_newest = max((datetime.fromisoformat(e["date"]).date() for e in eia_entries), default=None)
            print(f"[{label}] EIA's newest observation: {eia_newest}. Added {added} date(s) FRED didn't have.")
    elif staleness is None:
        print(f"[{label}] WARNING: FRED returned zero real observations for this window -- "
              f"check the key/series ID.", file=sys.stderr)

    entries = [{"date": d, "price": p} for d, p in sorted(by_date.items())]

    data_file = DATA_DIR / benchmark["file"]
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text(json.dumps(entries, indent=2) + "\n")

    if entries:
        print(f"[{label}] Wrote {len(entries)} real observation(s), {entries[0]['date']} to {entries[-1]['date']}.")
    else:
        print(f"[{label}] WARNING: zero real observations from either source -- check the keys/series IDs.",
              file=sys.stderr)


def main() -> None:
    fred_key = os.environ.get("FRED_API_KEY")
    if not fred_key:
        print("ERROR: FRED_API_KEY environment variable not set", file=sys.stderr)
        sys.exit(1)
    eia_key = os.environ.get("EIA_API_KEY")

    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)

    for benchmark in BENCHMARKS:
        fetch_benchmark(benchmark, fred_key, eia_key, start, today)


if __name__ == "__main__":
    main()
