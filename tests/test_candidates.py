"""A candidate may hold more than one document.

An application is not a file. Somebody who sends a CV, a covering letter and
a scan of their certificates has made one application, and splitting it into
three candidates puts two people in the pool who do not exist — one of whom
scores near zero on every rubric dimension, because a certificate is not a CV.
"""

import pytest

from talanton import documents, store, tools
from tests.conftest import OPENING

LONG = "Ten years shipping production systems. " * 8
OTHER = "References from three previous employers. " * 8


@pytest.fixture
def written():
    """Stores one candidate's documents. Returns the candidate id."""

    def _written(*names, opening=OPENING, text=LONG):
        candidate = store.candidate_id(names[0])
        store.write_documents(
            candidate,
            [(name, f"{text} ({name})".encode()) for name in names],
            opening,
        )
        return candidate

    return _written


# --------------------------------------------------------------------------
# Naming: several documents, one id, and the id still derivable from the name.
# --------------------------------------------------------------------------


def test_the_first_document_keeps_the_name_a_single_document_candidate_has():
    """Every CV already on a company's drive is named this way. A change here
    would orphan them from their assessments."""
    written = store.write_documents("c-" + "a" * 16, [("cv.pdf", b"x")], OPENING)
    assert written[0].name == "c-" + "a" * 16 + ".pdf"


def test_further_documents_are_numbered_beside_the_first(written):
    candidate = written("cv.txt", "letter.txt", "certificates.txt")
    assert [i.name for i in store.documents_for(candidate, OPENING)] == [
        f"{candidate}.txt",
        f"{candidate}.d2.txt",
        f"{candidate}.d3.txt",
    ]


def test_every_document_resolves_to_the_same_candidate(written):
    candidate = written("cv.txt", "letter.txt", "certificates.txt")
    assert {store.candidate_id(i.name) for i in store.documents_for(candidate, OPENING)} == {candidate}


def test_a_numbered_document_is_not_hashed_a_second_time():
    """`candidate_id` is called on stored names all over the tool. Hashing one
    would invent a new candidate on every listing."""
    candidate = "c-" + "b" * 16
    assert store.candidate_id(f"{candidate}.d7.pdf") == candidate


def test_documents_keep_their_own_extensions(written):
    candidate = written("cv.pdf", "notes.txt")
    assert [i.name for i in store.documents_for(candidate, OPENING)] == [
        f"{candidate}.pdf",
        f"{candidate}.d2.txt",
    ]


# --------------------------------------------------------------------------
# The queue: three documents are one piece of work, not three.
# --------------------------------------------------------------------------


def test_one_application_with_three_documents_is_one_candidate(position, written):
    written("cv.txt", "cover-letter.txt", "certificates.txt")
    assert tools.list_new_cvs(OPENING)["count"] == 1


def test_the_queue_offers_the_first_document_as_the_handle(position, written):
    candidate = written("cv.txt", "cover-letter.txt")
    [row] = tools.list_new_cvs(OPENING)["waiting"]
    assert row["candidate"] == candidate
    assert row["cv"] == f"{candidate}.txt"


def test_assessing_it_once_takes_it_off_the_queue(position, assessed, written):
    candidate = written("cv.txt", "cover-letter.txt")
    store.save_assessment(candidate, {"overall": 7.0}, OPENING)
    assert tools.list_new_cvs(OPENING)["count"] == 0


# --------------------------------------------------------------------------
# Reading: assessed once, on all of them.
# --------------------------------------------------------------------------


def test_the_text_of_every_document_is_put_to_the_screener(position, written):
    candidate = written("cv.txt", "references.txt")
    text = tools.get_cv_text(OPENING, f"{candidate}.txt")["cv"]
    assert "(cv.txt)" in text
    assert "(references.txt)" in text


def test_each_document_is_announced_so_a_reader_knows_what_they_are_looking_at(position, written):
    candidate = written("cv.txt", "references.txt")
    text = tools.get_cv_text(OPENING, f"{candidate}.txt")["cv"]
    assert "document 1 of 2" in text
    assert "document 2 of 2" in text


def test_a_single_document_candidate_gets_no_document_headings(position, cv):
    """The overwhelming case is one CV. It should read exactly as it did."""
    name = cv()
    assert "document 1 of" not in tools.get_cv_text(OPENING, name)["cv"]


