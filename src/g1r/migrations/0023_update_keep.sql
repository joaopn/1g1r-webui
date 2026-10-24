-- Older updates of a title-ID game (Switch) the user keeps: never proposed for discarded/.
CREATE TABLE update_keep (
    folder_label  TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    PRIMARY KEY (folder_label, rel_path)
);

CREATE TRIGGER update_keep_change_insert AFTER INSERT ON update_keep BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER update_keep_change_update AFTER UPDATE ON update_keep BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER update_keep_change_delete AFTER DELETE ON update_keep BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
