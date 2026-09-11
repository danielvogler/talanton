"""Candidates, as files in two configured locations.

    <cvs>/anna-mueller.pdf              a CV, put there by anyone
    <assessments>/c-1a2b3c4d.yaml       what the screener made of it

There is no database and no record beyond those two things. A candidate *is* a
CV in the CVs location; the assessment is the only thing this system writes.

The id is derived from the CV's filename, so re-running a screen updates one
assessment rather than accumulating contradictory ones, and "have I already
done this?" is answerable by listing the assessments location. Nothing depends
on an email address — a CV dropped in a folder has none, and that is a
supported way to use this.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import documents, locations
from .config import current
from .locations import Item

ASSESSMENT_SUFFIX = ".yaml"
# Deliberately not .yaml: it sits beside the assessments, and everything that
# reads them filters on that suffix. A marker that looked like an assessment
# would be loaded as one.
REPORT_MARKER = "last-report.json"
ID_PREFIX = "c-"
ID_LENGTH = 16


def cvs(opening: str = "") -> locations.Location:
    """Where CVs are read from, narrowed to one opening's subfolder.

    An opening is a drawer of its own. Without one this is the whole location,
    which is only useful for looking around.
    """
    location = locations.build(current().cvs, current().store)
    return location.child(opening) if opening else location


def assessments(opening: str = "") -> locations.Location:
    """Where assessments are written, narrowed to one opening's subfolder."""
    location = locations.build(current().assessments, current().store)
    return location.child(opening) if opening else location


ID_PATTERN = re.compile(rf"^{ID_PREFIX}[0-9a-f]{{{ID_LENGTH}}}$")


def candidate_id(cv_name: str) -> str:
    """A stable id for the CV of that name.

    Derived from the filename rather than the contents, so a corrected CV
    replacing an earlier one stays the same candidate. It is a hash, so the id
    carries no personal information and is safe to put in an email.

    A file already stored under its id keeps it, rather than being hashed a
    second time. `write_cv` renames on the way in, so most stored names are
    already ids, and hashing an id would produce a different candidate on every
    listing.
    """
    stem = Path(cv_name.strip()).stem
    if ID_PATTERN.match(stem):
        return stem
    digest = hashlib.sha256(cv_name.strip().lower().encode()).hexdigest()
    return f"{ID_PREFIX}{digest[:ID_LENGTH]}"


def write_cv(original_name: str, payload: bytes, opening: str = "") -> Item:
    """Stores one CV under its candidate id, keeping the extension.

    The name a candidate gave their file is usually their own name, and the
    digest carries a link built from wherever the file ended up: a local path,
    a Cloud Storage console URL. Storing `marco-rossi.pdf` means that link
    names Marco in the same message that refuses to name him.

    Only reaches files talanton writes. One dropped into the folder by hand
    keeps whatever it was called, which is why `send_digest` checks the whole
    body it is about to send rather than trusting this.
    """
    suffix = Path(original_name).suffix.lower()
    return cvs(opening).write(f"{candidate_id(original_name)}{suffix}", payload)


# Anything else in the folder is not an application: a stray note, a .DS_Store,
# a spreadsheet someone parked there. Listing it as a candidate would create a
# phantom person, so the location is filtered rather than trusted wholesale.
# Accept what we can read, plus .doc — which is refused with an explanation
# rather than ignored, because an applicant who sent one deserves to be asked
# for a PDF instead of vanishing.
CV_SUFFIXES = (*documents.READABLE_SUFFIXES, *documents.LEGACY_SUFFIXES)


def is_cv(name: str) -> bool:
    """Whether a filename in the CVs location looks like an application."""
    return name.lower().endswith(CV_SUFFIXES) and not name.startswith((".", "_"))


def list_cvs(opening: str = "") -> list[Item]:
    """Every CV waiting for one opening."""
    return [item for item in cvs(opening).list() if is_cv(item.name)]


def read_cv(item: Item, opening: str = "") -> bytes:
    """The bytes of one CV."""
    return cvs(opening).read(item)


def openings() -> locations.Location:
    """Where a published opening is written. Optional, and never read back.

    No per-opening subfolder: one rendered file per opening is the whole
    contents, and a drawer holding a single sheet helps nobody.
    """
    return locations.build(current().openings, current().store)


def assessment_name(candidate: str) -> str:
    return f"{candidate}{ASSESSMENT_SUFFIX}"


def assessed_ids(opening: str = "") -> set[str]:
    """Which candidates already have an assessment, for one opening."""
    return {
        item.name.removesuffix(ASSESSMENT_SUFFIX)
        for item in assessments(opening).list()
        if item.name.endswith(ASSESSMENT_SUFFIX)
    }


def load_assessments(opening: str = "") -> dict[str, dict[str, Any]]:
    """Every assessment for one opening, by candidate id."""
    location = assessments(opening)
    out = {}
    for item in location.list():
        if not item.name.endswith(ASSESSMENT_SUFFIX):
            continue
        parsed = yaml.safe_load(location.read(item).decode("utf-8")) or {}
        out[item.name.removesuffix(ASSESSMENT_SUFFIX)] = {**parsed, "uri": item.uri}
    return out


def assessment(candidate: str, opening: str = "") -> dict[str, Any]:
    """One assessment, or an empty dict if the candidate is unassessed.

    Reads the one file rather than every file. On a local folder the difference
    is invisible; on Drive, loading the whole opening to answer a question
    about one candidate is a download per candidate on file, every lookup, and
    a screening run makes a lot of lookups.
    """
    location = assessments(opening)
    wanted = assessment_name(candidate)
    item = next((i for i in location.list() if i.name == wanted), None)
    if item is None:
        return {}
    parsed = yaml.safe_load(location.read(item).decode("utf-8")) or {}
    return {**parsed, "uri": item.uri}


def save_assessment(candidate: str, data: dict[str, Any], opening: str = "") -> Item:
    """Writes one assessment, replacing any earlier one for that candidate."""
    payload = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode("utf-8")
    return assessments(opening).write(assessment_name(candidate), payload)


def last_reported(opening: str = "") -> set[str]:
    """The candidates the operator had already been told about.

    Empty when no report has gone out yet, which is not the same as a report
    that found nobody — `pool_counts` distinguishes the two so the first mail
    does not announce every application on file as new.
    """
    location = assessments(opening)
    item = next((i for i in location.list() if i.name == REPORT_MARKER), None)
    if item is None:
        return set()
    try:
        parsed = json.loads(location.read(item).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # A corrupt marker must not stop a run. The cost is one report that
        # counts everybody as new, which is noise rather than damage.
        return set()
    return {str(c) for c in parsed.get("candidates", [])}


def record_report(candidates: set[str], opening: str = "") -> Item:
    """Remembers who the operator has now been told about.

    Stored as ids rather than a count, because a count cannot survive a CV
    being withdrawn: the arithmetic would go negative and under-report the
    next run's arrivals.
    """
    payload = json.dumps(
        {"candidates": sorted(candidates), "at": datetime.now(UTC).isoformat()}, indent=2
    ).encode("utf-8")
    return assessments(opening).write(REPORT_MARKER, payload)
