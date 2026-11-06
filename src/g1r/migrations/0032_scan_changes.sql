-- How many ROM files (and archives) the run found new, changed or gone since the files it
-- had listed before: 0 tells Home that a check found nothing new. NULL for older runs.
ALTER TABLE scan ADD COLUMN changes INTEGER;
