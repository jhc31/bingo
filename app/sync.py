"""Sync job, run every 5 minutes (Render Cron Job or POST /api/cron/sync):

1. pull newly published draws from the official API,
2. score predictions whose draw is now known,
3. rank numbers for the next scheduled draw with every strategy.

Predictions are only stored before their draw time, so the live record on the site is a
true out-of-sample test.

Usage: python -m app.sync
"""
import logging
import threading
import time
from datetime import datetime, timedelta

from app import config, db
from core import taiwan_lottery as tl
from core.strategies import predict_next

log = logging.getLogger("sync")
_lock = threading.Lock()


def ingest(conn) -> int:
    """Fetch every day from the last stored draw's date through today (Taipei)."""
    last = db.latest_draw(conn)
    start = last["draw_date"] if last else tl.today() - timedelta(days=2)
    d, added = start, 0
    while d <= tl.today():
        added += db.upsert_draws(conn, tl.fetch_day(d))
        d += timedelta(days=1)
    conn.commit()
    return added


def predict(conn) -> dict | None:
    last = db.latest_draw(conn)
    if last is None:
        return None
    target = tl.next_target(last["draw_term"], last["draw_date"], last["draw_index"], datetime.now(tl.TZ))
    existing = db.predictions_for(conn, target["term"])
    if existing and all((p["based_on_term"] or 0) >= last["draw_term"] for p in existing):
        return {"term": target["term"], "created": 0}
    history = db.draw_history(conn, config.HISTORY_FOR_PREDICTION)
    if len(history) < 2000:
        log.warning("only %d draws stored; seed history first (python -m scripts.seed_history)", len(history))
        return None
    ranked = predict_next(history, seed=target["term"], logit_train_len=config.LOGIT_TRAIN_LEN)
    # Re-check the clock: a prediction finished after the draw must not count as live.
    if datetime.now(tl.TZ) >= target["time"]:
        return {"term": target["term"], "created": 0, "late": True}
    n = db.upsert_predictions(conn, target["term"], target["time"], last["draw_term"],
                              {k: v for k, (_, v) in ranked.items()})
    conn.commit()
    return {"term": target["term"], "time": target["time"].isoformat(), "created": n}


def run() -> dict:
    t0 = time.time()
    with db.connection() as conn:
        added = ingest(conn)
        settled = db.settle_predictions(conn)
        conn.commit()
        predicted = predict(conn)
    return {"new_draws": added, "settled": settled, "prediction": predicted, "seconds": round(time.time() - t0, 1)}


def run_exclusive() -> dict | None:
    """run() unless another sync in this process is already running (returns None then)."""
    if not _lock.acquire(blocking=False):
        return None
    try:
        return run()
    finally:
        _lock.release()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run())
    db.close()
