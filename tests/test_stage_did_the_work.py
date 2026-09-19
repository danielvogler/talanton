"""A stage that reports success must have done the work.

`StageFailedError` is documented as being raised "when a stage did not
actually do its work", but what was checked is that the agent said something.
An LLM always says something, so the guard could not fire for the case it was
named after: a run that assessed ten of seventy-two ended with "I have
reassessed all CVs", exit code zero, nothing logged.
"""

import pytest

from talanton import run, screening, store, tools
from tests.conftest import OPENING

GOOD = {"overall": 7.0, "justification": "Strong.", "knockouts": {"work_permit": "pass"}}


def _assesses(count: int):
    """An agent that assesses `count` of whatever is waiting, then stops."""

    def _run(question, user_id="operator", app=None):
        for row in tools.list_new_cvs(OPENING)["waiting"][:count]:
            tools.save_assessment(OPENING, row["cv"], GOOD)
        return run.Turn(text="I have assessed all CVs for this opening.")

    return _run


def test_a_run_that_leaves_the_queue_full_is_a_failure(position, cv, monkeypatch):
    for who in ("a.txt", "b.txt", "c.txt"):
        cv(who)
    monkeypatch.setattr(run, "converse", _assesses(1))
    with pytest.raises(run.StageFailedError, match="2 of 3"):
        run.assess(OPENING)


def test_the_failure_says_how_many_were_left(position, cv, monkeypatch):
    """A count is what tells an operator whether to re-run or to investigate."""
    for who in ("a.txt", "b.txt", "c.txt"):
        cv(who)
    monkeypatch.setattr(run, "converse", _assesses(0))
    with pytest.raises(run.StageFailedError, match="3 of 3"):
        run.assess(OPENING)


def test_a_run_that_drains_the_queue_succeeds(position, cv, monkeypatch):
    for who in ("a.txt", "b.txt"):
        cv(who)
    monkeypatch.setattr(run, "converse", _assesses(2))
    assert run.assess(OPENING)


def test_an_empty_queue_is_not_a_failure(position, monkeypatch):
    """Nothing waiting is an ordinary outcome, not a broken run."""
    monkeypatch.setattr(run, "converse", _assesses(0))
    assert run.assess(OPENING)


def test_the_agents_own_words_do_not_decide_it(position, cv, monkeypatch):
    """The whole point: confident prose is not evidence of work."""
    cv("a.txt")

    def _says_so_but_does_nothing(question, user_id="operator", app=None):
        return run.Turn(text="All CVs have been assessed successfully.")

    monkeypatch.setattr(run, "converse", _says_so_but_does_nothing)
    with pytest.raises(run.StageFailedError):
        run.assess(OPENING)


def test_a_rescreen_that_missed_candidates_is_a_failure(position, cv, assessed, monkeypatch):
    """A rescreen leaves the queue empty either way, so the queue cannot answer
    it. Everybody must carry this run's id."""
    assessed("a.txt")
    assessed("b.txt")

    def _rescreens_one(question, user_id="operator", app=None):
        tools.save_assessment(OPENING, "a.txt", GOOD)
        return run.Turn(text="Every CV has been reassessed.")

    monkeypatch.setattr(run, "converse", _rescreens_one)
    with pytest.raises(run.StageFailedError, match="1 of 2"):
        run.assess(OPENING, rescreen=True)


def test_a_rescreen_that_covered_everyone_succeeds(position, assessed, monkeypatch):
    assessed("a.txt")
    assessed("b.txt")

    def _rescreens_all(question, user_id="operator", app=None):
        for candidate in list(store.candidates(OPENING)):
            tools.save_assessment(OPENING, f"{candidate}.txt", GOOD)
        return run.Turn(text="Every CV has been reassessed.")

    monkeypatch.setattr(run, "converse", _rescreens_all)
    assert run.assess(OPENING, rescreen=True)


def test_the_run_id_is_what_a_rescreen_is_judged_on(position, assessed, monkeypatch):
    """Not the date: a rescreen on the day of the original would pass on dates
    without having reassessed anybody."""
    assessed("a.txt")
    seen = {}

    def _capture(question, user_id="operator", app=None):
        seen["run"] = screening.current_run()
        tools.save_assessment(OPENING, "a.txt", GOOD)
        return run.Turn(text="done")

    monkeypatch.setattr(run, "converse", _capture)
    run.assess(OPENING, rescreen=True)
    assert seen["run"]
    assert store.assessment(store.candidate_id("a.txt"), OPENING)["screening_run"] == seen["run"]
