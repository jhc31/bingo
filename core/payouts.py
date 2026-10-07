"""Bingo Bingo prize tables (NTD per 25-NTD unit at 1x multiplier) and promotions.

Prizes scale linearly with the multiplier (1x-50x), so return rates are multiplier
independent; only the money at risk changes.
"""
from datetime import date
from math import comb

UNIT = 25  # NTD per ticket at 1x

# Regular prize tables, star game -> {matched numbers: prize}.
# Matches the official starDetails returned by the Taiwan Lottery API.
BASE = {
    1: {1: 50},
    2: {2: 75, 1: 25},
    3: {3: 500, 2: 50},
    4: {4: 1000, 3: 100, 2: 25},
    5: {5: 7500, 4: 500, 3: 50},
    6: {6: 25000, 5: 1000, 4: 200, 3: 25},
    7: {7: 80000, 6: 3000, 5: 300, 4: 50, 3: 25},
    8: {8: 500000, 7: 20000, 6: 1000, 5: 200, 4: 25, 0: 25},
    9: {9: 1000000, 8: 100000, 7: 3000, 6: 500, 5: 100, 4: 25, 0: 25},
    10: {10: 5000000, 9: 250000, 8: 25000, 7: 2500, 6: 250, 5: 25, 0: 25},
}
SUPER_NUMBER_BASE = 1200   # 超級獎號 single play, 48x
BIG_SMALL_BASE = 150       # 猜大小 / 猜單雙, 6x
# 猜大小 wins when >= 13 of the 20 numbers are 41-80 (大) or 1-40 (小); 單雙 is symmetric.
BIG_SMALL_P = sum(comb(40, i) * comb(40, 20 - i) for i in range(13, 21)) / comb(80, 20)

# Promotions: tiers listed in `stars` replace the base prize; unlisted tiers stay unchanged.
PROMOTIONS = [
    {
        "name": "2026 中秋 基本玩法快閃加碼",
        "start": date(2026, 10, 8),
        "end": date(2026, 10, 9),
        "stars": {
            6: {6: 50000, 5: 1200},
            5: {5: 10000, 4: 600},
            4: {4: 2000, 3: 150},
            3: {3: 1000},
            2: {2: 150},
            1: {1: 75},
        },
    },
    {
        "name": "2026 中秋 超級獎號/猜大小/猜單雙 獎金加碼",
        "start": date(2026, 9, 25),
        "end": date(2026, 10, 11),
        "super_number": 1500,
        "big_small": 175,
    },
]


def parse_star_details(dividends: list[int]) -> dict:
    """Official API starDetails (10星 first, tiers in BASE order) -> {stars: prize table}."""
    tables, i = {}, 0
    for k in range(10, 0, -1):
        tiers = list(BASE[k])
        tables[k] = dict(zip(tiers, dividends[i:i + len(tiers)]))
        i += len(tiers)
    return tables


def star_table(stars: int, on: date | None = None, promo_name: str | None = None,
               promotions: list | None = None) -> dict:
    """Prize table for a star game on a given date, or with a named promotion forced on.
    `promotions` defaults to the built-in PROMOTIONS list (the web app passes its DB rows)."""
    table = dict(BASE[stars])
    for p in PROMOTIONS if promotions is None else promotions:
        active = (promo_name == p["name"]) or (on is not None and p["start"] <= on <= p["end"])
        if active and stars in p.get("stars", {}):
            table.update(p["stars"][stars])
    return table


def hit_probability(stars: int, hits: int) -> float:
    """P(exactly `hits` of the chosen `stars` numbers are among the 20 drawn from 80)."""
    return comb(20, hits) * comb(60, stars - hits) / comb(80, stars)


def theoretical(stars: int, table: dict) -> dict:
    """Exact expectation and variance of one 1x ticket under a fair draw."""
    ev = sum(hit_probability(stars, m) * table.get(m, 0) for m in range(stars + 1))
    ev2 = sum(hit_probability(stars, m) * table.get(m, 0) ** 2 for m in range(stars + 1))
    return {
        "return_rate": ev / UNIT,
        "payout_mean": ev,
        "payout_var": ev2 - ev * ev,
        "p_any_prize": sum(hit_probability(stars, m) for m in table),
        "p_profit": sum(hit_probability(stars, m) for m, v in table.items() if v > UNIT),
    }
