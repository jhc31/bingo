-- Free alternative to the Render Cron Job: let Supabase call the web service every 5 minutes.
-- 1. Supabase dashboard > Database > Extensions: enable pg_cron and pg_net.
-- 2. Replace the URL and secret below (CRON_SECRET is shown in the Render web service's
--    Environment tab), then run this in the SQL editor.
-- Schedule is UTC: minutes 3,8,...,58 of 23:00-15:59 UTC = 07:03-23:58 Taipei.
-- Note: a free Render web service sleeps when idle; the first call wakes it (~1 minute),
-- so the first prediction of the morning may be skipped.

select cron.schedule(
    'bingo-sync',
    '3-59/5 0-15,23 * * *',
    $$
    select net.http_post(
        url := 'https://YOUR-APP.onrender.com/api/cron/sync',
        headers := jsonb_build_object('X-Cron-Secret', 'YOUR_CRON_SECRET', 'Content-Type', 'application/json'),
        timeout_milliseconds := 120000
    );
    $$
);

-- To remove: select cron.unschedule('bingo-sync');
