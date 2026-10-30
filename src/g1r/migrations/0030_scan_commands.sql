-- Every external command a scan ran (igir), in order, as a JSON list of
-- {"command": what `command` showed, "output": the screen it drew, as lines of [text, style]
-- runs (lines of plain text before igir ran on a terminal)}. Kept when the scan ends, so the
-- folder page shows them until the next scan.
ALTER TABLE scan ADD COLUMN commands TEXT;
