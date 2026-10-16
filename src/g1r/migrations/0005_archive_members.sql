-- What each archive holds, as of the folder's latest scan.
CREATE TABLE archive_member (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    member        TEXT NOT NULL,
    size          INTEGER NOT NULL,
    crc32         TEXT,
    PRIMARY KEY (folder_label, rel_path, member),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);

-- Archives that could not be listed, with the reason.
CREATE TABLE archive_problem (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    message       TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
