-- Bingo Bingo 策略實驗室 schema.
-- Row level security is enabled with no policies, so Supabase's public REST API (anon key)
-- cannot read or write these tables; only the backend's direct Postgres connection can.

create table if not exists draws (
    draw_term    bigint primary key,
    draw_date    date not null,
    draw_index   smallint not null,          -- 1..203 within the day
    numbers      smallint[] not null,        -- 20 numbers, ascending
    open_order   smallint[] not null,        -- same numbers in drawing order
    super_number smallint not null,          -- 超級獎號 (last number drawn)
    fetched_at   timestamptz not null default now()
);
create index if not exists draws_date_idx on draws (draw_date);

create table if not exists promotions (
    id                 bigserial primary key,
    name               text not null unique,
    start_date         date not null,
    end_date           date not null,
    star_overrides     jsonb not null default '{}'::jsonb,  -- {"3": {"3": 1000}} = 3星中3 → 1000
    super_number_prize integer,                             -- 超級獎號 single prize override
    big_small_prize    integer,                             -- 猜大小/單雙 prize override
    note               text
);

create table if not exists predictions (
    target_term  bigint not null,
    strategy     text not null,
    ranking      smallint[] not null,        -- top-10 picks in order; k星 uses the first k
    target_time  timestamptz not null,       -- scheduled draw time
    created_at   timestamptz not null default now(),
    hits         smallint[],                 -- hits[k] = matches among the first k picks (after draw)
    primary key (target_term, strategy)
);
create index if not exists predictions_unsettled_idx on predictions (target_term) where hits is null;

create table if not exists backtest_runs (
    id         bigserial primary key,
    kind       text not null,                -- e.g. 'strategies'
    created_at timestamptz not null default now(),
    payload    jsonb not null
);

alter table draws enable row level security;
alter table promotions enable row level security;
alter table predictions enable row level security;
alter table backtest_runs enable row level security;

-- Promotions. The 快閃加碼 table below is exactly what the official API paid on the
-- historical dates listed (detected from per-draw prize tables).
insert into promotions (name, start_date, end_date, star_overrides, note) values
    ('2025 春節 基本玩法加碼', '2025-01-24', '2025-02-12',
     '{"6": {"6": 50000, "5": 1200}, "5": {"5": 10000, "4": 600}, "4": {"4": 2000, "3": 150},
       "3": {"3": 1000}, "2": {"2": 150}, "1": {"1": 75}}', '由官方每期獎金表偵測'),
    ('2026 二二八 基本玩法加碼', '2026-02-27', '2026-03-03',
     '{"6": {"6": 50000, "5": 1200}, "5": {"5": 10000, "4": 600}, "4": {"4": 2000, "3": 150},
       "3": {"3": 1000}, "2": {"2": 150}, "1": {"1": 75}}', '由官方每期獎金表偵測'),
    ('2026 端午 基本玩法加碼', '2026-06-19', '2026-06-21',
     '{"6": {"6": 50000, "5": 1200}, "5": {"5": 10000, "4": 600}, "4": {"4": 2000, "3": 150},
       "3": {"3": 1000}, "2": {"2": 150}, "1": {"1": 75}}', '由官方每期獎金表偵測'),
    ('2026 中秋 基本玩法快閃加碼', '2026-10-08', '2026-10-09',
     '{"6": {"6": 50000, "5": 1200}, "5": {"5": 10000, "4": 600}, "4": {"4": 2000, "3": 150},
       "3": {"3": 1000}, "2": {"2": 150}, "1": {"1": 75}}', '台彩中秋加碼海報'),
    ('2026 中秋 超級獎號/猜大小/猜單雙 加碼', '2026-09-25', '2026-10-11', '{}', '台彩中秋加碼海報')
on conflict (name) do nothing;

update promotions set super_number_prize = 1500, big_small_prize = 175
where name = '2026 中秋 超級獎號/猜大小/猜單雙 加碼';
