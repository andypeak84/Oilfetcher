"""One-off: rebuild data/brent-latest.json from OilPriceAPI's own history (no EIA/FRED values).

For each weekday it keeps the reading closest to 19:45 UTC (the time fetch-brent-latest.yml records), if one exists
within 3 hours of that, so the backfilled rows are on the same basis as the daily recorder's. Pages through
/v1/prices/past_month newest-first until it passes the cutoff. Needs OILPRICEAPI_KEY in the environment.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "brent-latest.json"
CUTOFF = datetime(2026, 9, 14, tzinfo=timezone.utc)   # a month of history, enough for any 20-day change
PER_PAGE = 100  # the API caps a page at 100 rows


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main():
    key = os.environ["OILPRICEAPI_KEY"].strip()
    rows = []
    page = 1
    while True:
        url = ("https://api.oilpriceapi.com/v1/prices/past_month?by_code=BRENT_CRUDE_USD"
               f"&page={page}&per_page={PER_PAGE}")
        req = urllib.request.Request(url, headers={"Authorization": f"Token {key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.load(r)["data"]["prices"]
        if not batch:
            break
        rows += [(parse(p["created_at"]), float(p["price"])) for p in batch]
        print(f"page {page}: {len(batch)} rows, {batch[0]['created_at']} -> {batch[-1]['created_at']}", file=sys.stderr)
        if parse(batch[-1]["created_at"]) < CUTOFF:
            break
        page += 1
    out = {}
    day = CUTOFF.date()
    end = datetime.now(timezone.utc).date()
    while day <= end:
        if day.weekday() < 5:
            target = datetime(day.year, day.month, day.day, 19, 45, tzinfo=timezone.utc)
            best = min(rows, key=lambda r: abs(r[0] - target), default=None)
            if best and abs(best[0] - target) <= timedelta(hours=3) and 10 < best[1] < 400:
                out[day.isoformat()] = {"date": day.isoformat(), "price": round(best[1], 2),
                                        "readAtUtc": best[0].strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "oilpriceapi-backfill"}
        day += timedelta(days=1)
    # keep today's live recorder row (newer than any backfill) if it exists
    if OUT.exists():
        for r in json.loads(OUT.read_text()):
            if r.get("source") != "eia-seed" and r["date"] not in out and r.get("readAtUtc"):
                out[r["date"]] = r
    final = [out[k] for k in sorted(out)]
    OUT.write_text(json.dumps(final, indent=1) + "\n")
    print(f"wrote {len(final)} rows {final[0]['date']} -> {final[-1]['date']}")


if __name__ == "__main__":
    main()
