"""Postgres (Supabase) access. Uses a direct connection, so Supabase's Session pooler URL
works on Render (IPv4). prepare_threshold=None keeps it compatible with the Transaction
pooler as well."""
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app import config

_pool: ConnectionPool | None = None


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set")
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=config.DB_POOL_MAX, open=True,
                               kwargs={"prepare_threshold": None, "row_factory": dict_row})
    return _pool


@contextmanager
def connection():
    with pool().connection() as conn:
        yield conn


def close():
    if _pool is not None:
        _pool.close()


# ---- draws -------------------------------------------------------------------------------

def latest_draw(conn) -> dict | None:
    return conn.execute("select * from draws order by draw_term desc limit 1").fetchone()


def recent_draws(conn, limit: int) -> list[dict]:
    return conn.execute("select * from draws order by draw_term desc limit %s", (limit,)).fetchall()


def draw_history(conn, limit: int) -> list[list[int]]:
    """Numbers of the last `limit` draws, oldest first."""
    rows = conn.execute("select numbers from (select draw_term, numbers from draws order by draw_term desc "
                        "limit %s) t order by draw_term", (limit,)).fetchall()
    return [r["numbers"] for r in rows]


def upsert_draws(conn, draws: list[dict]) -> int:
    if not draws:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "insert into draws (draw_term, draw_date, draw_index, numbers, open_order, super_number) "
            "values (%(draw_term)s, %(draw_date)s, %(draw_index)s, %(numbers)s, %(open_order)s, %(super_number)s) "
            "on conflict (draw_term) do nothing", draws)
        return cur.rowcount


def draw_count(conn) -> int:
    return conn.execute("select count(*) as n from draws").fetchone()["n"]


# ---- promotions --------------------------------------------------------------------------

def promotions(conn) -> list[dict]:
    """Promotions in the format core.payouts expects (int keys, date bounds)."""
    rows = conn.execute("select * from promotions order by start_date").fetchall()
    out = []
    for r in rows:
        stars = {int(k): {int(m): int(v) for m, v in t.items()} for k, t in (r["star_overrides"] or {}).items()}
        out.append({"name": r["name"], "start": r["start_date"], "end": r["end_date"], "stars": stars,
                    "super_number": r["super_number_prize"], "big_small": r["big_small_prize"],
                    "note": r["note"]})
    return out


# ---- predictions -------------------------------------------------------------------------

def upsert_predictions(conn, target_term: int, target_time, based_on_term: int,
                       rankings: dict[str, list[int]]) -> int:
    """Insert predictions, or replace ones computed from older data that are still unsettled."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            insert into predictions (target_term, strategy, ranking, target_time, based_on_term)
            values (%s, %s, %s, %s, %s)
            on conflict (target_term, strategy) do update
                set ranking = excluded.ranking, based_on_term = excluded.based_on_term, created_at = now()
                where predictions.hits is null
                  and coalesce(predictions.based_on_term, 0) < excluded.based_on_term
            """,
            [(target_term, name, ranking, target_time, based_on_term) for name, ranking in rankings.items()])
        return cur.rowcount


def predictions_for(conn, target_term: int) -> list[dict]:
    return conn.execute("select * from predictions where target_term = %s", (target_term,)).fetchall()


def settle_predictions(conn) -> int:
    """Fill hits[k] (matches among the first k picks) for predictions whose draw is in."""
    rows = conn.execute(
        "select p.target_term, p.strategy, p.ranking, d.numbers from predictions p "
        "join draws d on d.draw_term = p.target_term where p.hits is null").fetchall()
    updates = []
    for r in rows:
        drawn = set(r["numbers"])
        hits, h = [], 0
        for n in r["ranking"]:
            h += n in drawn
            hits.append(h)
        updates.append((hits, r["target_term"], r["strategy"]))
    if updates:
        with conn.cursor() as cur:
            cur.executemany("update predictions set hits = %s where target_term = %s and strategy = %s", updates)
    return len(updates)


def strategy_recent(conn, strategy: str, limit: int) -> list[dict]:
    return conn.execute(
        """
        select p.target_term, p.ranking, p.hits, p.target_time, p.created_at < p.target_time as live,
               d.draw_date, d.numbers
        from predictions p left join draws d on d.draw_term = p.target_term
        where p.strategy = %s order by p.target_term desc limit %s
        """, (strategy, limit)).fetchall()


def live_hit_counts(conn, stars: tuple[int, ...]) -> list[dict]:
    """Counts of (strategy, k, hits, draw_date) for predictions made before their draw."""
    return conn.execute(
        """
        select p.strategy, u.k::int as k, u.h::int as h, d.draw_date, count(*)::int as n
        from predictions p
        join draws d on d.draw_term = p.target_term
        cross join lateral unnest(p.hits) with ordinality as u(h, k)
        where p.hits is not null and p.created_at < p.target_time and u.k = any(%s)
        group by p.strategy, u.k, u.h, d.draw_date
        """, (list(stars),)).fetchall()


# ---- backtest ----------------------------------------------------------------------------

def latest_backtest(conn, kind: str = "strategies") -> dict | None:
    row = conn.execute("select payload, created_at from backtest_runs where kind = %s "
                       "order by created_at desc limit 1", (kind,)).fetchone()
    return row


def insert_backtest(conn, kind: str, payload) -> None:
    from psycopg.types.json import Jsonb
    conn.execute("insert into backtest_runs (kind, payload) values (%s, %s)", (kind, Jsonb(payload)))

