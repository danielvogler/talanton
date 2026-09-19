"""`talanton import` — applications that did not arrive by mail.

A batch downloaded from a job board has to reach the pipeline somehow. Before
this, the only way in was for a person to re-send it to the apply mailbox,
which works but costs what little provenance there was: the forward carries the
operator as sender and the forwarding date as the date, so the store ends up
describing the forward rather than the application.

This is not a way around a single-intake-path policy. It is the opposite — a
labelled import records that an application came in by another route, where a
forward into the mailbox hides it.
"""

from pathlib import Path

import pytest

from talanton import config, intake, store, tools
from tests.conftest import OPENING

LONG = "Ten years shipping production systems. " * 8


@pytest.fixture
def enabled(configure):
    """Import is opt-in. Most of these tests need it switched on."""
    configure(intake=config.Intake(allow_import=True))


@pytest.fixture
def batch(tmp_path):
    """Builds a directory of files the way a board download leaves one."""

    def _batch(layout: dict[str, str | dict], name="jobs-ch") -> Path:
        root = tmp_path / "intake" / name
        root.mkdir(parents=True, exist_ok=True)
        for key, value in layout.items():
            if isinstance(value, dict):
                folder = root / key
                folder.mkdir(parents=True, exist_ok=True)
                for inner, text in value.items():
                    (folder / inner).write_text(text, encoding="utf-8")
                continue
            (root / key).write_text(value, encoding="utf-8")
        return root

    return _batch


# --------------------------------------------------------------------------
# What a directory means. Read-only: `plan` writes nothing.
# --------------------------------------------------------------------------


def test_a_loose_file_is_one_candidate(batch):
    plan = intake.plan(batch({"anna.txt": f"{LONG} Anna.", "bruno.txt": f"{LONG} Bruno."}))
    assert len(plan.applications) == 2


def test_a_subfolder_is_one_candidate_however_many_documents_it_holds(batch):
    """The case this exists for: one applicant who sent a CV, their
    certificates and their references."""
    plan = intake.plan(
        batch({"marco-rossi": {"cv.txt": LONG, "certificates.txt": LONG, "references.txt": LONG}})
    )
    assert len(plan.applications) == 1
    assert len(plan.applications[0].paths) == 3


def test_loose_files_and_subfolders_mix_in_one_directory(batch):
    """One board sends a file per applicant, another sends folders. Neither
    should need its own command."""
    plan = intake.plan(batch({"anna.txt": f"{LONG} Anna.", "marco": {"cv.txt": LONG}}))
    assert len(plan.applications) == 2


def test_a_subfolders_candidate_id_comes_from_the_folder_name(batch):
    """So a re-run lands on the same candidate rather than a second one."""
    first = intake.plan(batch({"marco": {"cv.txt": LONG}}))
    assert first.applications[0].candidate == store.candidate_id("marco")


def test_the_cv_is_read_first_when_a_folder_says_which_it_is(batch):
    plan = intake.plan(batch({"marco": {"zertifikate.txt": LONG, "cv-marco.txt": LONG}}))
    assert plan.applications[0].paths[0].name == "cv-marco.txt"


def test_a_file_that_is_not_a_document_is_skipped_with_a_reason(batch):
    plan = intake.plan(batch({"anna.txt": LONG, "notes.xlsx": "not a CV"}))
    assert [s.name for s in plan.skipped] == ["notes.xlsx"]
    assert "not a document" in plan.skipped[0].reason


def test_an_empty_subfolder_is_skipped_rather_than_becoming_a_candidate(batch):
    plan = intake.plan(batch({"marco": {}}))
    assert plan.applications == ()
    assert plan.skipped[0].name == "marco"


def test_a_folder_inside_a_folder_is_refused_rather_than_flattened(batch, tmp_path):
    """Flattening would silently put one person's documents under another's
    name, which is worse than the split it is meant to fix."""
    root = batch({"marco": {"cv.txt": LONG}})
    (root / "marco" / "older").mkdir()
    (root / "marco" / "older" / "cv-2019.txt").write_text(LONG, encoding="utf-8")
    plan = intake.plan(root)
    assert plan.applications == ()
    assert "one level" in plan.skipped[0].reason


