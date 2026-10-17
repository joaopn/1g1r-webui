-- P4d: what the scan learned from a file's own header that matters to the user: a 3DS card
-- image that is encrypted or trimmed. Carried to a conversion's output (an unzip keeps both).
CREATE TABLE file_note (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    note          TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path, note),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
