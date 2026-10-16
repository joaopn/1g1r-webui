-- One row per scan of a folder; the latest finished one is what the tables show.
CREATE TABLE scan (
    id            INTEGER PRIMARY KEY,
    folder_label  TEXT NOT NULL,
    status        TEXT NOT NULL CHECK (status IN ('running', 'done', 'failed')),
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    finished_at   TEXT,
    dat_sha1      TEXT,
    message       TEXT
);
CREATE INDEX scan_folder ON scan (folder_label, id);

-- The files of a folder as of its latest scan.
CREATE TABLE folder_file (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    size          INTEGER NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('rom', 'archive', 'ignored', 'other')),
    PRIMARY KEY (folder_label, rel_path)
);

-- Which DAT game a file was identified as, and how.
CREATE TABLE identity (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    game_name     TEXT NOT NULL,
    method        TEXT NOT NULL,
    dat_sha1      TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path, game_name),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
