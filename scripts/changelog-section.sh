#!/usr/bin/env bash
# Print one version's section of CHANGELOG.md, and fail if it has none.
#
# Two callers need the same answer for different reasons, which is why this is
# a script rather than a grep in each: the release workflow refuses to publish
# a tag whose version has no changelog entry, and the GitHub release it then
# creates uses that entry as its notes. A version whose notes are checked in
# one place and rendered in another is a version whose notes drift.
#
# Usage: scripts/changelog-section.sh 0.7.1 [path/to/CHANGELOG.md]
set -euo pipefail

version="${1:-}"
changelog="${2:-CHANGELOG.md}"

if [ -z "$version" ]; then
  echo "usage: scripts/changelog-section.sh <version> [changelog]" >&2
  exit 2
fi

if [ ! -f "$changelog" ]; then
  echo "no such file: $changelog" >&2
  exit 2
fi

# Everything between this version's heading and whatever ends the section: the
# next `## ` heading, or — for the oldest version, which has none after it —
# the block of `[0.6.0]: https://...` link definitions at the foot of the file.
# Without that second stop the last release's notes end in a list of URLs.
section=$(
  awk -v heading="## [$version]" '
    index($0, heading) == 1 { found = 1; next }
    found && /^## / { exit }
    found && /^\[[^]]+\]: / { exit }
    found { print }
  ' "$changelog"
)

# Trim the blank lines the heading and the next one leave behind.
section=$(printf '%s\n' "$section" | sed -e '/./,$!d' | sed -e :a -e '/^\n*$/{$d;N;};/\n$/ba')

if [ -z "$section" ]; then
  echo "$changelog has no '## [$version]' section, or it is empty" >&2
  exit 1
fi

printf '%s\n' "$section"
