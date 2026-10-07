"""Bingo Bingo 策略實驗室 — FastAPI app (API + static frontend).

Run locally: uvicorn app.main:app --reload
"""
import hmac
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from app import config, db, stats, sync
from app.scheduler import scheduler
from core import taiwan_lottery as tl
from core.payouts import star_table
from core.strategies import DESCRIPTIONS


@asynccontextmanager
async def lifespan(_app):
    scheduler.start()
    yield
    scheduler.stop()
    db.close()


app = FastAPI(title="Bingo Bingo 策略實驗室", lifespan=lifespan)

_cache: dict[str, tuple[float, object]] = {}


def cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.time(), value)
    return value


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/overview")
def overview():
    with db.connection() as conn:
        last = db.latest_draw(conn)
        if last is None:
            raise HTTPException(503, "尚無開獎資料，請先匯入歷史資料")
        now = datetime.now(tl.TZ)
        target = tl.next_target(last["draw_term"], last["draw_date"], last["draw_index"], now)
        preds = db.predictions_for(conn, target["term"])
        previous = db.predictions_for(conn, last["draw_term"])
        promotions = cached("promotions", 300, lambda: db.promotions(conn))
    return {
        "server_time": now.isoformat(),
        "latest_draw": last,
        "next_draw": {"term": target["term"], "time": target["time"].isoformat(), "date": target["date"],
                      "index": target["index"]},
        "payouts": stats.payout_overview(target["date"], promotions),
        "predictions": [{"strategy": p["strategy"], "description": DESCRIPTIONS.get(p["strategy"], p["strategy"]),
                         "ranking": p["ranking"], "created_at": p["created_at"]} for p in preds],
        "previous_predictions": [{"strategy": p["strategy"], "ranking": p["ranking"], "hits": p["hits"],
                                  "live": p["created_at"] < p["target_time"]} for p in previous],
        "predict_stars": config.PREDICT_STARS,
        "strategies": DESCRIPTIONS,
        "scheduler": {k: scheduler.status[k] for k in ("enabled", "last_run", "next_run", "last_error")},
    }


@app.get("/api/draws")
def draws(limit: int = Query(50, ge=1, le=500)):
    with db.connection() as conn:
        return db.recent_draws(conn, limit)


@app.get("/api/live-stats")
def live_stats():
    with db.connection() as conn:
        last = db.latest_draw(conn)

    def compute():
        with db.connection() as conn:
            rows = db.live_hit_counts(conn, config.PREDICT_STARS)
            promotions = db.promotions(conn)
        return stats.live_stats(rows, promotions, DESCRIPTIONS)
    # Keyed by the latest draw so a new draw invalidates it immediately.
    return cached(f"live_stats:{last['draw_term'] if last else 0}", 300, compute)


@app.get("/api/strategy/{name}")
def strategy_detail(name: str, limit: int = Query(50, ge=1, le=300)):
    """A strategy's most recent predictions with the drawn numbers (pending ones included)."""
    if name not in DESCRIPTIONS:
        raise HTTPException(404, "沒有這個策略")
    with db.connection() as conn:
        rows = db.strategy_recent(conn, name, limit)
        promotions = cached("promotions", 300, lambda: db.promotions(conn))
    for r in rows:
        r["prizes"] = ({k: star_table(k, on=r["draw_date"], promotions=promotions).get(r["hits"][k - 1], 0)
                        for k in config.PREDICT_STARS} if r["hits"] else None)
    return {"strategy": name, "description": DESCRIPTIONS[name], "predictions": rows}


@app.get("/api/backtest")
def backtest():
    def load():
        with db.connection() as conn:
            row = db.latest_backtest(conn, "strategies")
        if row is None:
            raise HTTPException(404, "尚未上傳回測結果")
        return {"created_at": row["created_at"], **row["payload"]}
    return cached("backtest", 600, load)


@app.get("/api/promotions")
def promotions():
    with db.connection() as conn:
        return [stats.promo_json(p) for p in db.promotions(conn)]


@app.post("/api/cron/sync")
def cron_sync(x_cron_secret: str = Header(default="")):
    """Lets an external scheduler (e.g. Supabase pg_cron) trigger the sync job."""
    if not config.CRON_SECRET or not hmac.compare_digest(x_cron_secret, config.CRON_SECRET):
        raise HTTPException(403, "forbidden")
    result = sync.run_exclusive()
    return result if result is not None else {"skipped": "sync already running"}


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
