"""Upload backtest/output/results.json (from `python -m backtest.run_backtest`) so the site
can show it.

Usage: python -m scripts.upload_backtest
"""
import json

from app import config, db


def main():
    payload = json.loads((config.ROOT / "backtest" / "output" / "results.json").read_text(encoding="utf-8"))
    with db.connection() as conn:
        db.insert_backtest(conn, "strategies", payload)
        conn.commit()
    print(f"uploaded backtest generated {payload['meta']['generated']} "
          f"({payload['meta']['draws_evaluated']:,} draws evaluated)")
    db.close()


if __name__ == "__main__":
    main()
