-- The notifications panel lists the latest scans and runs; Clear marks the finished ones
-- dismissed so the panel stops listing them (the rows themselves stay).
ALTER TABLE scan ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE apply_run ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0;
