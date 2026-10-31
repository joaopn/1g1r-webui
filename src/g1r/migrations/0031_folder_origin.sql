-- A file moved to another folder of its set (the game folders of the Updates & DLC tab):
-- the folder it was in before its first such move ('' = the set's own folder), under its
-- path now. A revert gives it back. No foreign key, so it outlives rescans.
CREATE TABLE folder_origin (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    original_dir  TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path)
);

CREATE TRIGGER folder_origin_change_insert AFTER INSERT ON folder_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER folder_origin_change_update AFTER UPDATE ON folder_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER folder_origin_change_delete AFTER DELETE ON folder_origin BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
