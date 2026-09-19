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
import logging
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from . import documents, locations
from .config import current
from .locations import Item, LocationError

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


# A candidate's documents, stored flat beside each other:
#
#     c-1a2b3c4d.pdf      the first, named exactly as a lone CV always was
#     c-1a2b3c4d.d2.pdf   the second
#
# Flat rather than a folder per candidate because a location is a flat list of
# files — Drive and GCS both answer `list` that way — and a folder each would
# cost a round trip per candidate on every listing.
STORED_NAME = re.compile(rf"^({ID_PREFIX}[0-9a-f]{{{ID_LENGTH}}})(?:\.d([2-9]|[1-9][0-9]+))?$")
FIRST_DOCUMENT = 1
# Beside the CVs rather than among the assessments: it describes the arrival,
# not the judgement. The suffix keeps it out of `is_cv`, so it can never be
# listed as an application.
PROVENANCE_SUFFIX = ".provenance.yaml"


def candidate_id(cv_name: str) -> str:
    """A stable id for the CV of that name.

    Derived from the filename rather than the contents, so a corrected CV
    replacing an earlier one stays the same candidate. It is a hash, so the id
    carries no personal information and is safe to put in an email.

    A file already stored under its id keeps it, rather than being hashed a
    second time — including a numbered second or third document, which belongs
    to the candidate the number hangs off rather than to one of its own.
    `write_documents` renames on the way in, so most stored names are already
    ids, and hashing an id would produce a different candidate on every listing.
    """
    stored = STORED_NAME.match(Path(cv_name.strip()).stem)
    if stored:
        return stored.group(1)
    digest = hashlib.sha256(cv_name.strip().lower().encode()).hexdigest()
    return f"{ID_PREFIX}{digest[:ID_LENGTH]}"


def document_ordinal(stored_name: str) -> int:
    """Which of a candidate's documents a stored file is. 1 unless numbered."""
    stored = STORED_NAME.match(Path(stored_name.strip()).stem)
    if stored and stored.group(2):
        return int(stored.group(2))
    return FIRST_DOCUMENT


def document_name(candidate: str, ordinal: int, suffix: str) -> str:
    """What a candidate's nth document is stored as.

    The first is unnumbered, so every CV stored before a candidate could hold
    more than one document keeps the name it already has — and keeps the
    assessment that is keyed to it.
    """
    if ordinal <= FIRST_DOCUMENT:
        return f"{candidate}{suffix}"
    return f"{candidate}.d{ordinal}{suffix}"


def write_documents(candidate: str, documents: Sequence[tuple[str, bytes]], opening: str = "") -> list[Item]:
    """Stores one application's documents under one candidate id.

    The order given is the order they are stored and the order the screener
    reads them in, so whichever document is the CV belongs first.

    The names applicants give their files are usually their own, and the digest
    carries a link built from wherever the file ended up: a local path, a Drive
    URL. Storing `marco-rossi.pdf` means that link names Marco in the same
    message that refuses to name him. So the original name is used to pick the
    extension and for nothing else.

    Only reaches files talanton writes. One dropped into the folder by hand
    keeps whatever it was called, which is why `send_digest` checks the whole
    body it is about to send rather than trusting this.
    """
    location = cvs(opening)
    # Writing over a candidate who already has documents is how one applicant
    # replaces another without anyone noticing. It is legitimate — a re-read of
    # the same message, a corrected file — but it is never routine, and a bug in
    # whatever derives the id shows up here first and nowhere else.
    existing = documents_for(candidate, opening)
    if existing:
        logging.warning(
            "%s already has %d document(s) in opening %r; writing over them. If this candidate is "
            "not the same application, whatever produced the id has merged two people.",
            candidate,
            len(existing),
            opening,
        )
    return [
        location.write(document_name(candidate, ordinal, Path(original).suffix.lower()), payload)
        for ordinal, (original, payload) in enumerate(documents, start=FIRST_DOCUMENT)
    ]


def write_cv(original_name: str, payload: bytes, opening: str = "") -> Item:
    """Stores one document as a candidate of its own, under its candidate id."""
    return write_documents(candidate_id(original_name), [(original_name, payload)], opening)[0]


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


def candidates(opening: str = "") -> dict[str, list[Item]]:
    """Every candidate waiting for one opening, with their documents in order.

    An application is not a file. Someone who sends a CV, a covering letter and
    a scan of their certificates has applied once, and counting that as three
    candidates puts two people in the pool who do not exist — one of whom
    scores near zero on every rubric dimension, because a certificate is not a
    CV.
    """
    grouped: dict[str, list[Item]] = {}
    for item in list_cvs(opening):
        grouped.setdefault(candidate_id(item.name), []).append(item)
    return {
        candidate: sorted(items, key=lambda i: document_ordinal(i.name)) for candidate, items in grouped.items()
    }


def documents_for(candidate: str, opening: str = "") -> list[Item]:
    """One candidate's documents, in the order they are to be read."""
    return candidates(opening).get(candidate, [])


def provenance_name(candidate: str) -> str:
    return f"{candidate}{PROVENANCE_SUFFIX}"


def write_provenance(candidate: str, record: dict[str, Any], opening: str = "") -> Item:
    """Records how one application reached the pipeline, and when.

    The stated reason for a single intake path is that every candidate is
    logged, timed and screened the same way, so a decision can be justified
    later. Without this, nothing persisted supports the "timed" part: given a
    stored CV there is no way to say when it was received or by which route,
    and an application forwarded into the apply mailbox by an operator is byte
    for byte identical to one the candidate sent themselves.
    """
    payload = yaml.safe_dump(dict(record), sort_keys=False, allow_unicode=True).encode("utf-8")
    return cvs(opening).write(provenance_name(candidate), payload)


def provenances(opening: str = "") -> dict[str, dict[str, Any]]:
    """Every candidate's arrival record for one opening, from ONE listing.

    The singular form lists the location to find one file, which is right when
    one candidate is the question. Asking it for a whole pool is a listing per
    candidate — a round trip each on Drive, and the reconciliation this record
    exists for is precisely the loop over everybody. On a pool of 72 that did
    not finish; this returns in one listing plus one read per record.

    Candidates with no record are absent rather than present-and-empty, so a
    caller can tell "arrived before this was recorded" from "arrived by an
    unknown route".
    """
    location = cvs(opening)
    out: dict[str, dict[str, Any]] = {}
    for item in location.list():
        if not item.name.endswith(PROVENANCE_SUFFIX):
            continue
        candidate = item.name.removesuffix(PROVENANCE_SUFFIX)
        parsed = _read_provenance(location, item, candidate)
        if parsed is not None:
            out[candidate] = parsed
    return out


def _read_provenance(location: locations.Location, item: Item, candidate: str) -> dict[str, Any] | None:
    """One record, or None if it cannot be read. A damaged one is not fatal."""
    try:
        parsed = yaml.safe_load(location.read(item).decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, LocationError):
        logging.warning("Could not read the provenance record for %s; treating it as absent", candidate)
        return None
    return parsed if isinstance(parsed, dict) else None


def provenance(candidate: str, opening: str = "") -> dict[str, Any]:
    """What is known about one application's arrival, or an empty dict.

    Empty is an ordinary answer: every CV stored before this record existed has
    none, and those candidates still have to be assessable.
    """
    location = cvs(opening)
    wanted = provenance_name(candidate)
    item = next((i for i in location.list() if i.name == wanted), None)
    if item is None:
        return {}
    # A damaged record must not stop an assessment. The cost is one candidate
    # whose route is unknown, which is what it was before the record existed.
    return _read_provenance(location, item, candidate) or {}


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
