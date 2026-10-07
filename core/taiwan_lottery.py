"""Official Taiwan Lottery Bingo Bingo API client and draw schedule.

Schedule: 203 draws a day, 07:05 ~ 23:55 Asia/Taipei, every 5 minutes. Draw terms are
<ROC year><6-digit running number>, e.g. 115056637, restarting at 000001 each year.
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

API = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult"
TZ = ZoneInfo("Asia/Taipei")
DRAWS_PER_DAY = 203
FIRST_DRAW = time(7, 5)
INTERVAL = timedelta(minutes=5)


def fetch_day_raw(d: date, timeout: int = 30) -> list[dict]:
    """All draws published so far for date `d`, as returned by the API."""
    r = requests.get(API, params={"openDate": d.isoformat(), "pageNum": 1, "pageSize": 300}, timeout=timeout)
    r.raise_for_status()
    return r.json()["content"]["bingoQueryResult"] or []


def parse_draws(raw: list[dict], d: date) -> list[dict]:
    """Normalise one day's API rows, sorted by term, with draw_index 1..203 within the day."""
    out = []
    for x in sorted(raw, key=lambda x: x["drawTerm"]):
        nums = sorted(int(n) for n in x["bigShowOrder"])
        if len(nums) != 20:
            continue
        out.append({
            "draw_term": int(x["drawTerm"]),
            "draw_date": d,
            "numbers": nums,
            "open_order": [int(n) for n in x["openShowOrder"]],
            "super_number": int(x["bullEyeTop"]),
            "dividends": [s["dividend"] for s in x["starDetails"]] if x.get("starDetails") else None,
        })
    for i, row in enumerate(out, start=1):
        row["draw_index"] = i
    return out


def fetch_day(d: date) -> list[dict]:
    return parse_draws(fetch_day_raw(d), d)


def today() -> date:
    return datetime.now(TZ).date()


def draw_time(d: date, index: int) -> datetime:
    """Scheduled time of the index-th (1-based) draw on date d."""
    return datetime.combine(d, FIRST_DRAW, tzinfo=TZ) + INTERVAL * (index - 1)


def roc_year(d: date) -> int:
    return d.year - 1911


def next_target(last_term: int, last_date: date, last_index: int, now: datetime) -> dict:
    """The first scheduled draw strictly after `now`, with its term number derived from the
    last known draw. Gaps (draws held but not yet ingested) are counted along the way."""
    d, idx, term = last_date, last_index, last_term
    while True:
        if idx < DRAWS_PER_DAY:
            idx += 1
        else:
            d, idx = d + timedelta(days=1), 1
        term = roc_year(d) * 1_000_000 + 1 if (idx == 1 and roc_year(d) != roc_year(last_date)
                                                and d.month == 1 and d.day == 1) else term + 1
        t = draw_time(d, idx)
        if t > now:
            return {"term": term, "date": d, "index": idx, "time": t}
