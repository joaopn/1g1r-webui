-- P2: every move is journalled before it runs, so it can be resumed, rolled back or undone.

-- One apply or restore, as the user started it.
CREATE TABLE apply_run (
    id            INTEGER PRIMARY KEY,
    folder_label  TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('apply', 'restore')),
    scope         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    total         INTEGER NOT NULL DEFAULT 0,
    message       TEXT NOT NULL DEFAULT '',
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at   TEXT
);
CREATE INDEX apply_run_folder ON apply_run (folder_label, id);

-- One file moved (or refused). 'started' is committed before the file is touched.
CREATE TABLE operation (
    id            INTEGER PRIMARY KEY,
    run_id        INTEGER NOT NULL REFERENCES apply_run (id),
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    group_key     TEXT NOT NULL DEFAULT '',
    reason        TEXT NOT NULL,
    source        TEXT NOT NULL,
    destination   TEXT NOT NULL,
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    -- The destination's mtime once moved (a copy to another disk may round it).
    moved_mtime_ns INTEGER,
    state         TEXT NOT NULL CHECK (state IN ('started', 'done', 'failed', 'restored')),
    error         TEXT NOT NULL DEFAULT '',
    -- The restore operation that moved this file back, once restored.
    restored_by   INTEGER REFERENCES operation (id),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX operation_run ON operation (run_id);
CREATE INDEX operation_folder ON operation (folder_label, state);

-- Where a scanned file is now: still in the folder, or moved to discarded/ by an apply.
ALTER TABLE folder_file ADD COLUMN place TEXT NOT NULL DEFAULT 'folder'
    CHECK (place IN ('folder', 'discarded'));
