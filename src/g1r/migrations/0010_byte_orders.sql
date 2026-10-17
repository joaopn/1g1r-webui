-- P4a: files whose single ROM is in a swapped byte order (N64 .v64 / little-endian), and the
-- word length to reverse for the native order. Read from the data at every scan, never from
-- the extension. Not carried over to a conversion's output, which is in the native order.
CREATE TABLE byte_order (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    word_bytes    INTEGER NOT NULL,
    PRIMARY KEY (folder_label, rel_path),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
