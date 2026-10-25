# 1g1r-webui

A web UI for organizing ROMSET collections and creating one-game-one-rom (1G1R) collections.

## What it does

- Identifies files by checksum against the platform's DAT
- Converts losslessly to the platform's target format (zip, CHD, RVZ or the bare file)
- Groups the versions of each game and ranks them by region, language and revision for 1G1R


## Running

```sh
git clone <this repo> && cd 1g1r-webui
ROMS=/path/to/roms docker compose up -d --build    # http://localhost:8077
```

`ROMS` is the folder holding your ROMs; it is mounted at `/roms` in the container. Instead of passing it each time, put it in a `.env` file next to `compose.yaml`:

```sh
ROMS=/path/to/roms
PORT=8077        # optional, the host port
PUID=1000        # optional, the user and group owning your ROM files
PGID=1000
```

To add another ROM folder (another disk), add a line under `volumes:` in `compose.yaml`, mounted under `/mnt/<name>`:

```yaml
      - /mnt/disk2/roms:/mnt/disk2
```

The app keeps its database, DATs, caches and console keys in `data/` in the clone. Keys are entered in the web UI.

## Platforms

Files are read bare or inside `.zip`/`.7z`. Every file is converted to its platform's target format (a `.7z` becomes a `.zip`); files that cannot be converted are listed for moving to `discarded/`. Scanning (igir, Hasheous) and 1G1R wait until every file is in the target format.

| Platform | Formats | Target | DAT |
|---|---|---|---|
| Amiga | `ipf`; with TOSEC also `adf`, `adz`, `dms`, `lha`, `exe`, `hdf` | zip | No-Intro or TOSEC |
| Atari 2600 | `a26`, `bin` | zip | No-Intro |
| Atari 5200 | `a52`, `bin` | zip | No-Intro |
| Atari 7800 | `a78`, `bin` | zip | No-Intro |
| Atari Jaguar | `j64`, `jag`, `rom`, `abs`, `cof` | zip | No-Intro |
| Atari Lynx | `lnx`, `lyx`, `bll` (aftermarket executables) | zip | No-Intro |
| ColecoVision | `col`, `rom`, `bin` | zip | No-Intro |
| Commodore 64 | `crt`, `d64`; with TOSEC also `d71`, `d81`, `g64`, `nib`, `t64`, `tap`, `prg`, `p00`, `lnx` | zip | No-Intro or TOSEC |
| Dreamcast | `chd`, `cue`/`bin`, `gdi`; `cdi` cannot be converted (chdman cannot read it) | chd | Redump, Non-Redump, TOSEC |
| Game Boy | `gb` | zip | No-Intro |
| Game Boy Advance | `gba` | zip | No-Intro |
| Game Boy Color | `gbc` | zip | No-Intro |
| Game Gear | `gg`, `sms` (carts that run in Master System mode) | zip | No-Intro |
| GameCube | `rvz`, `iso`, `gcm` | rvz | Redump, Non-Redump |
| Master System | `sms` | zip | No-Intro |
| Mega Drive / Genesis | `md`, `gen`, `bin`, `smd` | zip | No-Intro |
| Neo Geo CD | `chd`, `cue`/`bin`, `iso` | chd | Redump |
| Neo Geo MVS | romset zips | zip | FBNeo |
| Neo Geo Pocket | `ngp` | zip | No-Intro |
| Neo Geo Pocket Color | `ngc`, `ngpc` | zip | No-Intro |
| Nintendo 3DS | `3ds`, `cci`, `cia` | bare file (decrypted) | No-Intro, New 3DS |
| Nintendo 64 | `z64`, `v64`, `n64` | zip (`z64`) | No-Intro |
| Nintendo DS | `nds` | zip | No-Intro |
| NES | `nes` | zip | No-Intro |
| Nintendo Switch | `nsp`, `nsz` | `nsp` | none, title ID |
| PC Engine / TurboGrafx-16 | `pce`, `sgx` | zip | No-Intro, SuperGrafx |
| PlayStation | `chd`, `cue`/`bin`, `iso` | chd | Redump, Non-Redump |
| PlayStation 2 | `chd`, `cue`/`bin`, `iso`, `cso` | chd | Redump, Non-Redump |
| PlayStation Portable | `chd`, `iso`, `cso` | chd | Redump, Non-Redump, PSN |
| Saturn | `chd`, `cue`/`bin`, `iso` | chd | Redump, Non-Redump |
| Sega 32X | `32x`, `bin` | zip | No-Intro |
| Sega CD | `chd`, `cue`/`bin`, `iso` | chd | Redump, Non-Redump |
| Super Nintendo | `sfc`, `smc` | zip | No-Intro |
| Virtual Boy | `vb` | zip | No-Intro |
| Wii | `rvz`, `iso`, `wbfs` | rvz | Redump, Non-Redump |
| WonderSwan | `ws` | zip | No-Intro |
| WonderSwan Color | `wsc` | zip | No-Intro |

The target can be changed per platform in Settings.

- Non-Redump: No-Intro's DATs of discs Redump does not list (prototypes, betas, unlicensed). DAT-o-MATIC serves them to a browser only: the Non-Redump button in Settings → Platform DATs opens the page, then the file is uploaded there.
- PSN (PSP): No-Intro's DAT of digital-only releases, downloaded from the libretro-database mirror. Games kept as an EBOOT.PBP folder are not supported.
- SuperGrafx (PC Engine): No-Intro's DAT of the HuCards that need the SuperGrafx, which its PC Engine DAT leaves out, downloaded from the libretro-database mirror.
- New 3DS (3DS): No-Intro's DAT of the cards that need a New 3DS (Xenoblade Chronicles 3D, Fire Emblem Warriors), which its 3DS DAT leaves out, downloaded from the libretro-database mirror.

- 3DS: encrypted images are decrypted with your own console's keys (`boot9.bin`, `seeddb.bin`), added in the UI. No keys are included. A decrypted image is kept only if it matches the hashes its partitions carry; no DAT is needed.
- Switch: no public DAT exists, so files are identified by the title ID and version inside each file. 1G1R keeps every update and DLC; older updates can be discarded on the Updates tab. With your own `prod.keys` (added in the UI, none included), versions are also read from files without a `cnmt.xml`. NSZ is converted to NSP; each NCA is checked against its content ID. XCI and XCZ (game card images) are not supported.

## Backend

The work is done by existing tools and databases. 

| | Used for |
|---|---|
| [igir](https://igir.io) 5.8.0 | checksum matching against DATs, reading archives and disc images |
| chdman (MAME) 0.276 | CHD creation and verification |
| [dolphin-tool](https://github.com/emmercm/dolphin-tool-js) 0.2606.2 | RVZ conversion and verification |
| 7-Zip 25.01 | unpacking archives |
| [Retool](https://github.com/unexpectedpanda/retool) 2.4.9 clone lists | grouping versions of a game |
| [pyctr](https://github.com/ihaveamac/pyctr) | 3DS decryption |
| No-Intro, Redump, FBNeo, TOSEC DATs | identification (downloaded from libretro-database, redump.info, FBNeo, tosecdev.org, or uploaded) |
| [Hasheous](https://hasheous.org) | optional lookup for files the DATs do not know |


## Licence

AGPL-3.0.
