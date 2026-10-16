#!/bin/sh
# Print the version of every bundled external tool; exit non-zero if any is missing.
set -u
status=0
check() {
  name=$1; shift
  if out=$("$@" 2>&1); then
    printf '%-13s %s\n' "$name" "$(printf '%s\n' "$out" | grep -m1 -v '^$' | sed 's/\x1b\[[0-9;]*m//g')"
  else
    printf '%-13s MISSING (%s)\n' "$name" "$*"
    status=1
  fi
}
check chdman      sh -c 'chdman 2>&1 | head -n1 | grep -i chdman'
check 7z          sh -c '7z 2>&1 | grep -m1 "7-Zip"'
check igir        sh -c 'igir --help 2>&1 | grep -m1 -o "v[0-9][0-9.]* (Node.js [^)]*)"'
check dolphin-tool sh -c 'dolphin-tool 2>&1 | grep -q -i usage && npm ls -g --depth=0 dolphin-tool 2>/dev/null | grep -m1 -o "dolphin-tool@[0-9.]*"'
check node        node --version
check python3     python3 --version
check retool      sh -c 'cd /opt/retool && /opt/retool/venv/bin/python retool.py --help 2>&1 | grep -m1 -i retool'
exit $status
