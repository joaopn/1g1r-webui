-- The Statistics page's figures as last computed, so opening it reads them instead of
-- parsing every DAT again. `kind` is folder (key: label), missing (key: label and source)
-- or dat (key: DAT SHA1); `fingerprint` names the data a folder's figures were computed
-- from, so the page can tell which ones changed since.
CREATE TABLE statistics_cache (
    kind         TEXT NOT NULL,
    key          TEXT NOT NULL,
    fingerprint  TEXT NOT NULL,
    computed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    value        TEXT NOT NULL,
    PRIMARY KEY (kind, key)
);
