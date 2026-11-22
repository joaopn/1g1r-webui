---
title: "3DS and Switch"
parent: User guide
nav_order: 7
---
# 3DS and Switch

- 3DS: encrypted images are decrypted with your own console's keys (`boot9.bin`, `seeddb.bin`), added in the UI. No keys are included. A decrypted image is kept only if it matches the hashes its partitions carry; no DAT is needed.
- Switch: no public DAT exists, so files are identified by the title ID and version inside each file. 1G1R keeps every update and DLC; older updates can be discarded on the Updates & DLC tab, and updates and DLC can optionally be moved into a folder per game (`<Game>/update/`, `<Game>/dlc/`). With your own `prod.keys` (added in the UI, none included), versions are also read from files without a `cnmt.xml`. NSZ is converted to NSP; each NCA is checked against its content ID. XCI and XCZ (game card images) are not supported.

How it works: [Switch](../architecture/switch.md), [Conversion](../architecture/conversion.md)
