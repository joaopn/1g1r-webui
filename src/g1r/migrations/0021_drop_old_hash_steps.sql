-- Scan cache rows of steps no longer read: the payload SHA1 (now the content hashes after
-- a probe), the header-stripped and byte-order CRCs and the padded card CRC. Content
-- hashes are read again once: they no longer include a byte-swapped variant. The
-- inventory's own byte-order step ('byte-order:…') stays.
DELETE FROM file_cache
WHERE step LIKE 'payload-sha1%'
   OR step LIKE 'headerless%'
   OR step LIKE 'byte-order-crcs%'
   OR step LIKE 'padded-crc%'
   OR step LIKE 'content-hashes%';
