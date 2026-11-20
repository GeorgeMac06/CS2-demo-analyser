#!/usr/bin/env bash
# Fails when a branch adds what must never reach this public repo:
#   - demo files, or anything under tests/local_fixtures/;
#   - a line with a real-looking SteamID64 (7656119 then 7, 8 or 9, then 9 digits).
# Only lines the branch adds are checked. A made-up ID in a test can stay if its line
# also says "hygiene: allow". The log names the file and line, never the number itself.
#
# Usage: hygiene.sh <base-ref>     for example: hygiene.sh origin/main
set -euo pipefail

base="${1:?usage: hygiene.sh <base-ref>}"
fail=0

added_files=$(git diff --name-only --diff-filter=ACR "$base"...HEAD)
bad_files=$(printf '%s\n' "$added_files" \
    | grep -E '(\.dem(\.(gz|bz2|zst))?|\.zip)$|^tests/local_fixtures/' || true)
if [ -n "$bad_files" ]; then
    echo "::error::Demos, archives or local fixtures must not be committed:"
    printf '%s\n' "$bad_files" | sed 's/^/  /'
    fail=1
fi

id_hits=$(git diff -U0 "$base"...HEAD | awk '
    /^\+\+\+ / { file = substr($0, 7); next }
    /^@@ / { split($3, a, ","); line = substr(a[1], 2) + 0; next }
    /^\+/ {
        if ($0 ~ /7656119[789][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]/ \
            && $0 !~ /hygiene: allow/) print "  " file ":" line
        line++
    }
')
if [ -n "$id_hits" ]; then
    echo "::error::Real-looking SteamIDs added. Remove them, or mark a made-up one with 'hygiene: allow':"
    echo "$id_hits"
    fail=1
fi

if [ "$fail" -eq 0 ]; then
    echo "Hygiene: no demos, local fixtures or real-looking SteamIDs added."
fi
exit "$fail"
