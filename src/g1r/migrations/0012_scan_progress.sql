-- How far a running scan is: the step it is on and, for steps that go file by file, how
-- many of that step's files are done. Shown on the Home cards and the folder pages.
ALTER TABLE scan ADD COLUMN stage TEXT;
ALTER TABLE scan ADD COLUMN files_done INTEGER;
ALTER TABLE scan ADD COLUMN files_total INTEGER;
