"""Run with: python -m pytest scripts/test_fetch_brent_latest.py  (or python scripts/test_fetch_brent_latest.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_brent_latest import market_day, relabel  # noqa: E402


def test_an_evening_reading_belongs_to_its_own_day():
    assert market_day("2026-11-10T19:45:00.000Z") == "2026-11-10"
    assert market_day("2026-11-10T23:56:25.364Z") == "2026-11-10"


def test_a_reading_after_midnight_belongs_to_the_previous_day():
    # the Wednesday 11 Nov evening job, started late at 01:36 UTC on Thursday 12 Nov
    assert market_day("2026-11-12T01:36:06.912Z") == "2026-11-11"
    # the Monday 9 Nov job, started late at 02:23 UTC on Tuesday 10 Nov
    assert market_day("2026-11-10T02:23:45.000Z") == "2026-11-09"


def test_weekend_readings_count_as_friday():
    assert market_day("2026-11-07T14:00:00Z") == "2026-11-06"   # Saturday afternoon
    assert market_day("2026-11-08T03:00:00Z") == "2026-11-06"   # Sunday small hours (Saturday's day before)
    assert market_day("2026-11-09T01:00:00Z") == "2026-11-06"   # Monday small hours: still Sunday's day, so Friday


def test_relabel_fixes_the_row_that_was_filed_under_the_wrong_date():
    rows = [
        {"date": "2026-11-10", "price": 91.92, "readAtUtc": "2026-11-10T23:56:25.364Z"},
        {"date": "2026-11-12", "price": 91.92, "readAtUtc": "2026-11-12T01:36:06.912Z"},
    ]
    assert [r["date"] for r in relabel(rows)] == ["2026-11-10", "2026-11-11"]


def test_relabel_keeps_the_latest_reading_when_two_fall_on_one_day():
    rows = [
        {"date": "2026-11-09", "price": 92.05, "readAtUtc": "2026-11-10T02:23:45.000Z"},
        {"date": "2026-11-09", "price": 92.40, "readAtUtc": "2026-11-09T23:56:00.000Z"},
    ]
    out = relabel(rows)
    assert len(out) == 1 and out[0]["price"] == 92.05 and out[0]["date"] == "2026-11-09"


def test_relabel_is_safe_to_repeat():
    rows = [{"date": "2026-11-12", "price": 91.92, "readAtUtc": "2026-11-12T01:36:06.912Z"}]
    assert relabel(relabel(rows)) == relabel(rows)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
