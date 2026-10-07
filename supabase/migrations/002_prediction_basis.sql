-- Which draw a prediction was computed after. When a newer draw arrives before the target
-- draw time, the prediction is recomputed with the fresher data (still before its draw).
alter table predictions add column if not exists based_on_term bigint;
