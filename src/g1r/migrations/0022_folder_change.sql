-- A change counter per folder, kept by triggers: every write to a table holding a folder's
-- data bumps that folder's row, every write to the DATs bumps the '' row. Home keeps each
-- folder's card until its counter moves. A new table with a folder_label column needs the
-- same three triggers (a test checks).
CREATE TABLE folder_change (
    folder_label TEXT PRIMARY KEY,
    n INTEGER NOT NULL
);

CREATE TRIGGER apply_run_change_insert AFTER INSERT ON apply_run BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER apply_run_change_update AFTER UPDATE ON apply_run BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER apply_run_change_delete AFTER DELETE ON apply_run BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_member_change_insert AFTER INSERT ON archive_member BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_member_change_update AFTER UPDATE ON archive_member BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_member_change_delete AFTER DELETE ON archive_member BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_problem_change_insert AFTER INSERT ON archive_problem BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_problem_change_update AFTER UPDATE ON archive_problem BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER archive_problem_change_delete AFTER DELETE ON archive_problem BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER byte_order_change_insert AFTER INSERT ON byte_order BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER byte_order_change_update AFTER UPDATE ON byte_order BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER byte_order_change_delete AFTER DELETE ON byte_order BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER card_info_change_insert AFTER INSERT ON card_info BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER card_info_change_update AFTER UPDATE ON card_info BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER card_info_change_delete AFTER DELETE ON card_info BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER content_hash_change_insert AFTER INSERT ON content_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER content_hash_change_update AFTER UPDATE ON content_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER content_hash_change_delete AFTER DELETE ON content_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_cache_change_insert AFTER INSERT ON file_cache BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_cache_change_update AFTER UPDATE ON file_cache BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_cache_change_delete AFTER DELETE ON file_cache BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_note_change_insert AFTER INSERT ON file_note BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_note_change_update AFTER UPDATE ON file_note BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER file_note_change_delete AFTER DELETE ON file_note BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER folder_file_change_insert AFTER INSERT ON folder_file BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER folder_file_change_update AFTER UPDATE ON folder_file BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER folder_file_change_delete AFTER DELETE ON folder_file BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER game_flag_change_insert AFTER INSERT ON game_flag BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER game_flag_change_update AFTER UPDATE ON game_flag BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER game_flag_change_delete AFTER DELETE ON game_flag BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER identity_change_insert AFTER INSERT ON identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER identity_change_update AFTER UPDATE ON identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER identity_change_delete AFTER DELETE ON identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER keep_choice_change_insert AFTER INSERT ON keep_choice BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER keep_choice_change_update AFTER UPDATE ON keep_choice BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER keep_choice_change_delete AFTER DELETE ON keep_choice BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER lookup_result_change_insert AFTER INSERT ON lookup_result BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER lookup_result_change_update AFTER UPDATE ON lookup_result BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER lookup_result_change_delete AFTER DELETE ON lookup_result BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER manual_identity_change_insert AFTER INSERT ON manual_identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER manual_identity_change_update AFTER UPDATE ON manual_identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER manual_identity_change_delete AFTER DELETE ON manual_identity BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER operation_change_insert AFTER INSERT ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER operation_change_update AFTER UPDATE ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER operation_change_delete AFTER DELETE ON operation BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER payload_hash_change_insert AFTER INSERT ON payload_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER payload_hash_change_update AFTER UPDATE ON payload_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER payload_hash_change_delete AFTER DELETE ON payload_hash BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER scan_change_insert AFTER INSERT ON scan BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER scan_change_update AFTER UPDATE ON scan BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER scan_change_delete AFTER DELETE ON scan BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER suggestion_change_insert AFTER INSERT ON suggestion BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER suggestion_change_update AFTER UPDATE ON suggestion BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
    INSERT INTO folder_change (folder_label, n) VALUES (NEW.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER suggestion_change_delete AFTER DELETE ON suggestion BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES (OLD.folder_label, 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER dat_version_change_insert AFTER INSERT ON dat_version BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES ('', 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER dat_version_change_update AFTER UPDATE ON dat_version BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES ('', 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
CREATE TRIGGER dat_version_change_delete AFTER DELETE ON dat_version BEGIN
    INSERT INTO folder_change (folder_label, n) VALUES ('', 1) ON CONFLICT (folder_label) DO UPDATE SET n = n + 1;
END;
