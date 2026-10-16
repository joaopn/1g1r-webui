# 1g1r-webui

A web UI for tidying ROM folders, one platform per folder: lossless conversion to the format your emulator plays, then checksum matching against DATs and one-game-one-ROM selection, reviewed in a table before anything is applied. Discarded files are moved, never deleted, and every reversible operation can be undone.

Status: early development, read-only. The app skeleton runs; platforms, DATs and matching arrive in the next builds.

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
