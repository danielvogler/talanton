"""What each operation costs, asserted so it cannot quietly grow again.

Three slowdowns reported from a live deployment were one bug in three places:
an operation costing one round trip per candidate where it should cost one.
Each was correct, each was invisible on a local folder, and each only appeared
once a real opening had enough people in it to notice.

The point of these tests is not a ceiling. It is that the cost must not SCALE:
the same work is run against a small pool and a large one, and the counts have
to match. A fixed ceiling gets raised by whoever trips over it; a scaling
assertion cannot be satisfied except by fixing the cause.
"""

from talanton import store, tools
from tests.conftest import FULL_FACTS, OPENING
from tests.roundtrips import counted

SMALL, LARGE = 5, 50


def build_pool(size: int, start: int = 0) -> list[str]:
    """Adds `size` assessed candidates to the opening, numbered from `start`."""
    ids = []
    for n in range(start, start + size):
        name = f"applicant-{n:03d}.txt"
        store.cvs(OPENING).write(name, b"Ten years of production systems. " * 8)
        candidate = store.candidate_id(name)
        ids.append(candidate)
        if True:
            store.save_assessment(
                candidate,
                {
                    "candidate": candidate,
                    "cv": name,
                    "cv_uri": f"https://drive.example.test/{candidate}",
                    "opening": 101,
                    "role": "software-engineer",
                    "overall": 7.0,
                    "facts": dict(FULL_FACTS),
                    "knockouts": {"work_permit": "pass"},
                    "flags": [],
                    "justification": "Fine.",
                },
                OPENING,
            )
    return ids


def costs_as_the_pool_grows(work, monkeypatch):
    """What `work` costs on a small pool, then on a pool ten times the size.

    One pool that grows, not two built side by side: the question being asked
    is held fixed and only the number of people on file changes, which is
    exactly the thing the cost must not track.
    """
    ids = build_pool(SMALL)
    tally = counted(monkeypatch)

    tally.reset()
    work(ids)
    small = tally.snapshot()

    build_pool(LARGE - SMALL, start=SMALL)
    tally.reset()
    work(ids)
    return small, tally.snapshot()


# --------------------------------------------------------------------------
# The shortlist mail. The operation an operator actually waits on.
# --------------------------------------------------------------------------


def test_the_digest_never_lists_once_per_candidate(position, sent, monkeypatch):
    """Listings are the strict budget: a listing returns the whole folder, so
    needing more than a handful means something is asking per candidate."""

    def send(ids):
        tools.send_digest(OPENING, f"{ids[0]} is worth a look", ids[:3])

    small, large = costs_as_the_pool_grows(send, monkeypatch)
    assert large.lists == small.lists, f"lists grew: {small} -> {large}"


def test_a_digest_reads_only_the_shortlisted_when_it_need_not_check_names(
    position, sent, monkeypatch, configure
):
    """With names permitted there is no reason to look at anybody but the
    people being written about."""
    from talanton import config

    configure(shortlist=config.Shortlist(names=True))

    def send(ids):
        tools.send_digest(OPENING, f"{ids[0]} is worth a look", ids[:3])

    small, large = costs_as_the_pool_grows(send, monkeypatch)
    assert large.reads == small.reads, (
        f"reads grew with the pool rather than with the shortlist: {small} -> {large}"
    )


def test_the_name_check_reads_the_pool_once_and_not_three_times(position, sent, monkeypatch):
    """The guard has to check every recorded name — a name leaking for somebody
    who was not shortlisted is exactly as bad — so its cost tracks the pool by
    design. What is not by design is paying it more than once: the links, the
    counts and the check each used to download every assessment separately.
    """
    ids = build_pool(LARGE)
    tally = counted(monkeypatch)
    tally.reset()
    tools.send_digest(OPENING, f"{ids[0]} is worth a look", ids[:3])
    assert tally.reads < LARGE * 2, (
        f"{tally.reads} reads for a pool of {LARGE}: the pool is being read more than once"
    )


# --------------------------------------------------------------------------
# Listing. A listing is one round trip whatever it returns; a listing per
# candidate is the bug.
# --------------------------------------------------------------------------


def test_reading_one_candidates_arrival_does_not_list_the_pool_repeatedly(position, monkeypatch):
    ids = build_pool(LARGE)
    store.write_provenance(ids[0], {"via": "import", "source": "a-board"}, OPENING)
    tally = counted(monkeypatch)
    tally.reset()
    store.provenance(ids[0], OPENING)
    assert tally.lists <= 2, f"one candidate's record cost {tally}"


def test_reading_every_arrival_record_costs_one_listing(position, monkeypatch):
    ids = build_pool(LARGE)
    for candidate in ids:
        store.write_provenance(candidate, {"via": "import", "source": "a-board"}, OPENING)
    tally = counted(monkeypatch)
    tally.reset()
    store.provenances(OPENING)
    assert tally.lists <= 2, f"{LARGE} records cost {tally} — the #15 regression"


def test_the_pool_summary_does_not_list_once_per_candidate(position, monkeypatch):
    small, large = costs_as_the_pool_grows(lambda ids: tools.pool_summary(OPENING), monkeypatch)
    assert large.lists == small.lists, f"lists grew with the pool: {small} -> {large}"


def test_the_work_queue_does_not_list_once_per_candidate(position, monkeypatch):
    small, large = costs_as_the_pool_grows(lambda ids: tools.list_new_cvs(OPENING), monkeypatch)
    assert large.lists == small.lists, f"lists grew with the pool: {small} -> {large}"


def test_arrival_records_are_read_only_for_the_shortlisted(position, sent, monkeypatch, configure):
    """The CV block says when each application came in. Answering that from
    `provenances()` would download a record for everybody on file to print
    three lines."""
    from talanton import config

    configure(shortlist=config.Shortlist(names=True))

    def send(ids):
        for candidate in ids:
            store.write_provenance(
                candidate, {"arrived": "2026-09-14", "via": "import", "source": "a-board"}, OPENING
            )
        tools.send_digest(OPENING, f"{ids[0]} is worth a look", ids[:3])

    small, large = costs_as_the_pool_grows(send, monkeypatch)
    assert large.reads == small.reads, f"arrival records are read per candidate on file: {small} -> {large}"
    assert large.lists == small.lists, f"lists grew: {small} -> {large}"
