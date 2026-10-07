"""Background thread that runs the sync job right after each draw while the web process is up.

Timing: wake PUBLISH_DELAY seconds after the next scheduled draw; if the official API has not
published it yet, retry every 15 s (every 60 s once more than 10 minutes behind). Each
successful sync immediately predicts the following draw, so predictions appear about
4 minutes before their draw.

On Render's free plan the web service sleeps when idle, so a Cron Job (or Supabase pg_cron
hitting /api/cron/sync) is still needed to keep data current; both paths are idempotent.
"""
import logging
import threading
from datetime import datetime, timedelta

from app import config, db, sync
from core import taiwan_lottery as tl

log = logging.getLogger("scheduler")


class Scheduler:
    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status = {"enabled": config.ENABLE_SCHEDULER, "last_run": None, "last_result": None,
                       "last_error": None, "next_run": None}

    def start(self):
        if not config.ENABLE_SCHEDULER or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="bingo-scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            delay = self._tick()
            self.status["next_run"] = (datetime.now(tl.TZ) + timedelta(seconds=delay)).isoformat()
            self._stop.wait(delay)

    def _tick(self) -> float:
        try:
            result = sync.run_exclusive()
            if result is not None:
                self.status.update(last_run=datetime.now(tl.TZ).isoformat(), last_result=result, last_error=None)
            with db.connection() as conn:
                last = db.latest_draw(conn)
        except Exception as e:  # noqa: BLE001 - keep the scheduler alive on network/DB errors
            log.exception("sync failed")
            self.status["last_error"] = str(e)
            return 60
        if last is None:
            return 300
        now = datetime.now(tl.TZ)
        upcoming = tl.next_target(last["draw_term"], last["draw_date"], last["draw_index"],
                                  tl.draw_time(last["draw_date"], last["draw_index"]))
        due = upcoming["time"] + timedelta(seconds=config.PUBLISH_DELAY)
        if due > now:
            return (due - now).total_seconds()
        return 15 if now - upcoming["time"] < timedelta(minutes=10) else 60


scheduler = Scheduler()
