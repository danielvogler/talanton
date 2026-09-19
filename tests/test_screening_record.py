"""What produced an assessment, recorded on the assessment.

A score is a judgement made by a particular model, served from a particular
place, by a particular version of this tool. None of that was written down, so
"was the whole pool judged the same way?" could not be answered from the files —
which is the question that matters if a decision is ever challenged.
"""

from talanton import config, screening, store, tools
from tests.conftest import OPENING

GOOD = {"overall": 7.0, "justification": "Strong.", "knockouts": {"work_permit": "pass"}}


def test_an_assessment_records_the_model_that_produced_it(position, cv, configure):
    configure(screening=config.Screening(model="gemini-3.8-flash", project="p", location="global"))
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, GOOD)
    got = store.assessment(store.candidate_id(name), OPENING)
    assert got["model"] == "gemini-3.8-flash"


def test_it_records_where_that_model_was_served(position, cv, configure):
    """A rubric applied in two regions is two standards if the model differs."""
    configure(screening=config.Screening(model="m", project="p", location="europe-west1"))
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, GOOD)
    assert store.assessment(store.candidate_id(name), OPENING)["location"] == "europe-west1"


def test_it_records_the_version_of_the_tool(position, cv):
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, GOOD)
    assert store.assessment(store.candidate_id(name), OPENING)["talanton"]


def test_a_coding_agent_writing_by_hand_is_recorded_as_such(position, cv, configure):
    """`next`/`record` has no model. Saying `gemini` there would be a lie, and
    an assessment that misreports its author is worse than one that says
    nothing."""
    configure(screening=config.Screening(model="", project="", location=""))
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, GOOD)
    assert store.assessment(store.candidate_id(name), OPENING)["model"] == screening.BY_HAND


def test_assessments_from_one_run_share_a_run_id(position, cv):
    """So "was this pool judged in one pass?" is answerable from the files."""
    with screening.run_recorded():
        for who in ("anna.txt", "bruno.txt"):
            cv(who)
            tools.save_assessment(OPENING, who, GOOD)
    ids = {store.assessment(store.candidate_id(w), OPENING)["screening_run"] for w in ("anna.txt", "bruno.txt")}
    assert len(ids) == 1


def test_two_runs_do_not_share_one(position, cv):
    saved = []
    for who in ("anna.txt", "bruno.txt"):
        cv(who)
        with screening.run_recorded():
            tools.save_assessment(OPENING, who, GOOD)
        saved.append(store.assessment(store.candidate_id(who), OPENING)["screening_run"])
    assert saved[0] != saved[1]


def test_an_assessment_saved_outside_a_run_still_saves(position, cv):
    """`record` is driven by a person, one candidate at a time, with no run
    around it. That must not fail, and must not claim a run it was not part of."""
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, GOOD)
    assert store.assessment(store.candidate_id(name), OPENING)["screening_run"] == ""


def test_the_recorded_fields_survive_the_assessment_schema(position, cv):
    """They are added at save time, not returned by the screener, so nothing
    the model writes can forge them."""
    name = cv("anna.txt")
    tools.save_assessment(OPENING, name, {**GOOD, "model": "claimed-by-the-model"})
    assert store.assessment(store.candidate_id(name), OPENING)["model"] != "claimed-by-the-model"
