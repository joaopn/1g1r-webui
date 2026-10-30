-- The external command a running scan's step is waiting on (igir), as a shell would show it.
-- Shown on the folder pages while it runs; cleared when the step ends.
ALTER TABLE scan ADD COLUMN command TEXT;
