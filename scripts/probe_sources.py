"""One-off probe (manual workflow only): newest date/value each candidate source has for Brent, WTI and VIX.

Prints a table to the Actions log and publishes nothing. Every source is tried independently, so one failure
(missing key, outage, rate limit) is reported on its own line and never stops the others. No secret is printed.
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_oil_price_fred as oil  # noqa: E402  (reuse its EIA fetcher)


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 probe"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def newest(rows):
    rows = [(d, v) for d, v in rows if v is not None]
    return max(rows)[0:2] if rows else None


def fred_csv(series):
    out = []
    for line in get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}").splitlines()[1:]:
        d, _, v = line.partition(",")
        try:
            out.append((d, float(v)))
        except ValueError:
            pass
    return out


def eia(series):
    k = os.environ.get("EIA_API_KEY", "").strip()
    if not k:
        raise RuntimeError("no EIA_API_KEY")
    rows = oil.fetch_eia_series(series, k, date.today() - timedelta(days=21), date.today())
    return [(r["date"], r["price"]) for r in rows]


def av(function):
    k = os.environ.get("ALPHA_VANTAGE_API_KEY", "").strip()
    if not k:
        raise RuntimeError("no ALPHA_VANTAGE_API_KEY")
    body = json.loads(get(f"https://www.alphavantage.co/query?function={function}&interval=daily&apikey={k}"))
    if "data" not in body:
        raise RuntimeError("no data: " + str({a: b for a, b in body.items() if a != "apikey"})[:150])
    return [(r["date"], float(r["value"])) for r in body["data"] if r["value"] not in (".", "")]


def oilpriceapi(code):
    k = os.environ.get("OILPRICEAPI_KEY", "").strip()
    if not k:
        raise RuntimeError("no OILPRICEAPI_KEY (optional)")
    req = urllib.request.Request(f"https://api.oilpriceapi.com/v1/prices/latest?by_code={code}",
                                 headers={"Authorization": f"Token {k}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.load(r)
    p = d["data"]
    return [(str(p.get("created_at", "?"))[:19], float(p["price"]))]


def yahoo(sym):
    # Probe only, to know what exists; its terms do not allow shipping this in the app.
    d = json.loads(get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range=7d&interval=1d"))
    r = d["chart"]["result"][0]
    return [(date.fromtimestamp(t).isoformat(), c) for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]


CANDIDATES = [
    ("Brent", "EIA API", lambda: eia("RBRTE")),
    ("Brent", "FRED csv", lambda: fred_csv("DCOILBRENTEU")),
    ("Brent", "AlphaVantage BRENT", lambda: av("BRENT")),
    ("Brent", "OilPriceAPI latest", lambda: oilpriceapi("BRENT_CRUDE_USD")),
    ("Brent", "Yahoo (probe only)", lambda: yahoo("BZ=F")),
    ("WTI", "EIA API", lambda: eia("RWTC")),
    ("WTI", "FRED csv", lambda: fred_csv("DCOILWTICO")),
    ("WTI", "AlphaVantage WTI", lambda: av("WTI")),
    ("WTI", "Yahoo (probe only)", lambda: yahoo("CL=F")),
    ("VIX", "FRED csv", lambda: fred_csv("VIXCLS")),
    ("VIX", "Yahoo (probe only)", lambda: yahoo("^VIX")),
]


def main():
    print(f"probe run {date.today()} (a Brent/WTI/VIX value for date D means D's close)\n")
    for feature, name, fn in CANDIDATES:
        try:
            n = newest(fn())
            print(f"{feature:6} | {name:22} | newest {n[0]}  value {n[1]}" if n else f"{feature:6} | {name:22} | EMPTY")
        except Exception as e:  # noqa: BLE001 - report per source, keep going
            print(f"{feature:6} | {name:22} | FAILED: {str(e)[:150]}")


if __name__ == "__main__":
    main()
