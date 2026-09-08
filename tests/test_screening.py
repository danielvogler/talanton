"""The knockout filter. This is what "a human never has to look at them" means."""

from talanton import screening, tools
from tests.conftest import OPENING, POSITION


def test_a_failed_knockout_excludes():
    assert screening.exclusions({"overall": 9, "knockouts": {"work_permit": "fail"}}, POSITION) == (
        "knockout:work_permit",
    )


def test_a_high_score_cannot_buy_off_a_knockout():
    assert screening.is_excluded({"overall": 10.0, "knockouts": {"work_permit": "fail"}}, POSITION)


def test_unknown_is_not_failure():
    """A CV that does not say is a question for a person, not a reason to drop someone."""
    assert screening.exclusions({"overall": 7, "knockouts": {"work_permit": "unknown"}}, POSITION) == ()


def test_an_unassessed_candidate_is_not_excluded():
    assert screening.exclusions({}, POSITION) == ()


def test_a_score_below_the_positions_floor_excludes():
    assert screening.exclusions({"overall": 2.0, "knockouts": {"work_permit": "pass"}}, POSITION) == (
        "below-bar:2.0<5.0",
    )


def test_there_is_no_floor_unless_the_position_sets_one():
    without = {k: v for k, v in POSITION.items() if k != "screening"}
    assert screening.exclusions({"overall": 0.5, "knockouts": {}}, without) == ()


def test_an_excluded_candidate_is_absent_from_the_listing(assessed, position):
    assessed("good.txt", score=8.0)
    dropped = assessed("blocked.txt", score=8.0, knockouts={"work_permit": "fail"})
    listed = [r["candidate"] for r in tools.list_candidates(OPENING)["candidates"]]
    assert dropped not in listed and len(listed) == 1


def test_the_filter_is_auditable(assessed, position):
    dropped = assessed("blocked.txt", knockouts={"work_permit": "fail"})
    excluded = tools.list_excluded(OPENING)
    assert excluded["count"] == 1
    assert excluded["excluded"][0] == {"candidate": dropped, "reasons": ["knockout:work_permit"]}


def test_get_candidate_will_not_hand_back_an_excluded_assessment(assessed, position):
    dropped = assessed("blocked.txt", knockouts={"work_permit": "fail"})
    result = tools.get_candidate(OPENING, dropped)
    assert result["excluded"] is True and "assessment" not in result


def test_an_excluded_candidates_cv_is_never_linked(assessed, position, sent):
    dropped = assessed("blocked.txt", knockouts={"work_permit": "fail"})
    result = tools.send_digest(OPENING, "here they are", [dropped])
    assert result["linked"] == []
    assert result["refused"][0]["candidate"] == dropped


def test_a_knockout_the_assessment_omits_is_reported_not_silently_passed(position):
    """Not an exclusion: an unanswered knockout is a question, not a failure.
    But it must be visible, because a dropped id otherwise looks exactly like
    one that was checked and passed."""
    from talanton import screening

    assessment = {"overall": 8, "knockouts": {}}
    assert screening.exclusions(assessment, POSITION_WITH_KNOCKOUT) == ()
    assert screening.unanswered(assessment, POSITION_WITH_KNOCKOUT) == ("work_permit",)


def test_an_answered_knockout_is_not_reported_as_a_gap():
    from talanton import screening

    assessment = {"overall": 8, "knockouts": {"work_permit": "unknown"}}
    assert screening.unanswered(assessment, POSITION_WITH_KNOCKOUT) == ()


def test_a_score_that_is_not_a_number_does_not_slip_under_the_floor():
    """isinstance(overall, (int, float)) is false for "8", which used to skip
    the floor entirely rather than failing loudly."""
    from talanton import screening

    reasons = screening.exclusions(
        {"overall": "8", "knockouts": {"work_permit": "pass"}},
        {"screening": {"min_score": 9.0}, "knockouts": [{"id": "work_permit"}]},
    )
    assert reasons, "a non-numeric score cleared a floor it should not have"


def test_a_numeric_string_is_still_compared_when_it_can_be_read():
    from talanton import screening

    position = {"screening": {"min_score": 5.0}, "knockouts": [{"id": "work_permit"}]}
    assert screening.exclusions({"overall": "8", "knockouts": {"work_permit": "pass"}}, position) == ()


def test_knockouts_arriving_as_a_list_do_not_crash_the_filter():
    """A model can return a list of objects instead of a map. That must be a
    refusal, not an AttributeError halfway through a run."""
    from talanton import screening

    reasons = screening.exclusions(
        {"overall": 8, "knockouts": [{"id": "work_permit", "verdict": "pass"}]},
        {"knockouts": [{"id": "work_permit"}]},
    )
    assert reasons, "a malformed knockouts block was treated as clean"


POSITION_WITH_KNOCKOUT = {
    "knockouts": [{"id": "work_permit", "test": "Can work here."}],
    "screening": {},
}


WORLD_CLASS = {
    "overall": 9.5,
    "dimensions": {"production_experience": 10.0},
    "justification": "Has owned a large system in production, including its failures.",
}
STRICT = {
    "knockouts": [{"id": "work_permit"}, {"id": "english"}],
    "screening": {"min_score": 5.0},
}


def test_a_strong_candidate_who_never_mentions_a_permit_stays_in_the_pool():
    """The one this must never get wrong. Not mentioning something is not
    failing it, and the cost of confusing the two is a person who should have
    been hired never being read."""
    from talanton import screening

    assert screening.exclusions({**WORLD_CLASS, "knockouts": {}}, STRICT) == ()


def test_an_unknown_verdict_does_not_exclude_either():
    from talanton import screening

    assessment = {**WORLD_CLASS, "knockouts": {"work_permit": "unknown", "english": "unknown"}}
    assert screening.exclusions(assessment, STRICT) == ()


def test_the_gap_is_still_reported_so_somebody_can_ask():
    """Not excluded is not the same as not noticed."""
    from talanton import screening

    assessment = {**WORLD_CLASS, "knockouts": {}}
    assert screening.unanswered(assessment, STRICT) == ("work_permit", "english")


def test_only_an_established_failure_holds_anybody_back():
    from talanton import screening

    assessment = {**WORLD_CLASS, "knockouts": {"work_permit": "fail"}}
    assert screening.exclusions(assessment, STRICT) == ("knockout:work_permit",)


def test_the_screener_is_told_that_silence_is_not_a_fail():
    """The rule lives in the prompt as well as the filter, because the filter
    can only act on the verdict it is given."""
    from talanton import agent

    instruction = " ".join(agent.SCREENER_INSTRUCTION.lower().split())
    assert "silence is never a fail" in instruction
    assert "world-class" in instruction
    # And nothing pushing the other way: asking for full coverage is what makes
    # a model invent a verdict for something the document never addressed.
    assert "cover every" not in instruction
