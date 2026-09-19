"""The questions asked before a shortlist goes out.

`status` answers how big the pool is and who is in it. The questions that
actually precede a decision are whether everything that arrived was scored,
how it arrived, and whether the whole pool was judged the same way. Each was a
throwaway script written in a scratch directory and lost.
"""

from talanton import screening, store, tools
from tests.conftest import OPENING

GOOD = {"overall": 7.0, "justification": "Fine.", "knockouts": {"work_permit": "pass"}}


def test_it_counts_how_everybody_arrived(position, cv):
    for name, source in (("a.txt", "a-board"), ("b.txt", "a-board"), ("c.txt", "another-board")):
        cv(name)
        store.write_provenance(store.candidate_id(name), {"via": "import", "source": source}, OPENING)
    pool = tools.pool_summary(OPENING)
    assert pool["arrived_by"][("import", "a-board")] == 2
    assert pool["arrived_by"][("import", "another-board")] == 1


def test_candidates_with_no_record_are_counted_separately(position, cv):
    """Anybody stored before arrivals were recorded. Not an unknown route —
    a record that never existed."""
    cv("old.txt")
    assert tools.pool_summary(OPENING)["no_record"] == 1


def test_it_says_how_many_of_the_arrivals_were_scored(position, cv):
    for name in ("a.txt", "b.txt", "c.txt"):
        cv(name)
    tools.save_assessment(OPENING, "a.txt", GOOD)
    pool = tools.pool_summary(OPENING)
    assert pool["arrived"] == 3
    assert pool["assessed"] == 1
    assert pool["unassessed"] == 2


def test_it_says_what_judged_them(position, cv, configure):
    """A rubric applied by two models is two standards, and the pool cannot
    say so unless the model is on the record."""
    from talanton import config

    configure(screening=config.Screening(model="model-one", location="global"))
    cv("a.txt")
    tools.save_assessment(OPENING, "a.txt", GOOD)
    configure(screening=config.Screening(model="model-two", location="europe-west1"))
    cv("b.txt")
    tools.save_assessment(OPENING, "b.txt", GOOD)

    judged = tools.pool_summary(OPENING)["judged_by"]
    assert judged[("model-one", "global")] == 1
    assert judged[("model-two", "europe-west1")] == 1


def test_it_counts_the_screening_runs_behind_the_pool(position, cv):
    """One pass over the pool, or several assembled over a week."""
    for name in ("a.txt", "b.txt"):
        cv(name)
    with screening.run_recorded():
        tools.save_assessment(OPENING, "a.txt", GOOD)
        tools.save_assessment(OPENING, "b.txt", GOOD)
    assert tools.pool_summary(OPENING)["screening_runs"] == 1


def test_an_empty_pool_is_answerable_not_an_error(position):
    pool = tools.pool_summary(OPENING)
    assert pool["arrived"] == 0
    assert pool["unassessed"] == 0


def test_the_summary_reads_one_listing_per_location(position, cv, monkeypatch):
    """It is the command an operator runs on a real pool, so it must not be
    the one that costs a round trip per candidate."""
    for name in ("a.txt", "b.txt", "c.txt"):
        cv(name)
    calls = {"count": 0}
    original = store.provenance

    def _counted(candidate, opening=""):
        calls["count"] += 1
        return original(candidate, opening)

    monkeypatch.setattr(store, "provenance", _counted)
    tools.pool_summary(OPENING)
    assert calls["count"] == 0, "the per-candidate accessor is the slow one"
