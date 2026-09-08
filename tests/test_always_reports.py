"""Every run reports, including the runs with nothing to report.

Silence is ambiguous. An operator who gets no mail cannot tell whether nobody
applied, everybody was held back, or the pipeline broke — and the one time it
matters is the time it broke. So a run always sends, and the counts are
computed here rather than written by the model.
"""

from talanton import config, run, tools
from tests.conftest import OPENING


def turn(text="done", delivered=(), declined=()):
    return run.Turn(text=text, delivered=tuple(delivered), declined=tuple(declined))


def test_a_run_where_nobody_clears_the_bar_still_sends(assessed, position, sent, monkeypatch):
    assessed()
    monkeypatch.setattr(run, "converse", lambda *a, **k: turn("Nobody is worth your time."))

    run.shortlist(OPENING)

    assert len(sent) == 1, "a run with no shortlist sent nothing at all"
    assert "1 application" in sent[0]["body"]


def test_the_standing_report_says_how_many_applications_there_are(assessed, position, sent, monkeypatch):
    """The count is the whole point: it distinguishes an empty pipeline from a
    broken one. The breakdown belongs in `status`, not in this mail."""
    assessed()
    assessed(name="bruno-weiss.txt", knockouts={"work_permit": "fail"})
    monkeypatch.setattr(run, "converse", lambda *a, **k: turn("None of them."))

    run.shortlist(OPENING)

    assert "2 applications on file" in sent[0]["body"]


def test_a_delivered_shortlist_is_not_followed_by_a_second_email(assessed, position, sent, monkeypatch):
    monkeypatch.setattr(run, "converse", lambda *a, **k: turn(delivered=("you@example.com",)))

    run.shortlist(OPENING)

    assert sent == [], "the agent had already sent; this is a duplicate"


def test_a_refused_shortlist_does_not_claim_nobody_cleared_the_bar(assessed, position, sent, monkeypatch):
    """A guardrail declining and an empty pool are different facts, and
    reporting the first as the second would hide a real problem."""
    assessed()
    monkeypatch.setattr(
        run,
        "converse",
        lambda *a, **k: turn(declined=("what this would send names Marco Rossi",)),
    )

    run.shortlist(OPENING)

    body = sent[0]["body"]
    assert "Marco Rossi" not in body, "the refusal reason leaked the name the guard caught"
    assert "declined" in body
    assert "cleared the bar" not in body


def test_a_failed_delivery_of_the_standing_report_fails_the_run(assessed, position, monkeypatch):
    import pytest

    monkeypatch.setattr(run, "converse", lambda *a, **k: turn("nobody"))
    monkeypatch.setattr(
        tools, "send_digest", lambda opening, summary, candidates: {"sent": False, "error": "refused"}
    )
    with pytest.raises(run.StageFailedError, match="refused"):
        run.shortlist(OPENING)


def test_no_operator_configured_is_not_a_failure(configure, assessed, position, monkeypatch):
    """Reading the result with `status` is a legitimate setup, and `check`
    already says so."""
    configure(outbound=config.Outbound(user="bot@example.com", operators=(), dry_run=True))
    monkeypatch.setattr(run, "converse", lambda *a, **k: turn("nobody"))

    run.shortlist(OPENING)  # does not raise


def test_the_counts_are_on_an_ordinary_shortlist_too(assessed, position, sent):
    cid = assessed()
    tools.send_digest(OPENING, f"{cid} is worth a look", [cid])

    assert "1 application" in sent[0]["body"]


def test_the_counts_are_computed_not_asked_for(assessed, position):
    assessed()
    assessed(name="bruno-weiss.txt", knockouts={"work_permit": "fail"})
    counts = tools.pool_counts(OPENING)

    assert counts["received"] == 2
    assert counts["assessed"] == 2
    assert counts["excluded"] == 1
