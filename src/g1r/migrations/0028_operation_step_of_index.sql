-- Listing a folder's files in discarded/ asks, for every move, whether a later step
-- deleted it (`step_of`). Without this index each question read the whole journal of
-- every folder, so a decision on a large set took seconds once the journal grew.
CREATE INDEX operation_step_of ON operation (step_of);
