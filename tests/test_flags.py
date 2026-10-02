"""Flags are what an operator sees next to the score, so they have to say something."""

from talanton import assessment


def test_empty_flags_are_never_stored():
    assert assessment.normalise({"flags": ["", "  ", "dates overlap"]})["flags"] == ["dates overlap"]


def test_the_screener_is_told_credibility_problems_are_flags():
    from talanton import agent

    assert "dates" in agent.SCREENER_INSTRUCTION and "flags" in agent.SCREENER_INSTRUCTION
