# 1g1r-webui

A web UI for tidying ROM folders, one platform per folder: lossless conversion to the format your emulator plays, then checksum matching against DATs and one-game-one-ROM selection, reviewed in a table before anything is applied. Discarded files are moved, never deleted, and every reversible operation can be undone.

Status: early development. This branch contains the tool image only (P0); the web app comes next.

## Tool image

```sh
docker build -t 1g1r-webui .
docker run --rm 1g1r-webui        # prints the version of every bundled tool
```

Bundled external tools, pinned in the `Dockerfile`:

| Tool | Version | Licence | Used for |
|---|---|---|---|
| [igir](https://igir.io) | 5.7.2 | GPL-3.0-or-later | reading archives and disc images, DAT checksum matching, content hashes |
| chdman (MAME, Debian `mame-tools`) | 0.276 | GPL-2.0-or-later | CHD creation, extraction, verification |
| [dolphin-tool](https://github.com/emmercm/dolphin-tool-js) | 0.2606.2 | GPL-3.0-or-later wrapper, Dolphin GPL-2.0-or-later | RVZ conversion and verification |
| 7-Zip (Debian `7zip`, binary `7z`) | 25.01 | LGPL-2.1-or-later with unRAR restriction | unpacking archives |
| [Retool](https://github.com/unexpectedpanda/retool) | 2.4.9 | BSD-3-Clause | clone lists for grouping versions |

They run as separate programs; their licences and sources are those of their upstream projects.

## Licence

AGPL-3.0-or-later. See [LICENSE](LICENSE). Because this is a network application, the running web UI links to its source.
