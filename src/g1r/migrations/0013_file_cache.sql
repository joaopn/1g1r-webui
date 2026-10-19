-- What a scan learned from reading a file (archive listing, headers, checksums), kept
-- between scans: reused while the file's size and mtime are unchanged. Not tied to
-- folder_file, which every scan rewrites; a scan prunes the rows of files that are gone.
-- `step` names what was read and the settings it depends on.
CREATE TABLE file_cache (
    folder_label TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    step TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path, step)
);
