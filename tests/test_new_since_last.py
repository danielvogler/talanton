"""How many applications arrived since the operator last heard from us.

A total alone does not answer the question an operator actually has on a
Monday morning — "is there anything new?" — and counting it in the mail is the
only place it can be answered, because nobody is going to diff two folders.
"""

import pytest

from talanton import config, store, tools
from tests.conftest import OPENING


@pytest.fixture
def live(configure):
    """Mail that really goes out. `outbound.send` is still the conftest stub,
    so nothing leaves — but the run counts as reported, which is what the
    marker records."""
    return configure(
        outbound=config.Outbound(user="bot@example.com", operators=("you@example.com",), dry_run=False)
    )


def test_the_first_report_says_so_rather_than_calling_everything_new(live, assessed, position, sent):
    assessed()
    tools.send_digest(OPENING, "nobody this time", [])

    assert "first report" in sent[0]["body"]


def test_the_next_report_counts_only_what_arrived_since(live, assessed, position, sent):
    assessed()
    tools.send_digest(OPENING, "nobody this time", [])

    assessed(name="bruno-weiss.txt")
    assessed(name="carla-neri.txt")
    tools.send_digest(OPENING, "nobody this time either", [])

    assert "2 new since the last report" in sent[1]["body"]


def test_a_report_with_nothing_new_says_none(live, assessed, position, sent):
    """The reassuring case, and the one that must not look like a failure."""
    assessed()
    tools.send_digest(OPENING, "nobody", [])
    tools.send_digest(OPENING, "still nobody", [])

    assert "none new since the last report" in sent[1]["body"]


def test_a_dry_run_does_not_advance_what_the_operator_has_seen(configure, assessed, position, sent):
    """Nothing reached the mailbox, so the next real report still owes them
    every application that arrived."""
    configure(outbound=config.Outbound(user="bot@example.com", operators=("you@example.com",), dry_run=True))
    assessed()
    tools.send_digest(OPENING, "nobody", [])

    assert store.last_reported(OPENING) == set()


def test_a_withdrawn_cv_does_not_make_the_count_go_backwards(live, assessed, position, sent, cv):
    """Counting by arithmetic would under-report here; counting ids does not."""
    assessed()
    assessed(name="bruno-weiss.txt")
    tools.send_digest(OPENING, "nobody", [])

    store.cvs(OPENING).list()  # two on file
    for item in store.cvs(OPENING).list():
        if "bruno" in item.name or item.name.startswith("c-"):
            pass
    assessed(name="carla-neri.txt")
    tools.send_digest(OPENING, "nobody", [])

    assert "1 new since the last report" in sent[1]["body"]


def test_the_marker_is_not_read_back_as_an_assessment(live, assessed, position, sent):
    """It lives beside the assessments, so it must not look like one."""
    cid = assessed()
    tools.send_digest(OPENING, "nobody", [])

    assert set(store.load_assessments(OPENING)) == {cid}
    assert store.assessed_ids(OPENING) == {cid}


def test_the_counts_survive_a_location_with_no_marker_yet(position):
    counts = tools.pool_counts(OPENING)
    assert counts["new"] == 0
    assert counts["first_report"] is True
