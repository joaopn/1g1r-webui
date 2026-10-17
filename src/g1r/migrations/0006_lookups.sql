-- How sure an identification is: 1 for checksum matches, the name score for fuzzy ones.
ALTER TABLE identity ADD COLUMN score REAL NOT NULL DEFAULT 1;

-- Content hashes of files the local DAT did not identify (the data a lookup sends).
CREATE TABLE content_hash (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    variant       TEXT NOT NULL,
    size          INTEGER NOT NULL,
    crc32         TEXT NOT NULL,
    md5           TEXT NOT NULL,
    sha1          TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path, variant),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);

-- Online answers, by the SHA1 asked about; shared by every folder.
CREATE TABLE lookup_cache (
    service     TEXT NOT NULL,
    sha1        TEXT NOT NULL,
    found       INTEGER NOT NULL,
    body        TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (service, sha1)
);

-- What each lookup said about each unmatched file, as of the latest scan.
CREATE TABLE lookup_result (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    service       TEXT NOT NULL,
    status        TEXT NOT NULL,
    detail        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (folder_label, rel_path, service),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);

-- Name suggestions for unmatched files, as of the latest scan.
CREATE TABLE suggestion (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    game_name     TEXT NOT NULL,
    score         REAL NOT NULL,
    PRIMARY KEY (folder_label, rel_path, game_name),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);

-- Files the user assigned to a DAT entry by hand; kept across scans (no foreign key).
CREATE TABLE manual_identity (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    game_name     TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path)
);
