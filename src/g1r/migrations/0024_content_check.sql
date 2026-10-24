-- Title-ID files (Switch): whether the content archives inside are the ones titledb lists for
-- the file's title ID and version. Written by a scan.
CREATE TABLE content_check (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    note          TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path)
);

CREATE TRIGGER content_check_change_insert AFTER INSERT ON content_check BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER content_check_change_update AFTER UPDATE ON content_check BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER content_check_change_delete AFTER DELETE ON content_check BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
