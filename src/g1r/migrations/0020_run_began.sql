-- When a run began working on its files. A conversion run waits for another folder's to end
-- (one at a time): until then it is running but not begun, and says what it waits for.
ALTER TABLE apply_run ADD COLUMN began_at TEXT;
UPDATE apply_run SET began_at = started_at;
