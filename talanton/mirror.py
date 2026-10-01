"""One file that mirrors a folder of small records, so reading them all is one read.

An opening's assessments are a hundred small files, and on Drive each is a
download of its own: a shortlist over a slow link spent half an hour reading
what fits in one file. The mirror is that one file.

It is a cache and never the record. Each row carries the version of the file
it came from, as the listing reports it, and a row is used only while that
version still matches. So a file that changed is read again, a file that went
away drops out, and a row lost because two runs wrote the mirror at once is
simply missing — read again next time, never wrong. Nothing needs a lock.
"""

import json
import logging
import time
from collections.abc import Callable
from typing import Any

from .locations import Item, Location, LocationError

# Bumped when a row's shape changes, so an old mirror is rebuilt rather than
# misread.
FORMAT = 1

# How often a read of many files says how far it got: every so many files, or
# after this long without a line, whichever comes first. On a link that drops
# connections ten reads can take minutes, and a silent log cannot tell a slow
# run from a stuck one.
PROGRESS_EVERY = 10
PROGRESS_SECONDS = 5.0

Parse = Callable[[Item, bytes], dict[str, Any] | None]


class Progress:
    """Counts one read of many files up to its total, logging as it goes."""

    def __init__(self, what: str, total: int) -> None:
        self.what, self.total, self.done = what, total, 0
        self.said_at = time.monotonic()

    def tick(self) -> None:
        self.done += 1
        now = time.monotonic()
        if self.done == self.total or self.done % PROGRESS_EVERY == 0 or now - self.said_at >= PROGRESS_SECONDS:
            logging.info("%s: %d/%d read", self.what, self.done, self.total)
            self.said_at = now


def records(
    source: Location,
    select: Callable[[str], bool],
    parse: Parse,
    *,
    mirror: Location | None = None,
    name: str,
    what: str,
    only: set[str] | None = None,
) -> dict[str, tuple[Item, dict[str, Any]]]:
    """Every selected file in `source`, by name, read through the mirror.

    `mirror` is where the mirror file lives, when that is not `source` itself.
    `only` narrows what is returned and read to those names; the mirror still
    keeps its rows for everything else that is listed. A file `parse` cannot
    use (it returns None) is left out, as it was before there was a mirror.
    """
    listed = source.list()
    home = mirror or source
    mirror_listing = listed if mirror is None else mirror.list()
    present = {item.name: item for item in listed if select(item.name)}
    saved = _load(home, mirror_listing, name)

    wanted = present if only is None else {n: i for n, i in present.items() if n in only}
    out: dict[str, tuple[Item, dict[str, Any]]] = {}
    stale: list[Item] = []
    for file_name, item in wanted.items():
        row = saved.get(file_name)
        if item.version and row and row.get("version") == item.version:
            out[file_name] = (item, row["data"])
        else:
            stale.append(item)

    fresh: dict[str, dict[str, Any]] = {}
    if stale:
        progress = Progress(what, len(stale))
        for item in stale:
            parsed = parse(item, source.read(item))
            progress.tick()
            if parsed is None:
                continue
            # As the mirror will hand it back next time: a YAML date read
            # straight from the file would otherwise come back as a string
            # only on the runs that happened to hit the mirror.
            parsed = json.loads(json.dumps(parsed, ensure_ascii=False, default=str))
            out[item.name] = (item, parsed)
            if item.version:
                fresh[item.name] = {"version": item.version, "data": parsed}

    rows = {n: row for n, row in saved.items() if n in present} | fresh
    if rows != saved:
        _save(home, name, rows)
    return out


def _load(mirror: Location, listing: list[Item], name: str) -> dict[str, dict[str, Any]]:
    """The mirror's rows, or none if it is absent, damaged or another format."""
    item = next((i for i in listing if i.name == name), None)
    if item is None:
        return {}
    try:
        parsed = json.loads(mirror.read(item).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, LocationError):
        logging.warning("Could not read the mirror %s; rebuilding it", name)
        return {}
    if (
        not isinstance(parsed, dict)
        or parsed.get("format") != FORMAT
        or not isinstance(parsed.get("rows"), dict)
    ):
        return {}
    return {n: row for n, row in parsed["rows"].items() if isinstance(row, dict) and "data" in row}


def _save(mirror: Location, name: str, rows: dict[str, dict[str, Any]]) -> None:
    """Writes the mirror. Failing to is not fatal: the next read rebuilds it."""
    payload = json.dumps({"format": FORMAT, "rows": rows}, ensure_ascii=False, default=str).encode("utf-8")
    try:
        mirror.write(name, payload)
    except LocationError as exc:
        logging.warning("Could not write the mirror %s (%s); the next run reads the files again", name, exc)
