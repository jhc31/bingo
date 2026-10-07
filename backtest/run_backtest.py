"""Walk-forward backtest of number-picking strategies for Bingo Bingo 3-6 星.

For every draw t (after a warm-up), each strategy ranks the 80 numbers using only draws
before t, buys the top-k as a k星 ticket (1x, 25 NTD), and is scored against draw t.

Null hypothesis: draws are fair and independent, so any strategy's hit count per draw
is Hypergeometric(80, 20, k). Strategies are tested against that exact distribution
(z-test, Bonferroni-corrected), not just eyeballed against a single random run.

Usage: python -m backtest.run_backtest
Outputs: backtest/output/results.json and backtest/output/report.md
"""
import csv
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from core.payouts import BASE, PROMOTIONS, UNIT, hit_probability, parse_star_details, star_table, theoretical
from core.strategies import build_strategies, draw_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
GAMES = (3, 4, 5, 6)
WARMUP = 20000           # draws reserved for history / first model fit
BANKROLL = 10000         # NTD, for the per-day money-management simulation
MARTINGALE_CAP = 50      # max multiplier allowed by Taiwan Lottery
PROMO = PROMOTIONS[0]["name"]


def p_two_sided(z: float) -> float:
    return math.erfc(abs(z) / math.sqrt(2))


