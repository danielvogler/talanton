"""Applications that did not arrive by mail.

`fetch` reads the apply mailbox. It is the ordinary route and it stays the
ordinary route. But an application can reach a company another way — a batch
downloaded from a job board, a referral handed over as a folder of PDFs — and
before this the only way in was for a person to re-send it to the apply
mailbox.

That round trip works, and it costs the one thing worth keeping: the re-sent
message carries the operator as sender and the forwarding date as the date, so
what gets stored describes the forward rather than the application.

This is deliberately not a way around a single-intake-path policy. It is the
opposite. A labelled import *records* that an application came in by another
route, where a forward into the mailbox hides it. Whether to permit the route
at all is the operator's decision, so it is off until a deployment says
otherwise — see `[intake] import` in the configuration.

Two shapes are understood, and which one a directory uses is read from the
directory rather than guessed:

    jobs-ch/anna-mueller.pdf        a loose file — one candidate
    jobs-ch/marco-rossi/         a folder — one candidate, every document
        cv.pdf                      in it, assessed once on all of them
        references.pdf
        certificates.pdf

Grouping is never inferred from filenames. A scan called an unlabelled scan
belongs to whoever put it in the folder, and no rule over its name could say
so; guessing wrong would file one person's references under another person's
name, which is worse than the split it is meant to fix.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import documents, store
from .config import current

VIA = "import"

# Which document a folder leads with. The whole set is assessed either way, so
# this only decides reading order — the CV should be the first thing read.
CV_HINTS = ("cv", "resume", "résumé", "lebenslauf", "curriculum", "vitae")

ENABLE_WITH = "[intake]\nimport = true"


class IntakeError(RuntimeError):
    """Raised when a directory cannot be read as applications, or may not be."""


@dataclass(frozen=True)
class Application:
    """One person's application, however many files it arrived as."""

    candidate: str
    # What the operator called it: a folder name, or a filename. Reported back
    # so they can match what was imported against what they handed over.
    label: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class Skipped:
    """Something in the directory that was not imported, and why not."""

    name: str
    reason: str


@dataclass(frozen=True)
class Plan:
    """What an import would do. Produced without writing anything."""

    directory: Path
    applications: tuple[Application, ...] = ()
    skipped: tuple[Skipped, ...] = ()


@dataclass(frozen=True)
class Imported:
    candidate: str
    label: str
    documents: int


@dataclass(frozen=True)
class Report:
    """What an import did."""

    imported: tuple[Imported, ...] = ()
    skipped: tuple[Skipped, ...] = ()


def plan(directory: Path) -> Plan:
    """Reads a directory as a set of applications. Writes nothing.

    Safe to run against a deployment that has not enabled importing: an
    operator deciding whether to enable it needs to see what it would do
    first, and looking costs nothing.

    Raises:
        IntakeError: If the directory is not there or is not a directory.
    """
    directory = Path(directory)
    if not directory.exists():
        raise IntakeError(f"no such directory: {directory}")
    if not directory.is_dir():
        raise IntakeError(f"not a directory: {directory}")

    applications: list[Application] = []
    skipped: list[Skipped] = []
    seen: dict[str, str] = {}

    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            _read_folder(entry, applications, skipped)
        else:
            _read_file(entry, applications, skipped, seen)

    return Plan(directory=directory, applications=tuple(applications), skipped=tuple(skipped))


