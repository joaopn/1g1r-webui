-- 1 for a Check files run the app started on its own (a set's auto-check): the notifications
-- list it only when it found something or failed.
ALTER TABLE scan ADD COLUMN auto INTEGER NOT NULL DEFAULT 0;
