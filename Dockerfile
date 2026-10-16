# 1g1r-webui image: the bundled external tools plus the web app.
# Every tool version is pinned here and reported by docker/tool-versions.sh.

FROM node:24-trixie-slim

ARG IGIR_VERSION=5.7.2
ARG DOLPHIN_TOOL_VERSION=0.2606.2
ARG RETOOL_VERSION=v2.4.9
ARG RETOOL_REPO=https://github.com/unexpectedpanda/retool.git

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

COPY docker/tool-versions.sh /usr/local/bin/tool-versions
RUN chmod +x /usr/local/bin/tool-versions && tool-versions

# The web app, in its own venv.
COPY pyproject.toml README.md LICENSE /opt/app/
COPY src /opt/app/src
RUN python3 -m venv /opt/app/venv \
 && /opt/app/venv/bin/pip install --no-cache-dir /opt/app \
 && rm -rf /opt/app/src

ENV G1R_DATA_DIR=/data
# The port is set in config (server.port); EXPOSE only documents the default.
EXPOSE 8080
CMD ["/opt/app/venv/bin/python", "-m", "g1r"]
