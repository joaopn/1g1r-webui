-- P10b: a folder's runs are of two kinds. 'check' lists the files and reads what conversion
-- decides on (archive listings, headers), hashing nothing; 'identify' (the Scan button) does
-- that too, then identifies the files with nothing left to convert. Earlier scans identified.
ALTER TABLE scan ADD COLUMN kind TEXT NOT NULL DEFAULT 'identify'
    CHECK (kind IN ('check', 'identify'));