def run(
    plan: Plan,
    opening: str,
    source: str,
    by: str = "",
    dry_run: bool = False,
) -> Report:
    """Writes a plan's applications into the CVs location, with provenance.

    Args:
        plan: What to import, from `plan`.
        opening: The opening these applications are for.
        source: Where they came from — the board or the referrer. Recorded
            against every candidate, and the reason this route exists.
        by: Who ran the import. Recorded when known; left out when not, rather
            than guessed, because a guessed identity in a provenance record is
            worse than an absent one.
        dry_run: Read and report, write nothing.

    Raises:
        IntakeError: If importing is not enabled, or no source was given.
    """
    if not current().intake.allow_import:
        raise IntakeError(
            "importing is not enabled for this deployment. Applications reach the pipeline "
            "through the apply mailbox unless a deployment decides otherwise, which is a "
            f"policy decision and not this command's to make. To permit it, add:\n\n{ENABLE_WITH}"
        )
    if not source.strip():
        raise IntakeError(
            "an import needs a --source: the board or referrer it came from. Recording the "
            "route is the whole reason this exists rather than forwarding the files into the "
            "apply mailbox."
        )

    already = set(store.candidates(opening))
    imported: list[Imported] = []
    skipped = list(plan.skipped)

    for application in plan.applications:
        if application.candidate in already:
            skipped.append(
                Skipped(application.label, f"already imported as {application.candidate}; not written again")
            )
            continue
        if dry_run:
            imported.append(Imported(application.candidate, application.label, len(application.paths)))
            continue
        imported.append(_write(application, opening, source.strip(), by.strip()))

    return Report(imported=tuple(imported), skipped=tuple(skipped))


def _write(application: Application, opening: str, source: str, by: str) -> Imported:
    """Stores one application's documents and the record of how it arrived."""
    written = store.write_documents(
        application.candidate,
        [(path.name, path.read_bytes()) for path in application.paths],
        opening,
    )
    record = {
        "arrived": datetime.now(UTC).date().isoformat(),
        "via": VIA,
        "source": source,
        "documents": [item.name for item in written],
    }
    store.write_provenance(application.candidate, {**record, "by": by} if by else record, opening)
    logging.info("Imported %s (%d document(s)) from %s", application.candidate, len(written), source)
    return Imported(application.candidate, application.label, len(written))


def _read_folder(folder: Path, applications: list[Application], skipped: list[Skipped]) -> None:
    """One folder is one candidate, and one level deep is all there is."""
    if any(child.is_dir() for child in folder.iterdir()):
        skipped.append(
            Skipped(
                folder.name,
                "holds a folder of its own, and an application is one level deep. Flattening it "
                "would file one person's documents under another person's name.",
            )
        )
        return

    usable, rejected = _usable(sorted(folder.iterdir()))
    skipped.extend(rejected)
    if not usable:
        skipped.append(Skipped(folder.name, "holds no documents that can be read as an application"))
        return

    applications.append(
        Application(
            candidate=store.candidate_id(folder.name),
            label=folder.name,
            paths=tuple(sorted(usable, key=_reading_order)),
        )
    )


def _read_file(
    path: Path, applications: list[Application], skipped: list[Skipped], seen: dict[str, str]
) -> None:
    """A loose file is one candidate, unless it is a copy of one already read."""
    usable, rejected = _usable([path])
    skipped.extend(rejected)
    if not usable:
        return

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest in seen:
        # A board's download button pressed twice leaves `cv.pdf` and
        # `cv (1).pdf`. Two candidates out of one person is the same phantom
        # this whole command exists to avoid.
        skipped.append(Skipped(path.name, f"byte for byte identical to {seen[digest]}; one candidate"))
        return

    seen[digest] = path.name
    applications.append(Application(candidate=store.candidate_id(path.name), label=path.name, paths=(path,)))


def _usable(paths: list[Path]) -> tuple[list[Path], list[Skipped]]:
    """The files that can be stored as documents, and why the others cannot."""
    usable, skipped = [], []
    for path in paths:
        if not path.is_file() or path.name.startswith("."):
            continue
        if not store.is_cv(path.name):
            skipped.append(Skipped(path.name, "not a document this can read; not imported"))
            continue
        size = path.stat().st_size
        if size > documents.MAX_DOCUMENT_BYTES:
            skipped.append(
                Skipped(
                    path.name,
                    f"{size / 1024 / 1024:.1f} MB is larger than any CV needs to be "
                    f"(the ceiling is {documents.MAX_DOCUMENT_BYTES // 1024 // 1024} MB); "
                    "not imported. Ask for a smaller file.",
                )
            )
            continue
        usable.append(path)
    return usable, skipped


def _reading_order(path: Path) -> tuple[int, str]:
    """Whichever document says it is the CV is read first, then the rest."""
    lowered = path.name.lower()
    return (0 if any(hint in lowered for hint in CV_HINTS) else 1, lowered)
