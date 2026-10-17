-- P3a: the SHA1 of a file's single ROM payload (the bare file, or an archive's one ROM
-- member), computed only where an exact duplicate is possible (another file has a payload
-- of the same size). Equal SHA1s are identical copies.
CREATE TABLE payload_hash (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    size          INTEGER NOT NULL,
    sha1          TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
CREATE INDEX payload_hash_sha1 ON payload_hash (folder_label, sha1);
