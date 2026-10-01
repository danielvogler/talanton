"""A slow run and a stuck one have to look different in the log."""

import logging

from talanton import store, tools
from tests.conftest import OPENING, picks
from tests.test_round_trip_budget import build_pool


def lines(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]


def test_reading_the_pool_counts_up_to_the_total(position, caplog):
    build_pool(25)
    with caplog.at_level(logging.INFO):
        store.load_assessments(OPENING)
    said = lines(caplog)
    assert "assessments: 10/25 read" in said
    assert "assessments: 20/25 read" in said
    assert "assessments: 25/25 read" in said


def test_a_small_read_says_only_that_it_finished(position, caplog):
    build_pool(3)
    with caplog.at_level(logging.INFO):
        store.load_assessments(OPENING)
    assert [line for line in lines(caplog) if line.startswith("assessments:")] == ["assessments: 3/3 read"]


def test_a_slow_read_reports_before_the_next_ten(position, caplog, monkeypatch):
    """On a link that resets, ten reads can take minutes. Time counts too."""
    clock = iter(range(0, 1000, 10))
    monkeypatch.setattr(store.time, "monotonic", lambda: next(clock))
    build_pool(4)
    with caplog.at_level(logging.INFO):
        store.load_assessments(OPENING)
    assert "assessments: 1/4 read" in lines(caplog)


def test_the_send_says_each_phase_and_how_it_ended(assessed, position, sent, caplog):
    cid = assessed()
    with caplog.at_level(logging.INFO):
        tools.send_digest(OPENING, "One.", picks(cid))
    said = "\n".join(lines(caplog))
    assert "shortlist: checking names" in said
    assert "shortlist: sending" in said
    assert "shortlist: sent to 1 operator(s)" in said


def test_a_declined_send_says_so(assessed, position, sent, caplog):
    cid = assessed(facts={"name": "Marco Rossi"})
    with caplog.at_level(logging.INFO):
        tools.send_digest(OPENING, "Marco is strong.", picks(cid))
    assert any(line.startswith("shortlist: declined") for line in lines(caplog))
