# Oil price fetcher (FRED) -- setup

Same overall pattern as the existing `gilt-yield-fetcher`: a small GitHub Action on a
daily schedule, writing one JSON file the Android app reads from
`raw.githubusercontent.com`. This is the second attempt at an oil fetcher -- the first
one (API Ninjas-backed) was abandoned after their free tier turned out premium-gated
for crude oil on both the endpoints it tried. FRED doesn't have that problem: it's the
same source the app already calls directly for `us2y`/`vix`, just moved off-device for
oil specifically at your request.

Real difference from the abandoned version: FRED has a genuine historical archive, so
this does NOT need to slowly accumulate day by day. Every run re-fetches a fresh
60-day window and overwrites the file completely -- no cold-start wait after first
setup, and a day this Action fails to run on self-heals automatically the next time it
runs successfully (that day just gets picked up again in the window), rather than
becoming a permanently missing date.

## Where these files go

Drop this into whichever repo you want to host it in -- your existing
`gilt-yield-fetcher` repo (reuses infra you've already got running) is a natural fit,
or a fresh repo if you'd rather keep it separate:

```
<your-repo>/
├── scripts/
│   └── fetch_oil_price_fred.py    <- new
├── data/
│   └── oil-price.json             <- new, starts as []
└── .github/workflows/
    └── fetch-oil-price.yml        <- new
```

**Whichever repo/path you use, tell me the exact URL** -- `OilPriceService.kt` on the
Android side needs to point at wherever this actually ends up
(`raw.githubusercontent.com/<user>/<repo>/<branch>/data/oil-price.json`).

## One-time setup

1. Copy the three files above into the repo, commit, push.
2. Add your FRED API key as a **repository secret**, not a committed file:
   Settings -> Secrets and variables -> Actions -> New repository secret -> name it
   `FRED_API_KEY`, paste the key value. (Same key value as `local.properties`'
   `FRED_API_KEY` in the Android project if you want to reuse it -- FRED keys aren't
   tied to a single application.)
3. That's it. Runs automatically at 20:30 UTC daily. To test immediately rather than
   waiting: Actions tab -> "Fetch oil price (FRED)" workflow -> "Run workflow" button
   (exists because of `workflow_dispatch` in the yml).

## Verifying it worked

Check `data/oil-price.json` in the repo after a run -- should show roughly 60 days of
real `{"date": ..., "price": ...}` entries, most-recent one within the last couple of
business days. Also check the Action's own log output in the Actions tab -- the script
prints exactly how many observations it wrote and the date range covered, or a clear
error if the key/series ID is wrong.
