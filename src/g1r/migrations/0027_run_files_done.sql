-- A run's progress in files: `total` is the files it works on, `files_done` those it has
-- finished with (failed ones too). A conversion is several steps per file.
ALTER TABLE apply_run ADD COLUMN files_done INTEGER NOT NULL DEFAULT 0;