def load_draws():
    with (ROOT / "data" / "draws.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    nums = [[int(x) for x in r["numbers"].split()] for r in rows]
    dates = np.array([r["draw_date"] for r in rows])
    return draw_matrix(nums), dates, rows


def actual_tables(rows, k: int) -> np.ndarray:
    """(T, k+1) prize per hit count as officially paid on each draw. Draws before the API
    started publishing prize tables (2024-10) fall back to the base table."""
    official = {}
    with (ROOT / "data" / "star_details.jsonl").open(encoding="utf-8") as f:
        for line in f:
            s = json.loads(line)
            official[s["draw_term"]] = parse_star_details(s["dividends"])[k]
    base = payout_vector(BASE[k], k)
    return np.array([payout_vector(official[int(r["draw_term"])], k) if int(r["draw_term"]) in official
                     else base for r in rows])


def payout_vector(table: dict, k: int) -> np.ndarray:
    return np.array([table.get(m, 0) for m in range(k + 1)], dtype=np.float64)


def evaluate(hits: np.ndarray, k: int, n_tests: int, actual: np.ndarray) -> dict:
    n = len(hits)
    p = 0.25
    exp_mean = k * p
    hyp_var = k * p * (1 - p) * (80 - k) / 79
    z_hits = (hits.mean() - exp_mean) / math.sqrt(hyp_var / n)
    half = n // 2
    z_half = [(h.mean() - exp_mean) / math.sqrt(hyp_var / len(h)) for h in (hits[:half], hits[half:])]

    res = {
        "n_draws": n,
        "avg_hits": hits.mean(),
        "expected_hits": exp_mean,
        "hit_distribution": np.bincount(hits, minlength=k + 1).tolist(),
        "z_hits": z_hits,
        "p_hits": p_two_sided(z_hits),
        "significant": p_two_sided(z_hits) < 0.05 / n_tests,
        "z_first_half": z_half[0],
        "z_second_half": z_half[1],
    }
    for label, table in (("base", BASE[k]), ("promo", star_table(k, promo_name=PROMO))):
        pay = payout_vector(table, k)[hits]
        th = theoretical(k, table)
        z_ret = (pay.mean() - th["payout_mean"]) / math.sqrt(th["payout_var"] / n)
        profit = np.cumsum(pay - UNIT)
        res[label] = {
            "return_rate": pay.mean() / UNIT,
            "theoretical_return_rate": th["return_rate"],
            "z_return": z_ret,
            "p_any_prize": float((pay > 0).mean()),
            "p_profit": float((pay > UNIT).mean()),
            "total_profit_1x": float(profit[-1]),
            "max_drawdown_1x": float((np.maximum.accumulate(profit) - profit).max()),
        }
    # As actually paid, including historical promotion days.
    probs = np.array([hit_probability(k, m) for m in range(k + 1)])
    pay = actual[np.arange(n), hits]
    th_mean = actual @ probs
    th_var = (actual ** 2) @ probs - th_mean ** 2
    res["actual"] = {
        "return_rate": pay.mean() / UNIT,
        "theoretical_return_rate": th_mean.mean() / UNIT,
        "z_return": (pay.sum() - th_mean.sum()) / math.sqrt(th_var.sum()),
        "total_profit_1x": float((pay - UNIT).sum()),
    }
    no_prize = (payout_vector(BASE[k], k)[hits] == 0).astype(np.int8)
    res["longest_no_prize_streak"] = longest_run(no_prize)
    return res


def longest_run(x: np.ndarray) -> int:
    best = cur = 0
    for v in x:
        cur = cur + 1 if v else 0
        best = max(best, cur)
    return best


def daily_sessions(hits: np.ndarray, days: np.ndarray, k: int, table: dict, only_days=None) -> dict:
    """Play every draw of a day at 1x (flat) vs. martingale (double after a losing draw,
    reset after a winning one, capped at 50x), starting each day with BANKROLL."""
    pay = payout_vector(table, k)[hits]
    flat, mart, ruined = [], [], 0
    by_day = defaultdict(list)
    for d, p in zip(days, pay):
        if only_days is None or d in only_days:
            by_day[d].append(p)
    for prizes in by_day.values():
        if len(prizes) < 150:   # skip partial days
            continue
        flat.append(sum(prizes) - UNIT * len(prizes))
        bank, mult = BANKROLL, 1
        for p in prizes:
            stake = UNIT * mult
            if stake > bank:
                ruined += 1
                break
            bank += p * mult - stake
            mult = 1 if p > UNIT else min(mult * 2, MARTINGALE_CAP)
        mart.append(bank - BANKROLL)
    flat, mart = np.array(flat), np.array(mart)
    summ = lambda a: {  # noqa: E731
        "p_day_profit": float((a > 0).mean()),
        "mean": float(a.mean()),
        "median": float(np.median(a)),
        "p5": float(np.percentile(a, 5)),
        "p95": float(np.percentile(a, 95)),
    }
    return {"days": len(flat), "flat_1x": summ(flat),
            "martingale": {**summ(mart), "p_bust": ruined / len(mart)}}


def main():
    OUT.mkdir(exist_ok=True)
    D, dates, rows = load_draws()
    T = len(D)
    print(f"{T} draws, {dates[0]} ~ {dates[-1]}; evaluating draws {WARMUP}..{T - 1}")

    strategies = build_strategies(D, WARMUP)
    n_tests = len(strategies) * len(GAMES)
    drawn = D[WARMUP:].astype(bool)
    eval_days = dates[WARMUP:]
    rows_idx = np.arange(T - WARMUP)[:, None]

    results = {"meta": {
        "draws_total": T, "draws_evaluated": T - WARMUP,
        "first_eval_date": str(eval_days[0]), "last_eval_date": str(eval_days[-1]),
        "bonferroni_alpha": 0.05 / n_tests, "promotion": PROMO,
        "generated": date.today().isoformat(),
    }, "theoretical": {}, "strategies": {}, "daily_sessions": {}}

    for k in range(1, 11):
        results["theoretical"][k] = {
            "base": theoretical(k, BASE[k]),
            "promo": theoretical(k, star_table(k, promo_name=PROMO)),
        }

    actual_by_k = {k: actual_tables(rows, k)[WARMUP:] for k in GAMES}
    promo_days = {str(d) for d, is_promo in zip(eval_days, actual_by_k[6][:, 6] > BASE[6][6]) if is_promo}
    results["meta"]["historical_promo_days"] = sorted(promo_days)

    random_hits = {}
    for name, (desc, S) in strategies.items():
        top = np.argsort(-S[WARMUP:], axis=1)[:, :max(GAMES)]
        results["strategies"][name] = {"description": desc, "games": {}}
        for k in GAMES:
            hits = drawn[rows_idx, top[:, :k]].sum(axis=1)
            results["strategies"][name]["games"][k] = evaluate(hits, k, n_tests, actual_by_k[k])
            if name == "random":
                random_hits[k] = hits
        print(f"  done: {name}")

    for k in GAMES:
        results["daily_sessions"][k] = {
            "base": daily_sessions(random_hits[k], eval_days, k, BASE[k]),
            "promo": daily_sessions(random_hits[k], eval_days, k, star_table(k, promo_name=PROMO)),
            "promo_days": daily_sessions(random_hits[k], eval_days, k, star_table(k, promo_name=PROMO),
                                         only_days=promo_days),
        }

    (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1, default=float),
                                      encoding="utf-8")
    (OUT / "report.md").write_text(render_report(results), encoding="utf-8")
    print(f"wrote {OUT / 'report.md'}")


