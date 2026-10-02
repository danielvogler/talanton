"""`[shortlist] size`: how many go in the mail is a setting, not the model's mood.

Unset, the correspondent decides, as before. Set, the code takes the top N of
the shortlistable pool by score; the correspondent supplies a reason for each,
and the footer says what the next two places scored so a tie at the cut shows.
"""

import pytest

from talanton import config, tools
from tests.conftest import OPENING, picks


@pytest.fixture
def sized(configure):
    def _sized(size):
        configure(shortlist=config.Shortlist(size=size))

    return _sized


def pool(assessed, *scores):
    return [assessed(f"cv-{n}.txt", score=score) for n, score in enumerate(scores)]


def numbered(body: str) -> list[str]:
    """The candidate id on each numbered entry, in order."""
    return [line.split(". ", 1)[1].split()[0] for line in body.splitlines() if ". c-" in line]


def test_the_size_is_read_from_the_config():
    assert config.parse({"shortlist": {"size": 20}}).shortlist.size == 20
    assert config.parse({}).shortlist.size is None


@pytest.mark.parametrize("bad", [0, -3, "twenty", 2.5, True])
def test_a_size_that_is_not_a_positive_whole_number_is_refused(bad):
    with pytest.raises(config.ConfigError, match=r"\[shortlist\] size"):
        config.parse({"shortlist": {"size": bad}})


def test_the_mail_carries_the_top_n_by_score(sized, assessed, position, sent):
    ids = pool(assessed, 6.0, 9.0, 8.0, 7.0)
    sized(2)
    tools.send_digest(OPENING, "Top two.", picks(*ids))
    assert numbered(sent[0]["body"]) == [ids[1], ids[2]]


def test_a_pick_outside_the_cut_is_refused_and_said(sized, assessed, position, sent):
    ids = pool(assessed, 9.0, 8.0, 6.0)
    sized(2)
    result = tools.send_digest(OPENING, "Top two.", picks(ids[0], ids[2]))
    assert {"candidate": ids[2], "reason": "outside the top 2 by score"} in result["refused"]


def test_a_top_candidate_the_agent_skipped_is_still_listed(sized, assessed, position, sent):
    """The setting decides who is in; the agent only explains them."""
    ids = pool(assessed, 9.0, 8.0)
    sized(2)
    tools.send_digest(OPENING, "Top two.", picks(ids[0], why="owned retrieval"))
    assert numbered(sent[0]["body"]) == ids


def test_the_footer_says_what_the_next_two_places_scored(sized, assessed, position, sent):
    ids = pool(assessed, 9.0, 8.0, 7.5, 7.5, 5.5)
    sized(2)
    tools.send_digest(OPENING, "Top two.", picks(*ids[:2]))
    assert "Places 3 and 4 scored 7.5 and 7.5." in sent[0]["body"]


def test_with_one_place_left_the_footer_says_one(sized, assessed, position, sent):
    ids = pool(assessed, 9.0, 8.0, 7.0)
    sized(2)
    tools.send_digest(OPENING, "Top two.", picks(*ids[:2]))
    assert "Place 3 scored 7." in sent[0]["body"]


def test_a_pool_that_fits_has_no_cut_to_report(sized, assessed, position, sent):
    ids = pool(assessed, 9.0, 8.0)
    sized(5)
    tools.send_digest(OPENING, "Both.", picks(*ids))
    assert "Place" not in sent[0]["body"]


def test_an_excluded_candidate_never_takes_a_place(sized, assessed, position, sent):
    top = assessed("blocked.txt", score=9.9, knockouts={"work_permit": "fail"})
    ids = pool(assessed, 8.0, 7.0)
    sized(1)
    tools.send_digest(OPENING, "Top one.", picks(*ids))
    assert numbered(sent[0]["body"]) == [ids[0]]
    assert top not in sent[0]["body"]


def test_unset_the_correspondent_still_decides(assessed, position, sent):
    ids = pool(assessed, 9.0, 8.0, 7.0)
    tools.send_digest(OPENING, "One.", picks(ids[2]))
    assert numbered(sent[0]["body"]) == [ids[2]]


def test_the_shortlist_prompt_names_the_size_when_set(sized):
    from talanton import run

    sized(20)
    assert "top 20" in run.shortlist_prompt(OPENING)
    sized(None)
    assert "top 20" not in run.shortlist_prompt(OPENING)
