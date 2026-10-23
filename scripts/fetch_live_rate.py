"""Publish the live GBP/USD rate as data/live-rate.json for the Android app's price alerts.

Alpha Vantage's free tier allows 25 calls a day, so this runs at most hourly on weekdays (see the workflow).
The API key stays in the repo secret ALPHA_VANTAGE_API_KEY; the app only ever reads the published file, so
no user needs a key. Never overwrites with an empty/failed reading: on any error the script exits non-zero
and the previous file stays up.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "live-rate.json"


def main():
    key = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not key:
        sys.exit("ALPHA_VANTAGE_API_KEY is not set")
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode({
        "function": "CURRENCY_EXCHANGE_RATE", "from_currency": "GBP", "to_currency": "USD", "apikey": key})
    with urllib.request.urlopen(url, timeout=30) as resp:
        body = json.load(resp)
    block = body.get("Realtime Currency Exchange Rate")
    if not block:
        # Rate-limit / bad-key replies are HTTP 200 with a Note/Information/Error Message field.
        sys.exit("Alpha Vantage returned no rate: " + str({k: v for k, v in body.items() if k != "apikey"})[:200])
    rate = float(block["5. Exchange Rate"])
    if not 0.5 < rate < 3.0:
        sys.exit(f"implausible GBP/USD rate {rate}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "rate": rate,
        "asOfUtc": block.get("6. Last Refreshed"),
        "fetchedUtc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }) + "\n")
    print("GBP/USD", rate)


if __name__ == "__main__":
    main()
