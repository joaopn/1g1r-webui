-- P10a: what a card image's header says that decides its conversion (3DS): encrypted, with a
-- seed (looked up in seeddb by program ID), the card's size. Read by the scan from a bare
-- image or an archive's one ROM, so the Conversion page needs no file read. Carried to a
-- conversion's output; a decryption's output is marked decrypted.
CREATE TABLE card_info (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    image_size    INTEGER NOT NULL,
    data_size     INTEGER NOT NULL,
    encrypted     INTEGER NOT NULL,
    seed          INTEGER NOT NULL,
    product_code  TEXT NOT NULL,
    program_id    TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path),
    FOREIGN KEY (folder_label, rel_path) REFERENCES folder_file (folder_label, rel_path)
        ON DELETE CASCADE
);