def pct(x):
    return f"{x * 100:.2f}%"


def render_report(r: dict) -> str:
    m = r["meta"]
    L = [
        "# Bingo Bingo 3–6星 策略回測報告",
        "",
        f"- 資料：台灣彩券官方 API，共 {m['draws_total']:,} 期；回測期間 {m['first_eval_date']} ~ "
        f"{m['last_eval_date']}，共 {m['draws_evaluated']:,} 期（前 {WARMUP:,} 期只作為歷史資料）",
        "- 方法：walk-forward，每期只用該期之前的資料選號，每期買 1 注 1 倍（25 元）",
        f"- 顯著性：與公平開獎的超幾何分佈比較，Bonferroni 校正後門檻 p < {m['bonferroni_alpha']:.5f}",
        f"- 加碼情境：「{m['promotion']}」的獎金表套用到全部歷史期數（what-if）",
        f"- 實際：依官方每期公布的獎金表計算，含歷史上 {len(m['historical_promo_days'])} 天快閃加碼日"
        f"（{', '.join(m['historical_promo_days'][:1])} 等，加碼表與本次中秋完全相同）",
        "",
        "## 1. 理論值（公平開獎下，任何選號方式都一樣）",
        "",
        "| 玩法 | 中獎率 | 獲利率(獎金>本金) | 回收率 平常 | 回收率 快閃加碼 |",
        "|---|---|---|---|---|",
    ]
    for k in GAMES:
        b, p = r["theoretical"][k]["base"], r["theoretical"][k]["promo"]
        L.append(f"| {k}星 | {pct(b['p_any_prize'])} | {pct(b['p_profit'])} | {pct(b['return_rate'])} | "
                 f"{pct(p['return_rate'])} |")

    for k in GAMES:
        L += ["", f"## 2.{k - 2} {k}星 各策略回測", "",
              f"期望平均命中 {k * 0.25:.2f} 顆。z 為命中數相對公平開獎的標準分數（|z|>2 才稍有意義，"
              f"還需通過 Bonferroni 門檻）。",
              "",
              "| 策略 | 平均命中 | z(命中) | 前半/後半 z | 中獎率 | 獲利率 | 回收率 平常 | 回收率 加碼 | 回收率 實際 | 1倍累計損益 | 最大回撤 | 最長槓龜 |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        rows = sorted(r["strategies"].items(), key=lambda kv: -kv[1]["games"][k]["base"]["return_rate"])
        for name, s in rows:
            g = s["games"][k]
            sig = " ✱" if g["significant"] else ""
            L.append(
                f"| {s['description']} | {g['avg_hits']:.4f} | {g['z_hits']:+.2f}{sig} | "
                f"{g['z_first_half']:+.2f} / {g['z_second_half']:+.2f} | {pct(g['base']['p_any_prize'])} | "
                f"{pct(g['base']['p_profit'])} | {pct(g['base']['return_rate'])} | {pct(g['promo']['return_rate'])} | "
                f"{pct(g['actual']['return_rate'])} | {g['base']['total_profit_1x']:,.0f} | {g['base']['max_drawdown_1x']:,.0f} | "
                f"{g['longest_no_prize_streak']} 期 |")

    L += ["", "## 3. 每天每期都買（一天約 203 期）的單日結果", "",
          f"每天起始資金 {BANKROLL:,} 元。固定 1 倍 vs 馬丁格爾（沒賺就倍數加倍，賺了回 1 倍，上限 50 倍）。", "",
          "| 玩法 | 獎金 | 固定1倍 單日獲利機率 | 固定1倍 單日平均 | 固定1倍 5%~95% | 馬丁 單日獲利機率 | 馬丁 單日平均 | 馬丁 爆倉率 |",
          "|---|---|---|---|---|---|---|---|"]
    for k in GAMES:
        for label, name in (("base", "平常"), ("promo", "快閃加碼(套全部歷史)"),
                            ("promo_days", f"歷史真實加碼日({r['daily_sessions'][k]['promo_days']['days']}天)")):
            d = r["daily_sessions"][k][label]
            f, mg = d["flat_1x"], d["martingale"]
            L.append(f"| {k}星 | {name} | {pct(f['p_day_profit'])} | {f['mean']:,.0f} | "
                     f"{f['p5']:,.0f} ~ {f['p95']:,.0f} | {pct(mg['p_day_profit'])} | {mg['mean']:,.0f} | "
                     f"{pct(mg['p_bust'])} |")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    main()
