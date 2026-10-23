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
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "brent-latest.json"
KEEP = 400


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
    day = read_at[:10]
    rows = [r for r in rows if r["date"] != day] + [{"date": day, "price": round(price, 2), "readAtUtc": read_at}]
    rows.sort(key=lambda r: r["date"])
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(rows[-KEEP:], indent=1) + "\n")
    print(f"Brent {price} read {read_at} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
