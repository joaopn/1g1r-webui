-- The user's keep tick per game (overrides the ranking's choice).
CREATE TABLE keep_choice (
    folder_label  TEXT NOT NULL,
    group_key     TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    chosen_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (folder_label, group_key)
);

-- Games the user took out of the operations ("leave this game alone").
CREATE TABLE game_flag (
    folder_label  TEXT NOT NULL,
    group_key     TEXT NOT NULL,
    flagged_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    PRIMARY KEY (folder_label, group_key)
);
