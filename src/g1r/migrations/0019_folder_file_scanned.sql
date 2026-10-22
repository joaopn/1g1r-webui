-- P10c: whether a Scan has looked at the file since it appeared or changed. Check files lists
-- files without identifying them: one no scan has seen is "not scanned yet", not unmatched.
-- Files of folders scanned before this were all listed by a scan.
ALTER TABLE folder_file ADD COLUMN scanned INTEGER NOT NULL DEFAULT 0;
UPDATE folder_file SET scanned = 1 WHERE folder_label IN (
    SELECT folder_label FROM scan WHERE kind = 'identify' AND status = 'done'
);
