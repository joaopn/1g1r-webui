-- P2c: conversions are journalled as steps beside the moves.
--   move     a file moved without being changed (1G1R discards, originals, restores)
--   convert  an output written from the source, verified; the source stays where it is
--   delete   a source removed for good (delete-originals; never undone)
--   remove   a conversion's output removed after its original was restored
ALTER TABLE operation ADD COLUMN action TEXT NOT NULL DEFAULT 'move'
    CHECK (action IN ('move', 'convert', 'delete', 'remove'));
-- The size of the destination once written (a conversion's output differs from its source).
ALTER TABLE operation ADD COLUMN moved_size INTEGER;
-- The convert step this step completes (moving or deleting that conversion's original).
ALTER TABLE operation ADD COLUMN step_of INTEGER REFERENCES operation (id);
