"""An application nobody could read has to appear in the digest.

Left unassessed rather than scored zero, which is right. But `shortlist` ranks
what is assessed, so an unreadable application is not ranked low — it is
absent, and the digest gives no sign anyone was left out. The footer's own
docstring says its job is telling an empty pipeline from a broken one, and it
read identically whether the shortlist was drawn from all of the pool or from
most of it.

The applicants this loses are not a random sample. A scanned PDF is what you
get from somebody who printed, signed and scanned their CV, which tracks career
stage and country of origin far more than it tracks whether they can do the
job.
"""

from talanton import run, store, tools
from tests.conftest import OPENING

SCAN = b"%PDF-1.4 no text layer"
GOOD = {"overall": 7.0, "justification": "Fine.", "knockouts": {"work_permit": "pass"}}


def test_the_digest_says_how_many_could_not_be_read(position, assessed, cv, sent):
    cid = assessed("anna.txt")
    store.write_documents(store.candidate_id("scan.pdf"), [("scan.pdf", SCAN)], OPENING)
    store.record_unreadable({store.candidate_id("scan.pdf")}, OPENING)
    tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert "could not be read" in sent[0]["body"]


def test_it_names_them_so_the_operator_can_ask_for_another_file(position, assessed, sent):
    cid = assessed("anna.txt")
    scan = store.candidate_id("scan.pdf")
    store.write_documents(scan, [("scan.pdf", SCAN)], OPENING)
    store.record_unreadable({scan}, OPENING)
    tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert scan in sent[0]["body"], "an id carries no identity and is what makes it actionable"


def test_a_pool_with_nothing_unreadable_says_nothing_about_it(position, assessed, sent):
    """The footer is one sentence. It does not grow a clause for a case that
    did not happen."""
    cid = assessed("anna.txt")
    tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert "could not be read" not in sent[0]["body"]


def test_the_count_survives_a_run_that_recommends_nobody(position, sent):
    """The run where this matters most: the digest is the standing report, and
    'nobody cleared the bar' reads very differently if two were never read."""
    scan = store.candidate_id("scan.pdf")
    store.write_documents(scan, [("scan.pdf", SCAN)], OPENING)
    store.record_unreadable({scan}, OPENING)
    tools.send_digest(OPENING, "Nobody this time.", [])
    assert "could not be read" in sent[0]["body"]


def test_the_record_survives_a_round_trip(position):
    store.record_unreadable({"c-" + "a" * 16, "c-" + "b" * 16}, OPENING)
    assert store.unreadable(OPENING) == {"c-" + "a" * 16, "c-" + "b" * 16}


def test_an_opening_with_no_record_reads_as_empty(position):
    """Every pool assessed before this existed has none."""
    assert store.unreadable(OPENING) == set()


def test_a_later_run_replaces_the_earlier_answer(position):
    """Somebody who sends a readable file must stop being counted."""
    store.record_unreadable({"c-" + "a" * 16}, OPENING)
    store.record_unreadable(set(), OPENING)
    assert store.unreadable(OPENING) == set()


def test_the_marker_is_not_mistaken_for_an_assessment(position, cv):
    """It sits among the assessments, and everything there filters on .yaml."""
    cv("anna.txt")
    store.record_unreadable({"c-" + "a" * 16}, OPENING)
    assert store.assessed_ids(OPENING) == set()


def test_assess_records_what_it_could_not_read(position, cv, monkeypatch):
    """The list is computed during the run that met them; recomputing it at
    digest time would re-read every waiting document."""
    cv("readable.txt")
    scan = store.candidate_id("scan.pdf")
    store.write_documents(scan, [("scan.pdf", SCAN)], OPENING)

    def _assesses_what_it_can(question, user_id="operator", agent_app=None):
        tools.save_assessment(OPENING, "readable.txt", GOOD)
        return run.Turn(text="one assessed, one unreadable")

    monkeypatch.setattr(run, "converse", _assesses_what_it_can)
    run.assess(OPENING)
    assert store.unreadable(OPENING) == {scan}
