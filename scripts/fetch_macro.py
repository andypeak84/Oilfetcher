#!/usr/bin/env python3
"""
Publishes the two US market series the Android app needs, as plain JSON files shaped exactly
like data/oil-price.json (a list of {"date": "YYYY-MM-DD", "price": N}), so the app can read
them from raw.githubusercontent.com with NO API key inside the app:

  data/us2y.json   US 2-year Treasury yield (%)
  data/vix.json    CBOE VIX close

Why this exists: the app used to call FRED directly with an API key compiled into the APK. For a
public Google Play release that key would be extractable by anyone, so the app now reads these
files instead and the key stays here, in a GitHub Actions secret (FRED_API_KEY).

US 2-year yield: the U.S. Treasury's own daily par yield curve (keyless, and it publishes the same
numbers FRED's DGS2 mirrors, a day or two sooner). FRED's DGS2 is the fallback if Treasury is down.
VIX: FRED's VIXCLS only (no keyless source worked). If FRED is down the existing file is left
untouched -- the app already handles a missing VIX (the model skips a missing feature).

Never overwrites a file with an empty result. Each series is isolated: one failing does not stop
the other, but the run still exits non-zero so the failure shows in the Actions history.
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_oil_price_fred import LOOKBACK_DAYS, fetch_fred_series  # noqa: E402  (reuse the tested FRED helper)

DATA_DIR = Path(os.environ.get("MACRO_DATA_DIR") or Path(__file__).resolve().parent.parent / "data")

TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
                "?data=daily_treasury_yield_curve&field_tdr_date_value_month={yyyymm}")
_D = "{http://schemas.microsoft.com/ado/2007/08/dataservices}"
_M = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"


def months_between(start: date, end: date) -> list[str]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur.strftime("%Y%m"))
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def fetch_treasury_2y(start: date, end: date) -> list[dict]:
    entries = []
    for yyyymm in months_between(start, end):
        req = Request(TREASURY_URL.format(yyyymm=yyyymm), headers={"User-Agent": "gbpusd-predictor-data/1.0"})
        with urlopen(req, timeout=30) as resp:
            root = ET.fromstring(resp.read())
        for props in root.iter(_M + "properties"):
            d, v = props.findtext(_D + "NEW_DATE"), props.findtext(_D + "BC_2YEAR")
            if not d or not v:
                continue  # a day with no 2-year reading (holiday rows can be blank)
            try:
                entries.append({"date": d[:10], "price": round(float(v), 4)})
            except ValueError:
                continue
    return [e for e in entries if start.isoformat() <= e["date"] <= end.isoformat()]


def get_us2y(start: date, end: date, fred_key: str | None) -> list[dict]:
    try:
        entries = fetch_treasury_2y(start, end)
        if entries:
            return entries
        print("[us2y] Treasury returned no rows -- trying FRED DGS2.", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"[us2y] Treasury failed ({type(e).__name__}: {str(e)[:120]}) -- trying FRED DGS2.", file=sys.stderr)
    if not fred_key:
        return []
    return fetch_fred_series("DGS2", fred_key, start, end)


def get_vix(start: date, end: date, fred_key: str | None) -> list[dict]:
    if not fred_key:
        print("[vix] No FRED_API_KEY set.", file=sys.stderr)
        return []
    # FRED's API times out now and then (seen from GitHub's runners); a few quick retries beat waiting
    # for the next scheduled run, and the app reads this file once a day, so every miss costs a day.
    last_error = None
    for attempt in range(1, 5):
        try:
            return fetch_fred_series("VIXCLS", fred_key, start, end)
        except Exception as e:  # noqa: BLE001
            last_error = e
            print(f"[vix] FRED attempt {attempt}/4 failed ({type(e).__name__}: {str(e)[:100]})", file=sys.stderr)
            time.sleep(5 * attempt)
    raise last_error


def publish(name: str, label: str, getter, start: date, end: date, fred_key: str | None) -> bool:
    try:
        entries = getter(start, end, fred_key)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: [{label}] failed entirely ({type(e).__name__}: {str(e)[:160]}); {name} left unchanged.",
              file=sys.stderr)
        return False
    if not entries:
        print(f"ERROR: [{label}] no observations from any source; {name} left unchanged.", file=sys.stderr)
        return False
    entries = sorted({e["date"]: e for e in entries}.values(), key=lambda e: e["date"])
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / name).write_text(json.dumps(entries, indent=2) + "\n")
    print(f"[{label}] Wrote {len(entries)} observation(s), {entries[0]['date']} to {entries[-1]['date']}.")
    return True


def main() -> None:
    fred_key = os.environ.get("FRED_API_KEY")
    today = date.today()
    start = today - timedelta(days=LOOKBACK_DAYS)
    ok = [
        publish("us2y.json", "us2y", get_us2y, start, today, fred_key),
        publish("vix.json", "vix", get_vix, start, today, fred_key),
    ]
    if not all(ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
