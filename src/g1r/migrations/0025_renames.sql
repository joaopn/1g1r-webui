-- Renaming files to a naming template: a rename is a journalled step of its own, inside the
-- folder. The action CHECK cannot be altered in place, so the table is rebuilt (its own
-- references point at the new table once renamed).
CREATE TABLE operation_new (
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
    moved_mtime_ns INTEGER,
    state         TEXT NOT NULL CHECK (state IN ('started', 'done', 'failed', 'restored')),
    error         TEXT NOT NULL DEFAULT '',
    restored_by   INTEGER REFERENCES operation_new (id),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    --   rename   a file given another name in its folder (and back, by a revert)
    action        TEXT NOT NULL DEFAULT 'move'
        CHECK (action IN ('move', 'convert', 'delete', 'remove', 'rename')),
    moved_size    INTEGER,
    step_of       INTEGER REFERENCES operation_new (id)
);
INSERT INTO operation_new SELECT * FROM operation;
DROP TABLE operation;
ALTER TABLE operation_new RENAME TO operation;
CREATE INDEX operation_run ON operation (run_id);
CREATE INDEX operation_folder ON operation (folder_label, state);

CREATE TRIGGER operation_change_insert AFTER INSERT ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER operation_change_update AFTER UPDATE ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER operation_change_delete AFTER DELETE ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;

-- A renamed file's name before its first rename, under its name now: a revert gives it back.
-- No foreign key, so it outlives rescans.
CREATE TABLE rename_origin (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    original      TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path)
);

CREATE TRIGGER rename_origin_change_insert AFTER INSERT ON rename_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER rename_origin_change_update AFTER UPDATE ON rename_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER rename_origin_change_delete AFTER DELETE ON rename_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
