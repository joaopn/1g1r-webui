-- Every external command a scan ran (igir), in order, as a JSON list of what `command`
-- showed. Kept when the scan ends, so the folder page shows them until the next scan.
ALTER TABLE scan ADD COLUMN commands TEXT;
