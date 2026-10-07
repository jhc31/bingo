"""3星 multiplier backtest: fixed 1x/2x/3x/4x vs. a 2-4x progression, on real draw history.

Number choice does not matter (see report.md: no strategy beats random), so tickets are
random picks. Three payout scenarios: regular prizes, the 中秋快閃加碼 table applied to all
history (what-if), and the 28 historical days when that exact promo table was paid.

Usage: python -m backtest.multiplier_3star
Output: backtest/output/report_3star_multiplier.md
"""
import csv
from collections import defaultdict
from pathlib import Path

import numpy as np

from core.payouts import BASE, PROMOTIONS, UNIT, star_table, theoretical
from backtest.run_backtest import WARMUP, actual_tables, payout_vector
from core.strategies import draw_matrix

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "output"
K = 3
BANKROLL = 10000
HOUR = 12          # draws per hour (one every 5 minutes)
PROMO = PROMOTIONS[0]["name"]

SCHEMES = {
    "固定1倍(參考)": ("fixed", 1),
    "固定2倍": ("fixed", 2),
    "固定3倍": ("fixed", 3),
    "固定4倍": ("fixed", 4),
    "累進2→3→4倍": ("progression", None),
}


def multipliers(prize_1x: np.ndarray, scheme) -> np.ndarray:
    """Multiplier used on each draw. Progression: start 2x, +1 after a draw with no prize
    (max 4x), back to 2x after any prize (every 3星 prize exceeds the stake)."""
    kind, m = scheme
    if kind == "fixed":
        return np.full(len(prize_1x), m, dtype=np.int64)
    out = np.empty(len(prize_1x), dtype=np.int64)
    m = 2
    for i, p in enumerate(prize_1x):
        out[i] = m
        m = 2 if p > 0 else min(m + 1, 4)
    return out


def play(prize_1x: np.ndarray, scheme, bankroll=None):
    """Play the draws in order. Returns (net profit, draws played, busted?)."""
    mult = multipliers(prize_1x, scheme)
    net = mult * (prize_1x - UNIT)
    if bankroll is None:
        return float(net.sum()), len(net), False
    bank_before = bankroll + np.concatenate([[0], np.cumsum(net)[:-1]])
    bust = np.nonzero(bank_before < mult * UNIT)[0]
    if len(bust):
        n = bust[0]
        return float(net[:n].sum()), int(n), True
    return float(net.sum()), len(net), False


def summarize(profits) -> str:
    a = np.array(profits)
    return (f"{(a > 0).mean() * 100:.1f}% | {a.mean():,.0f} | {np.median(a):,.0f} | "
            f"{np.percentile(a, 5):,.0f} ~ {np.percentile(a, 95):,.0f}")


def main():
    with (ROOT / "data" / "draws.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    D = draw_matrix([[int(x) for x in r["numbers"].split()] for r in rows])[WARMUP:].astype(bool)
    days = np.array([r["draw_date"] for r in rows])[WARMUP:]
    n = len(D)

    rng = np.random.default_rng(2026)
    picks = np.argsort(rng.random((n, 80)), axis=1)[:, :K]
    hits = D[np.arange(n)[:, None], picks].sum(axis=1)

    actual = actual_tables(rows, K)[WARMUP:]
    promo_mask = actual[:, K] > BASE[K][K]
    scenarios = {
        "平常獎金": payout_vector(BASE[K], K)[hits],
        "快閃加碼（套用全部歷史）": payout_vector(star_table(K, promo_name=PROMO), K)[hits],
        f"歷史真實加碼日（{len(set(days[promo_mask]))} 天）": np.where(promo_mask, actual[np.arange(n), hits], np.nan),
    }

    day_index = defaultdict(list)
    for i, d in enumerate(days):
        day_index[d].append(i)
    day_starts = [ix[0] for ix in day_index.values()]

    L = ["# 3星 倍數回測（2～4倍）", "",
         f"- 回測期間 {days[0]} ~ {days[-1]}，共 {n:,} 期；每期 1 注 3星，隨機選號（選號策略不影響結果，見 report.md）",
         f"- 累進法：從 2 倍開始，沒中獎就 +1 倍（最多 4 倍），中獎就回到 2 倍",
         f"- 有本金限制的情境，起始資金皆為 {BANKROLL:,} 元，下一注付不出來就算爆倉", ""]

    for label, prize in scenarios.items():
        valid = ~np.isnan(prize)
        th = theoretical(K, star_table(K, promo_name=PROMO) if "加碼" in label else BASE[K])
        L += [f"## {label}", "",
              f"理論回收率 {th['return_rate'] * 100:.2f}%，實際回收率 "
              f"{prize[valid].mean() / UNIT * 100:.2f}%（倍數不影響回收率）。", "",
              "### 長期：所有期數都買（不設本金上限）", "",
              "| 下注方式 | 總投注 | 總獎金 | 回收率 | 總損益 | 平均每期損益 |", "|---|---|---|---|---|---|"]
        p = prize[valid]
        for name, scheme in SCHEMES.items():
            mult = multipliers(p, scheme)
            stake, paid = (mult * UNIT).sum(), (mult * p).sum()
            L.append(f"| {name} | {stake:,.0f} | {paid:,.0f} | {paid / stake * 100:.2f}% | "
                     f"{paid - stake:,.0f} | {(paid - stake) / len(p):,.1f} |")

        L += ["", "### 玩 1 小時（連續 12 期）", "",
              "| 下注方式 | 獲利機率 | 平均損益 | 中位數 | 5%～95% 範圍 |", "|---|---|---|---|---|"]
        hours = [prize[i:i + HOUR] for i in range(0, n - HOUR, HOUR)]
        hours = [h for h in hours if not np.isnan(h).any()]
        for name, scheme in SCHEMES.items():
            L.append(f"| {name} | {summarize([play(h, scheme)[0] for h in hours])} |")

        L += ["", f"### 玩一整天（203 期），本金 {BANKROLL:,}", "",
              "| 下注方式 | 獲利機率 | 平均損益 | 中位數 | 5%～95% 範圍 | 爆倉率 |", "|---|---|---|---|---|---|"]
        full_days = [prize[ix] for ix in day_index.values() if not np.isnan(prize[ix]).any() and len(ix) >= 150]
        for name, scheme in SCHEMES.items():
            res = [play(dp, scheme, BANKROLL) for dp in full_days]
            L.append(f"| {name} | {summarize([r[0] for r in res])} | "
                     f"{np.mean([r[2] for r in res]) * 100:.1f}% |")

        if "真實" not in label:
            L += ["", f"### 本金 {BANKROLL:,} 能撐多久（從每天第一期開始一路買到爆倉）", "",
                  "| 下注方式 | 撐過1天機率 | 撐過3天機率 | 撐過7天機率 | 爆倉前中位數期數 |", "|---|---|---|---|---|"]
            for name, scheme in SCHEMES.items():
                lasted = np.array([play(prize[s:s + 30 * 203], scheme, BANKROLL)[1] for s in day_starts[:-7]])
                L.append(f"| {name} | {(lasted >= 203).mean() * 100:.1f}% | {(lasted >= 609).mean() * 100:.1f}% | "
                         f"{(lasted >= 1421).mean() * 100:.1f}% | {np.median(lasted):,.0f} 期 |")
        L.append("")

    OUT.mkdir(exist_ok=True)
    out = OUT / "report_3star_multiplier.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
