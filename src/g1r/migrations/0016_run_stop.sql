-- A conversion run the user asked to stop: set at once, so every page shows "Stopping"
-- until the files under way are cut off; the run then ends with a "stopped: ..." message.
ALTER TABLE apply_run ADD COLUMN stopping INTEGER NOT NULL DEFAULT 0;
