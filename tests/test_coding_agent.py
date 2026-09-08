"""Driving the pipeline from a coding agent. No model is configured, and none
is called — the agent reading these commands is the model.
"""

import json

from talanton import cli, store
from tests.conftest import OPENING

CONFIG = ["--config", "example/talanton.toml"]


def assessment(**overrides) -> dict:
    """A complete assessment, as `record` now requires. `dimensions` and
    `knockouts` are not optional: a model asked for an optional map returns an
    empty one, which is how a live run produced four assessments that could
    never be filtered."""
    return {
        "overall": 8.0,
        "dimensions": {"production_experience": 8.0},
        "facts": {"name": "Anna Mueller", "work_authorisation": "citizen"},
        "knockouts": {"work_permit": "pass"},
        "justification": "Strong production history.",
        **overrides,
    }


def test_next_emits_the_rubric_and_the_cv(cv, position, capsys):
    cv("anna.txt", "Ten years of production Python. " * 10)
    assert cli.main(["next", OPENING]) == 0
    out = capsys.readouterr().out
    assert "## Knockouts" in out
    assert "untrusted candidate text" in out
    assert "production Python" in out


def test_next_says_when_the_queue_is_empty(position, capsys):
    assert cli.main(["next", OPENING]) == 0
    assert "nothing waiting" in capsys.readouterr().out


def test_next_reports_an_unreadable_cv_instead_of_offering_it_for_scoring(cv, position, capsys):
    cv("scan.txt", "too short")
    assert cli.main(["next", OPENING]) == 0
    out = capsys.readouterr().out
    assert "UNREADABLE" in out and "Do not score this" in out


def test_record_saves_what_the_agent_produced(cv, position, tmp_path, capsys):
    cv("anna.txt")
    payload = tmp_path / "a.json"
    payload.write_text(json.dumps(assessment()), encoding="utf-8")
    assert cli.main(["record", "anna.txt", "--opening", OPENING, "--from", str(payload)]) == 0
    assert store.assessment(store.candidate_id("anna.txt"), OPENING)["overall"] == 8.0


def test_record_runs_the_same_filter_as_the_agent_path(cv, position, tmp_path, capsys):
    """Writing the JSON by hand does not get anyone past the knockouts."""
    cv("blocked.txt")
    payload = tmp_path / "a.json"
    payload.write_text(json.dumps(assessment(knockouts={"work_permit": "fail"})), encoding="utf-8")
    cli.main(["record", "blocked.txt", "--opening", OPENING, "--from", str(payload)])
    assert "held back by the filter" in capsys.readouterr().out


def test_record_refuses_malformed_json(cv, position, tmp_path, capsys):
    cv("anna.txt")
    payload = tmp_path / "a.json"
    payload.write_text("{not json", encoding="utf-8")
    assert cli.main(["record", "anna.txt", "--opening", OPENING, "--from", str(payload)]) == 1


def test_send_applies_the_name_check_to_a_hand_written_summary(assessed, position, sent, capsys):
    """The guards are in the tool, so writing the summary yourself is no way past."""
    cid = assessed("anna.txt", facts={"name": "Anna Mueller"})
    code = cli.main(["send", OPENING, "--candidates", cid, "--summary", "Anna Mueller is strongest."])
    assert code == 1
    assert sent == []


def test_send_goes_out_when_written_by_id(assessed, position, sent, capsys):
    cid = assessed("anna.txt", facts={"name": "Anna Mueller"})
    code = cli.main(["send", OPENING, "--candidates", cid, "--summary", f"{cid} is strongest."])
    assert code == 0
    assert len(sent) == 1 and "drive.example.test" in sent[0]["body"]


def test_send_will_not_link_an_excluded_candidate(assessed, position, sent, capsys):
    cid = assessed("blocked.txt", knockouts={"work_permit": "fail"})
    cli.main(["send", OPENING, "--candidates", cid, "--summary", "worth a look"])
    assert "excluded by a knockout" in capsys.readouterr().out


def test_rubric_prints_the_screening_standard(position, capsys):
    assert cli.main(["rubric", OPENING]) == 0
    out = capsys.readouterr().out
    assert "## Knockouts" in out
    assert "never traded off" in out
    assert "## Scored dimensions" in out


def test_next_prints_the_shape_the_assessment_must_take(cv, position, capsys):
    """The prompt no longer carries a JSON example, so if `next` did not print
    the schema, somebody assessing by hand would be guessing at the fields."""
    from talanton import cli

    cv("anna.txt")
    cli.main(["next", "101"])
    out = capsys.readouterr().out
    for field in ("overall", "dimensions", "knockouts", "justification", "probe", "flags"):
        assert field in out, f"`next` never mentions {field}"


def test_the_printed_shape_is_the_one_the_screener_is_held_to(configure):
    """One model, two paths. They cannot drift apart."""
    import json

    from talanton import agent, assessment

    assert json.loads(assessment.contract()) == agent.screener.output_schema.model_json_schema()


def test_record_reports_the_gaps_in_an_assessment_that_has_them(cv, position, tmp_path):
    """An assessment with no verdicts is saved, and the gaps are visible. It is
    not refused: pressing for a verdict on a knockout the CV never addresses is
    how a good candidate gets a "fail" they never earned."""
    import json as _json

    from talanton import tools

    cv("anna.txt")
    payload = tmp_path / "a.json"
    payload.write_text(_json.dumps({"overall": 8, "justification": "Strong."}), encoding="utf-8")
    assert cli.main(["record", "anna.txt", "--opening", OPENING, "--from", str(payload)]) == 0

    row = tools.list_candidates(OPENING)["candidates"][0]
    assert row["unanswered_knockouts"] == ["work_permit"]
    assert row["unscored_dimensions"] == ["production_experience"]


def test_an_unknown_verdict_records_cleanly_and_costs_the_candidate_nothing(cv, position, tmp_path):
    """The answer the screener is told to reach for. It is a real verdict, so
    it records, and it holds nobody back."""
    import json as _json

    from talanton import tools

    cv("anna.txt")
    payload = tmp_path / "a.json"
    payload.write_text(
        _json.dumps(
            {
                "overall": 9.5,
                "dimensions": {"production_experience": 10},
                "knockouts": {"work_permit": "unknown"},
                "justification": "Outstanding, but never mentions a permit.",
            }
        ),
        encoding="utf-8",
    )
    assert cli.main(["record", "anna.txt", "--opening", OPENING, "--from", str(payload)]) == 0
    assert tools.list_excluded(OPENING)["count"] == 0
    assert tools.list_candidates(OPENING)["candidates"][0]["score"] == 9.5
