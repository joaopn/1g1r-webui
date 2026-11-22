---
title: Conversion
parent: User guide
nav_order: 2
---
# Conversion

Each platform has one target format. Everything else is converted to it first; matching waits until it is done.

**Check files** (next to the set name) lists the set and what needs converting. Nothing is hashed.

![Conversion](../assets/conversion.png)

**Convert** shows the plan. Each output is checked (CRC32 and size) before the original moves to `discarded/<set>/originals/`.

![Review](../assets/conversion-review.png)

Runs can be stopped. Finished files are kept; the file in progress is removed.

![Running](../assets/conversion-running.png)

Files that cannot be converted can be moved to `discarded/` from the same tab. The target is set per platform in **Settings → Romset management**.

How it works: [Conversion](../architecture/conversion.md)
