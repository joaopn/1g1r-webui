# 1g1r-webui image: the bundled external tools plus the web app.
# Every tool version is pinned here and reported by docker/tool-versions.sh.

# --- Stage 1: the React front end. Lint, type-check and test before building, so an image
# never ships a front end that fails its own checks. Only dist/ leaves this stage.
FROM node:24-trixie-slim AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npx biome ci . && npx tsc --noEmit && npx vitest run && npm run build

# --- Stage 2: tools and the Python app.
FROM node:24-trixie-slim AS app

ARG IGIR_VERSION=5.8.0
ARG DOLPHIN_TOOL_VERSION=0.2606.2
ARG RETOOL_VERSION=v2.4.9
ARG RETOOL_REPO=https://github.com/unexpectedpanda/retool.git
ARG CLONELISTS_REPO=https://github.com/unexpectedpanda/retool-clonelists-metadata.git
ARG CLONELISTS_COMMIT=0b3ca8be34308e64f136a4c58086fe76a5fd6b2a

# chdman (MAME 0.276) and 7-Zip (binary `7z`, 7-Zip 25.01) from Debian trixie; Python for the app and Retool.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      mame-tools 7zip python3 python3-venv git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# igir reads every archive/disc format natively; dolphin-tool ships prebuilt Linux binaries.
RUN npm install -g --omit=dev "igir@${IGIR_VERSION}" "dolphin-tool@${DOLPHIN_TOOL_VERSION}" \
 && npm cache clean --force

# Retool: CLI only (PySide6 and darkdetect are GUI-only and left out).
RUN git clone --depth 1 --branch "${RETOOL_VERSION}" "${RETOOL_REPO}" /opt/retool \
 && rm -rf /opt/retool/.git \
 && python3 -m venv /opt/retool/venv \
 && /opt/retool/venv/bin/pip install --no-cache-dir \
      "alive-progress>=3.3.0" "lxml>=6.0.2" "psutil>=7.1.3" "strictyaml>=1.7.3" "validators>=0.35.0"

# Retool's clone lists (BSD-3) are not part of its release; pin them by commit.
RUN git init -q /tmp/cl && cd /tmp/cl \
 && git fetch -q --depth 1 "${CLONELISTS_REPO}" "${CLONELISTS_COMMIT}" \
 && git checkout -q FETCH_HEAD \
 && mkdir -p /opt/retool \
 && mv clonelists /opt/retool/clonelists && cp LICENSE /opt/retool/clonelists/LICENSE \
 && echo "${CLONELISTS_COMMIT}" > /opt/retool/clonelists/COMMIT \
 && rm -rf /tmp/cl

COPY docker/tool-versions.sh /usr/local/bin/tool-versions
# Streams a CHD's tracks into their hashes for online lookups (lookups.chd).
COPY docker/chd-hashes.mjs /usr/local/lib/g1r/chd-hashes.mjs
RUN chmod +x /usr/local/bin/tool-versions && tool-versions

# The web app, in its own venv.
COPY pyproject.toml README.md LICENSE /opt/app/
COPY src /opt/app/src
RUN python3 -m venv /opt/app/venv \
 && /opt/app/venv/bin/pip install --no-cache-dir /opt/app \
 && rm -rf /opt/app/src
COPY --from=web-build /web/dist /opt/app/web/dist

# --- Stage 3: the backend tests, run against the image's own tools (igir, chdman, Retool's
# clone lists), which the tests skip or stub elsewhere. Only a marker leaves this stage.
FROM app AS backend-test
COPY pyproject.toml README.md LICENSE /src/
COPY src /src/src
COPY tests /src/tests
RUN /opt/app/venv/bin/pip install --no-cache-dir "/src[dev]" \
 && cd /src && PYTHONDONTWRITEBYTECODE=1 /opt/app/venv/bin/python -m pytest -q -p no:cacheprovider \
 && touch /backend-tests-passed

FROM app
COPY --from=backend-test /backend-tests-passed /opt/app/backend-tests-passed

ENV G1R_DATA_DIR=/data
# The port is set in config (server.port); EXPOSE only documents the default.
EXPOSE 8077
CMD ["/opt/app/venv/bin/python", "-m", "g1r"]