def test_two_byte_identical_files_are_one_candidate_not_two(batch):
    """A board's download button pressed twice leaves `cv.pdf` and
    `cv (1).pdf`. They are one person."""
    plan = intake.plan(batch({"anna.txt": LONG, "anna (1).txt": LONG}))
    assert len(plan.applications) == 1
    assert "identical" in plan.skipped[0].reason


def test_a_missing_directory_says_so_rather_than_importing_nothing(tmp_path):
    with pytest.raises(intake.IntakeError, match="no such directory"):
        intake.plan(tmp_path / "not-there")


def test_a_document_over_the_ceiling_is_refused_and_named(batch):
    from talanton import documents

    plan = intake.plan(batch({"huge.txt": "x" * (documents.MAX_DOCUMENT_BYTES + 1)}))
    assert plan.applications == ()
    assert "larger than" in plan.skipped[0].reason


# --------------------------------------------------------------------------
# Writing it. This is the part that spends storage and touches the pool.
# --------------------------------------------------------------------------


def test_importing_puts_the_documents_in_the_cvs_location(position, enabled, batch):
    report = intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch")
    assert report.imported[0].documents == 1
    assert len(store.list_cvs(OPENING)) == 1


def test_an_imported_application_is_one_piece_of_work_in_the_queue(position, enabled, batch):
    intake.run(
        intake.plan(batch({"marco": {"cv.txt": LONG, "refs.txt": LONG, "certs.txt": LONG}})),
        OPENING,
        source="jobs-ch",
    )
    assert tools.list_new_cvs(OPENING)["count"] == 1


def test_the_stored_documents_do_not_carry_the_applicants_name(position, enabled, batch):
    """A hand-dropped file keeps its name, and the CV link then carries it into
    a shortlist designed never to name anybody. Import renames, as fetch does."""
    intake.run(intake.plan(batch({"anna-mueller.txt": LONG})), OPENING, source="jobs-ch")
    assert not any("anna" in item.name.lower() for item in store.list_cvs(OPENING))


def test_the_route_and_the_source_are_recorded(position, enabled, batch):
    report = intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch")
    record = store.provenance(report.imported[0].candidate, OPENING)
    assert record["via"] == "import"
    assert record["source"] == "jobs-ch"
    assert record["arrived"]


def test_who_ran_the_import_is_recorded_when_it_is_known(position, enabled, batch):
    report = intake.run(
        intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch", by="daniel@example.com"
    )
    assert store.provenance(report.imported[0].candidate, OPENING)["by"] == "daniel@example.com"


def test_the_documents_are_listed_in_the_record(position, enabled, batch):
    report = intake.run(
        intake.plan(batch({"marco": {"cv.txt": LONG, "refs.txt": LONG}})), OPENING, source="jobs-ch"
    )
    record = store.provenance(report.imported[0].candidate, OPENING)
    assert len(record["documents"]) == 2


def test_importing_the_same_directory_twice_does_not_duplicate_anyone(position, enabled, batch):
    directory = batch({"anna.txt": LONG})
    intake.run(intake.plan(directory), OPENING, source="jobs-ch")
    again = intake.run(intake.plan(directory), OPENING, source="jobs-ch")
    assert again.imported == ()
    assert "already" in again.skipped[0].reason
    assert tools.list_new_cvs(OPENING)["count"] == 1


def test_a_dry_run_writes_nothing(position, enabled, batch):
    intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch", dry_run=True)
    assert store.list_cvs(OPENING) == []


def test_a_source_is_required_because_that_is_the_whole_point(position, enabled, batch):
    with pytest.raises(intake.IntakeError, match="source"):
        intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="  ")


# --------------------------------------------------------------------------
# Whether to have this route at all is the operator's decision, not the tool's.
# --------------------------------------------------------------------------


def test_import_is_off_unless_a_deployment_turns_it_on(position, batch):
    with pytest.raises(intake.IntakeError, match=r"\[intake\]"):
        intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch")


def test_the_refusal_names_the_line_that_would_enable_it(position, batch):
    with pytest.raises(intake.IntakeError, match="import = true"):
        intake.run(intake.plan(batch({"anna.txt": LONG})), OPENING, source="jobs-ch")


def test_planning_is_allowed_even_when_importing_is_not(batch):
    """Looking at a directory spends nothing and changes nothing, and an
    operator deciding whether to enable this needs to see what it would do."""
    assert intake.plan(batch({"anna.txt": LONG})).applications
