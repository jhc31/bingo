"""Download Bingo Bingo draw history from the official Taiwan Lottery API.

Each day's response is cached under data/raw/YYYY-MM-DD.json so reruns only fetch
missing days. The merged result is written to data/draws.csv.

Usage: python backtest/fetch_draws.py [START_DATE] [END_DATE]
"""
import csv
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

import requests

API = "https://api.taiwanlottery.com/TLCAPIWeB/Lottery/BingoResult"
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_CSV = ROOT / "data" / "draws.csv"
OUT_STARS = ROOT / "data" / "star_details.jsonl"


def fetch_day(d: date) -> list:
    cache = RAW_DIR / f"{d.isoformat()}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    for attempt in range(4):
        try:
            r = requests.get(API, params={"openDate": d.isoformat(), "pageNum": 1, "pageSize": 300}, timeout=30)
            r.raise_for_status()
            rows = r.json()["content"]["bingoQueryResult"] or []
            # Only cache complete past days so a partially drawn day is refetched later.
            if d < date.today():
                cache.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            return rows
        except Exception as e:  # noqa: BLE001 - retry any network/JSON error
            if attempt == 3:
                print(f"{d}: failed ({e})", file=sys.stderr)
                return []
            time.sleep(2 * (attempt + 1))


def main():
    start = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2023, 11, 1)
    end = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else date.today() - timedelta(days=1)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch_day, days))

    draws, stars = [], []
    for d, rows in zip(days, results):
        for x in rows:
            nums = sorted(int(n) for n in x["bigShowOrder"])
            if len(nums) != 20:
                continue
            draws.append({
                "draw_term": x["drawTerm"],
                "draw_date": d.isoformat(),
                "numbers": " ".join(f"{n:02d}" for n in nums),
                "open_order": " ".join(x["openShowOrder"]),
                "super_number": int(x["bullEyeTop"]),
            })
            if x.get("starDetails"):
                stars.append({"draw_term": x["drawTerm"], "draw_date": d.isoformat(),
                              "dividends": [s["dividend"] for s in x["starDetails"]]})

    draws.sort(key=lambda r: r["draw_term"])
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(draws[0].keys()))
        w.writeheader()
        w.writerows(draws)
    with OUT_STARS.open("w", encoding="utf-8") as f:
        for s in sorted(stars, key=lambda r: r["draw_term"]):
            f.write(json.dumps(s) + "\n")

    days_with_data = sum(1 for r in results if r)
    print(f"{len(draws)} draws over {days_with_data} days ({draws[0]['draw_date']} ~ {draws[-1]['draw_date']}); "
          f"{len(stars)} draws carry official prize tables")


if __name__ == "__main__":
    main()
