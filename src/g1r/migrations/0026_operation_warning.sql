-- What a run reports about a step that succeeded (a disc track padded to a whole sector);
-- empty for nothing.
ALTER TABLE operation ADD COLUMN warning TEXT NOT NULL DEFAULT '';
