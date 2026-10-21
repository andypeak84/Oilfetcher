"""Time-decayed rolling sentiment, in [-1, +1] (negative = bearish GBP/USD)."""
import time

import config
import db


def decay(age_hours, half_life=None):
    half_life = half_life or config.HALF_LIFE_HOURS
    return 0.5 ** (max(age_hours, 0.0) / half_life)


def window_score(rows, window_hours, now=None):
    """Weighted average direction over rows inside the window.

    Each article contributes direction * confidence * source_weight * decay.
    Dividing by the total available weight keeps the result within [-1, 1],
    so one confident article and ten confident articles are comparable.
    """
    now = now or time.time()
    num = den = 0.0
    used = 0
    for r in rows:
        age_h = (now - r["published_ts"]) / 3600.0
        if age_h > window_hours:
            continue
        w = (r["confidence"] or 0.0) * (r["source_weight"] or config.DEFAULT_SOURCE_WEIGHT) * decay(age_h)
        if w <= 0:
            continue
        num += (r["direction"] or 0) * w
        den += w
        used += 1
    return (num / den if den else 0.0), used


def label(score):
    if score >= 0.4:
        return "strongly bullish"
    if score >= 0.15:
        return "mildly bullish"
    if score <= -0.4:
        return "strongly bearish"
    if score <= -0.15:
        return "mildly bearish"
    return "neutral"


def build_signal(conn, now=None, headline_limit=20):
    now = now or time.time()
    longest = max(config.WINDOWS_HOURS)
    rows = db.scored_since(conn, now - longest * 3600)
    windows = {}
    for h in config.WINDOWS_HOURS:
        s, n = window_score(rows, h, now)
        windows[f"{h}h"] = {"score": round(s, 3), "label": label(s), "articles": n}
    headlines = [
        {
            "title": r["title"], "source": r["source"], "url": r["url"],
            "published_ts": r["published_ts"], "direction": r["direction"],
            "confidence": r["confidence"], "driver": r["driver"], "reason": r["reason"],
            "scorer": r["scorer"],
        }
        for r in rows[:headline_limit]
    ]
    return {
        "pair": "GBP/USD",
        "generated_ts": now,
        "scale": "-1 = strongly bearish for GBP/USD, +1 = strongly bullish",
        "windows": windows,
        "headlines": headlines,
        "disclaimer": config.PAIR_DISCLAIMER,
    }
