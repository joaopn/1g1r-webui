# 1g1r-webui

A web UI for tidying ROM folders, one platform per folder: lossless conversion to the format your emulator plays, then checksum matching against DATs and one-game-one-ROM selection, reviewed in a table before anything is applied. Discarded files are moved, never deleted, and every reversible operation can be undone.

Status: early development. Scanning, conversion, 1G1R matching, apply and restore work for the platforms below.

## Supported platforms and formats

A folder holds one platform. The app reads the formats listed, bare or inside a `.zip` or `.7z`; anything else in the folder is listed on the folder's pages as "not in a supported format" and left alone (never converted, matched or moved). "Tested on real files" names the format of the real dumps each platform was checked with: scan and identification, plus conversion, 1G1R apply and restore wherever those dumps needed them. Everything else is covered by tests on synthetic files only.

| Platform | Formats read | Becomes | DAT download | Tested on real files |
|---|---|---|---|---|
| Amiga | `ipf`; with a TOSEC DAT also `adf`, `adz`, `dms`, `lha`, `exe`, `hdf` | zip | libretro (No-Intro) or TOSEC | `ipf` in zip, multi-disk |
| Atari 2600 | `a26`, `bin` | zip | libretro (No-Intro) | — |
| Atari 5200 | `a52`, `bin` | zip | libretro (No-Intro) | — |
| Atari 7800 | `a78`, `bin` | zip | libretro (No-Intro) | — |
| Atari Jaguar | `j64`, `jag`, `rom`, `abs`, `cof` | zip | libretro (No-Intro) | `rom` in zip |
| Atari Lynx | `lnx`, `lyx` | zip | libretro (No-Intro) | — |
| ColecoVision | `col`, `rom`, `bin` | zip | libretro (No-Intro) | — |
| Commodore 64 | `crt`, `d64`; with a TOSEC DAT also `d71`, `d81`, `g64`, `nib`, `t64`, `tap`, `prg`, `p00`, `lnx` | zip | libretro (No-Intro) or TOSEC | `crt` and `d64` in zip |
| Dreamcast | `chd`, `cue`/`bin`, `gdi`/`bin`/`raw` | chd | redump.info | cue/bin in 7z |
| Game Boy | `gb` | zip | libretro (No-Intro) | `gb` in zip |
| Game Boy Advance | `gba` | zip | libretro (No-Intro) | — |
| Game Boy Color | `gbc` | zip | libretro (No-Intro) | — |
| Game Gear | `gg` | zip | libretro (No-Intro) | — |
| GameCube | `rvz`, `iso`, `gcm` | rvz | redump.info | — |
| Master System | `sms` | zip | libretro (No-Intro) | — |
| Mega Drive / Genesis | `md`, `gen`, `bin`, `smd` | zip | libretro (No-Intro) | — |
| Neo Geo CD | `chd`, `cue`/`bin`, `iso` | chd | redump.info | — |
| Neo Geo MVS | FBNeo romset zips (split or non-merged) | zip | FBNeo | romset zips |
| Neo Geo Pocket | `ngp` | zip | libretro (No-Intro) | — |
| Neo Geo Pocket Color | `ngc`, `ngpc` | zip | libretro (No-Intro) | — |
| Nintendo 3DS | `3ds`, `cci`, `cia` | bare file | libretro (No-Intro) | encrypted `3ds` |
| Nintendo 64 | `z64`, `v64`, `n64` (any byte order) | zip, as `z64` | libretro (No-Intro) | `z64` in zip |
| Nintendo DS | `nds` | zip | libretro (No-Intro) | — |
| Nintendo Entertainment System | `nes` | zip | libretro (No-Intro) | `nes` in zip |
| Nintendo Switch | `nsp`, `nsz`, `xci`, `xcz` | bare file | none (identified by title ID) | `nsp`: game and update |
| PC Engine / TurboGrafx-16 | `pce` | zip | libretro (No-Intro) | — |
| PlayStation | `chd`, `cue`/`bin`, `iso` | chd | redump.info | `chd` |
| PlayStation 2 | `chd`, `cue`/`bin`, `iso`, `cso` | chd | redump.info | `cso` |
| PlayStation Portable | `chd`, `iso`, `cso` | chd | redump.info | `chd` |
| Saturn | `chd`, `cue`/`bin`, `iso` | chd | redump.info | — |
| Sega 32X | `32x`, `bin` | zip | libretro (No-Intro) | — |
| Sega CD | `chd`, `cue`/`bin`, `iso` | chd | redump.info | — |
| Super Nintendo | `sfc`, `smc` | zip | libretro (No-Intro) | — |
| Virtual Boy | `vb` | zip | libretro (No-Intro) | — |
| Wii | `rvz`, `iso`, `wbfs` | rvz | redump.info | `rvz` in zip |
| WonderSwan | `ws` | zip | libretro (No-Intro) | — |
| WonderSwan Color | `wsc` | zip | libretro (No-Intro) | — |

TOSEC is published as one pack of every system's DATs (about 100 MB); the TOSEC download takes the newest pack from tosecdev.org and merges the Amiga or C64 DATs in it into one (uploading the pack works too). With a TOSEC DAT active, names are read the TOSEC way and versions also rank by dump quality (verified, then clean, then alternate, cracked, trained, bad).

Every platform's target can be changed in Settings → Platforms; the table shows the default. A DAT can always be uploaded instead of downloaded (DAT-o-MATIC's No-Intro DATs, for instance).

Known limits:

- The libretro mirror keeps one ROM per game. A multi-disk game zipped whole (Amiga, C64) does not match it and stays unmatched, so it is kept; upload the No-Intro DAT from DAT-o-MATIC to match it. Disc platforms download from redump.info for the same reason.
- Encrypted 3DS images never match the DAT, which lists decrypted images: they are flagged, and the DAT entries with the card's product code are suggested for you to choose. Decrypting needs your console's keys and is not done.
- `.wbfs` and NKit images are identified but never converted (they are already stripped of data).
- Not supported: PlayStation Vita, Atari Jaguar CD, CSO version 2 and ZSO.

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

## Running

```sh
cp compose.example.yaml compose.yaml   # adjust the host paths
docker compose up -d --build           # then open http://localhost:8080
```

Configuration lives in `data/config.yaml` (mounted at `/data`). It is deep-merged over the shipped defaults in [`src/g1r/defaults.yaml`](src/g1r/defaults.yaml), which list and document every setting; unknown keys are rejected at start-up. Settings → Advanced shows the effective configuration.

## Development

Backend (Python, FastAPI):

```sh
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest
```

Frontend (`web/`: React, Vite, TypeScript, Tailwind):

```sh
cd web && npm ci
npm run check        # biome, tsc, vitest
npm run dev          # dev server on :5173, proxying /api to a backend on :8080
```

The Docker build runs the frontend checks and fails on any of them.

Project rule: application code contains no magic numbers. Every tunable value goes in `defaults.yaml`; `tests/test_no_magic_numbers.py` and ruff's `PLR2004` enforce it.
