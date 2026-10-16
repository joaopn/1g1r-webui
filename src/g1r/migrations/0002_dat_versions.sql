-- Every DAT file the app has stored, per platform. The active one is named in library.yaml.
CREATE TABLE dat_version (
    id               INTEGER PRIMARY KEY,
    platform         TEXT NOT NULL,
    source           TEXT NOT NULL,
    file             TEXT NOT NULL,
    original_name    TEXT,
    origin           TEXT,
    header_name      TEXT NOT NULL,
    description      TEXT,
    version          TEXT,
    date             TEXT,
    sha1             TEXT NOT NULL,
    game_count       INTEGER NOT NULL,
    has_parent_clone INTEGER NOT NULL,
    matches_platform INTEGER NOT NULL,
    added_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (platform, sha1)
);
CREATE INDEX dat_version_platform ON dat_version (platform, added_at);
