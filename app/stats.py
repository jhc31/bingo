"""Payout tables in force and live (forward) strategy statistics."""
import math
from collections import defaultdict
from datetime import date

from core.payouts import BASE, BIG_SMALL_BASE, BIG_SMALL_P, SUPER_NUMBER_BASE, UNIT, star_table, theoretical


def payout_overview(on: date, promotions: list[dict], stars=range(1, 11)) -> dict:
    """Regular vs. in-force prize tables and exact return rates for each star game on `on`."""
    games = {}
    for k in stars:
        current = star_table(k, on=on, promotions=promotions)
        games[k] = {
            "base_table": BASE[k],
            "table": current,
            "boosted": current != BASE[k],
            "base": theoretical(k, BASE[k]),
            "current": theoretical(k, current),
        }
    active = [p for p in promotions if p["start"] <= on <= p["end"]]
    super_prize = max([p["super_number"] for p in active if p.get("super_number")] or [SUPER_NUMBER_BASE])
    big_small = max([p["big_small"] for p in active if p.get("big_small")] or [BIG_SMALL_BASE])
    return {
        "date": on.isoformat(),
        "games": games,
        "super_number": {"prize": super_prize, "return_rate": super_prize / 80 / UNIT},
        "big_small": {"prize": big_small, "p_win": BIG_SMALL_P, "return_rate": big_small * BIG_SMALL_P / UNIT},
        "active_promotions": [promo_json(p) for p in active],
        "upcoming_promotions": [promo_json(p) for p in promotions if p["start"] > on],
    }


def promo_json(p: dict) -> dict:
    return {"name": p["name"], "start": p["start"].isoformat(), "end": p["end"].isoformat(),
            "stars": p["stars"], "super_number": p.get("super_number"), "big_small": p.get("big_small")}


def live_stats(rows: list[dict], promotions: list[dict], descriptions: dict[str, str]) -> dict:
    """Aggregate settled live predictions into per-strategy, per-game statistics.

    rows: (strategy, k, h, draw_date, n) counts from db.live_hit_counts.
    z_hits compares the average hit count with the exact hypergeometric expectation.
    """
    acc = defaultdict(lambda: {"n": 0, "hits": 0, "paid": 0.0, "paid_base": 0.0, "expected_paid": 0.0,
                               "dist": defaultdict(int)})
    tables = {}
    for r in rows:
        k, h, n = r["k"], r["h"], r["n"]
        key = (r["strategy"], k)
        tkey = (k, r["draw_date"])
        if tkey not in tables:
            t = star_table(k, on=r["draw_date"], promotions=promotions)
            tables[tkey] = (t, theoretical(k, t)["payout_mean"])
        table, exp_pay = tables[tkey]
        a = acc[key]
        a["n"] += n
        a["hits"] += h * n
        a["paid"] += table.get(h, 0) * n
        a["paid_base"] += BASE[k].get(h, 0) * n
        a["expected_paid"] += exp_pay * n
        a["dist"][h] += n

    out = defaultdict(dict)
    for (strategy, k), a in acc.items():
        n = a["n"]
        p = 0.25
        var = k * p * (1 - p) * (80 - k) / 79
        avg = a["hits"] / n
        out[strategy][k] = {
            "n": n,
            "avg_hits": avg,
            "expected_hits": k * p,
            "z_hits": (avg - k * p) / math.sqrt(var / n),
            "return_rate": a["paid"] / (n * UNIT),
            "return_rate_base": a["paid_base"] / (n * UNIT),
            "theoretical_return_rate": a["expected_paid"] / (n * UNIT),
            "profit_1x": a["paid"] - n * UNIT,
            "distribution": [a["dist"].get(i, 0) for i in range(k + 1)],
        }
    return {s: {"description": descriptions.get(s, s), "games": g} for s, g in out.items()}