def test_one_unreadable_document_does_not_lose_the_others(position, written):
    candidate = written("cv.txt")
    store.cvs(OPENING).write(f"{candidate}.d2.pdf", b"%PDF-1.4 not really")
    result = tools.get_cv_text(OPENING, f"{candidate}.txt")
    assert "(cv.txt)" in result["cv"]
    assert "could not be read" in result["cv"]


def test_a_candidate_whose_documents_are_all_unreadable_is_unreadable(position):
    candidate = store.candidate_id("scan.pdf")
    store.write_documents(candidate, [("scan.pdf", b"%PDF-1.4 no text layer")], OPENING)
    assert tools.get_cv_text(OPENING, f"{candidate}.pdf")["unreadable"]


def test_the_reported_document_count_matches_what_was_read(position, written):
    candidate = written("cv.txt", "references.txt", "certificates.txt")
    assert tools.get_cv_text(OPENING, f"{candidate}.txt")["documents"] == 3


# --------------------------------------------------------------------------
# Provenance: where an application came from, and when.
# --------------------------------------------------------------------------


def test_a_provenance_record_survives_a_round_trip():
    store.write_provenance("c-" + "c" * 16, {"via": "import", "source": "jobs-ch"}, OPENING)
    assert store.provenance("c-" + "c" * 16, OPENING)["source"] == "jobs-ch"


def test_a_provenance_record_is_not_mistaken_for_an_application(position):
    """It sits beside the CVs. Listed as one, it would be a candidate who does
    not exist, and `unreadable` is what the operator would be told about them."""
    store.write_provenance("c-" + "d" * 16, {"via": "import"}, OPENING)
    assert store.list_cvs(OPENING) == []
    assert tools.list_new_cvs(OPENING)["count"] == 0


def test_a_candidate_with_no_provenance_reads_as_empty_rather_than_failing():
    """Every CV stored before this existed has none, and they still have to
    be assessable."""
    assert store.provenance("c-" + "e" * 16, OPENING) == {}


def test_documents_too_large_to_read_are_refused_by_the_same_ceiling(position):
    """The CVs folder is not a file share. `documents` already applies this to
    anything it is handed; storing past it would only defer the failure."""
    candidate = store.candidate_id("huge.pdf")
    store.write_documents(candidate, [("huge.pdf", b"x" * (documents.MAX_DOCUMENT_BYTES + 1))], OPENING)
    assert tools.get_cv_text(OPENING, f"{candidate}.pdf")["unreadable"]


# --------------------------------------------------------------------------
# Reading provenance for a whole pool. The per-candidate accessor lists the
# location once per candidate, which is a round trip each on Drive — so the
# reconciliation the record exists for is the one call that does not finish.
# --------------------------------------------------------------------------


def test_every_candidates_arrival_comes_back_at_once(position, written):
    first = written("cv.txt")
    second = written("other.txt")
    store.write_provenance(first, {"via": "import", "source": "a-board"}, OPENING)
    store.write_provenance(second, {"via": "mailbox", "source": "someone@example.test"}, OPENING)
    records = store.provenances(OPENING)
    assert records[first]["source"] == "a-board"
    assert records[second]["via"] == "mailbox"


def test_it_costs_one_listing_however_many_candidates(position, written, monkeypatch):
    """The whole point. One listing, not one per candidate."""
    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        candidate = written(name)
        store.write_provenance(candidate, {"via": "import"}, OPENING)

    location = store.cvs(OPENING)
    listings = {"count": 0}
    original = location.list

    def _counted():
        listings["count"] += 1
        return original()

    monkeypatch.setattr(store, "cvs", lambda opening="": _Recording(location, listings))
    store.provenances(OPENING)
    assert listings["count"] == 1, f"listed {listings['count']} times for 4 candidates"


class _Recording:
    """A location that counts how often it is listed."""

    def __init__(self, inner, tally):
        self._inner, self._tally = inner, tally
        self.backend = inner.backend

    def list(self):
        self._tally["count"] += 1
        return self._inner.list()

    def read(self, item):
        return self._inner.read(item)


def test_a_candidate_with_no_record_is_simply_absent(position, written):
    written("cv.txt")
    assert store.provenances(OPENING) == {}


def test_a_damaged_record_does_not_take_the_others_with_it(position, written):
    good = written("cv.txt")
    store.write_provenance(good, {"via": "import"}, OPENING)
    store.cvs(OPENING).write(f"c-{'f' * 16}{store.PROVENANCE_SUFFIX}", b"\x00 not yaml: [")
    assert store.provenances(OPENING)[good]["via"] == "import"
