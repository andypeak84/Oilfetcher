"""Once a day: record OilPriceAPI's latest Brent price in data/brent-latest.json.

Separate from data/brent-price.json (the EIA/FRED spot series the model was trained on): OilPriceAPI's
number is a different measure (it tracks the Brent futures price, e.g. 113.9 when the EIA spot series read
115.2 two days earlier), so the two must not be mixed in one series. This file is a one-reading-per-day
history, [{"date": "2026-10-23", "price": 113.89, "readAtUtc": "..."}], newest reading wins for a date.
Never overwrites with a failed/implausible reading: on any error the script exits non-zero, file untouched.
"""
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "brent-latest.json"
KEEP = 400
# A reading taken before this UTC hour belongs to the PREVIOUS trading day's close: GitHub often starts the evening job hours late, after
# midnight UTC, and it used to file that reading under the new calendar date (the 11 Nov close was recorded as 12 Nov, and the Monday
# closes on 2 and 9 Nov were never recorded at all).
EARLIEST_SAME_DAY_HOUR_UTC = 12


def market_day(read_at: str) -> str:
    """The trading day a reading belongs to: its UTC date, or the day before when read before 12:00 UTC; a weekend day counts as Friday."""
    t = datetime.fromisoformat(read_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    day = t.date() - timedelta(days=1) if t.hour < EARLIEST_SAME_DAY_HOUR_UTC else t.date()
    while day.weekday() >= 5:  # Saturday = 5, Sunday = 6
        day -= timedelta(days=1)
    return day.isoformat()


def relabel(rows: list[dict]) -> list[dict]:
    """Re-date every stored row by market_day (safe to repeat) and keep the latest reading for each day, which is the closest to the close."""
    best: dict[str, dict] = {}
    for r in rows:
        day = market_day(r["readAtUtc"]) if r.get("readAtUtc") else r["date"]
        row = {**r, "date": day}
        if day not in best or row.get("readAtUtc", "") >= best[day].get("readAtUtc", ""):
            best[day] = row
    return sorted(best.values(), key=lambda r: r["date"])


def main():
    key = os.environ.get("OILPRICEAPI_KEY", "").strip()
    if not key:
        sys.exit("OILPRICEAPI_KEY is not set")
    req = urllib.request.Request("https://api.oilpriceapi.com/v1/prices/latest?by_code=BRENT_CRUDE_USD",
                                 headers={"Authorization": f"Token {key}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    p = body["data"]
    price = float(p["price"])
    read_at = str(p["created_at"])
    if not 10 < price < 400:
        sys.exit(f"implausible Brent price {price}")
    rows = json.loads(OUT.read_text()) if OUT.exists() else []
    rows = relabel(rows + [{"date": market_day(read_at), "price": round(price, 2), "readAtUtc": read_at}])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows[-KEEP:], indent=1) + "\n")
    print(f"Brent {price} read {read_at} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
