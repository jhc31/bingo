"""Load the draw history in data/draws.csv into the database (skips terms already stored).

Usage: python -m scripts.seed_history
Run `python -m backtest.fetch_draws` first if data/draws.csv does not exist.
"""
import csv
from collections import defaultdict

from app import config, db

BATCH = 5000


def load_csv() -> list[dict]:
    path = config.ROOT / "data" / "draws.csv"
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    index = defaultdict(int)
    out = []
    for r in sorted(rows, key=lambda r: int(r["draw_term"])):
        index[r["draw_date"]] += 1
        out.append({
            "draw_term": int(r["draw_term"]),
            "draw_date": r["draw_date"],
            "draw_index": index[r["draw_date"]],
            "numbers": [int(x) for x in r["numbers"].split()],
            "open_order": [int(x) for x in r["open_order"].split()],
            "super_number": int(r["super_number"]),
        })
    return out


def main():
    rows = load_csv()
    with db.connection() as conn:
        before = db.draw_count(conn)
        for i in range(0, len(rows), BATCH):
            db.upsert_draws(conn, rows[i:i + BATCH])
            conn.commit()
            print(f"  {min(i + BATCH, len(rows)):,}/{len(rows):,}", flush=True)
        after = db.draw_count(conn)
    print(f"draws in database: {before:,} -> {after:,}")
    db.close()


if __name__ == "__main__":
    main()
