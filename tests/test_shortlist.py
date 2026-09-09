"""The one thing that leaves the system. Ids and links, never names."""

from talanton import config, tools
from tests.conftest import OPENING


def test_the_shortlist_goes_only_to_operators(assessed, position, sent):
    cid = assessed()
    assert tools.send_digest(OPENING, f"{cid} is worth a look", [cid])["sent"] is True
    assert [m["to"] for m in sent] == ["you@example.com"]


def test_a_summary_naming_someone_is_refused(assessed, position, sent):
    """Identity lives behind the CV link, where folder access controls it."""
    cid = assessed(facts={"name": "Marco Rossi"})
    result = tools.send_digest(OPENING, "Marco Rossi is the strongest by far.", [cid])
    assert result["sent"] is False
    assert "Marco Rossi" in result["reason"]
    assert sent == []


def test_the_same_summary_by_id_goes_out(assessed, position, sent):
    cid = assessed(facts={"name": "Marco Rossi"})
    assert tools.send_digest(OPENING, f"{cid} is the strongest by far.", [cid])["sent"] is True
    assert "Marco Rossi" not in sent[0]["body"]


def test_the_name_check_is_case_insensitive(assessed, position, sent):
    cid = assessed(facts={"name": "Marco Rossi"})
    assert tools.send_digest(OPENING, "marco rossi looks good.", [cid])["sent"] is False


def test_a_very_short_name_does_not_trip_the_check(assessed, position, sent):
    """Guarding on a two-letter name would refuse every legitimate summary."""
    cid = assessed(facts={"name": "Jo"})
    assert tools.send_digest(OPENING, "Job history is strong for this one.", [cid])["sent"] is True


def test_cv_links_are_appended_by_the_tool(assessed, position, sent):
    cid = assessed()
    tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert "https://drive.example.test/" in sent[0]["body"]
    assert "Access is controlled on the folder" in sent[0]["body"]


def test_an_excluded_candidate_gets_no_link(assessed, position, sent):
    cid = assessed(knockouts={"work_permit": "fail"})
    result = tools.send_digest(OPENING, "summary", [cid])
    assert result["linked"] == []
    assert result["refused"][0]["reason"].startswith("excluded")
    assert "drive.example.test" not in sent[0]["body"]


def test_an_unknown_candidate_is_reported_not_silently_dropped(position, sent):
    result = tools.send_digest(OPENING, "summary", ["c-nobody"])
    assert result["refused"] == [{"candidate": "c-nobody", "reason": "no assessment on file"}]


def test_the_shortlist_is_refused_with_no_operator(configure, position, sent):
    configure(outbound=config.Outbound(user="bot@example.com", operators=()))
    assert tools.send_digest(OPENING, "x", [])["sent"] is False
    assert sent == []


def test_there_is_no_recipient_argument():
    import inspect

    assert list(inspect.signature(tools.send_digest).parameters) == ["opening", "summary", "candidates"]


def test_a_first_name_alone_is_refused(assessed, position, sent):
    """A shortlist that carries "Marco" has leaked as surely as one that
    carries "Marco Rossi"."""
    cid = assessed(facts={"name": "Marco Rossi"})
    result = tools.send_digest(OPENING, "Marco is the strongest by far.", [cid])
    assert result["sent"] is False
    assert sent == []


def test_a_possessive_first_name_is_refused(assessed, position, sent):
    cid = assessed(facts={"name": "Marco Rossi"})
    assert tools.send_digest(OPENING, "Marco's ownership evidence is thin.", [cid])["sent"] is False


def test_a_recorded_email_address_is_refused(assessed, position, sent):
    """The address identifies as surely as the name does."""
    cid = assessed(facts={"name": "unknown", "email": "marco.rossi@example.net"})
    result = tools.send_digest(OPENING, f"Reach {cid} at marco.rossi@example.net.", [cid])
    assert result["sent"] is False
    assert sent == []


def test_a_name_fragment_inside_another_word_does_not_trip_the_check(assessed, position, sent):
    """Matching on substrings would refuse "adaptive" for a candidate named Ada."""
    cid = assessed(facts={"name": "Ada Okonkwo"})
    assert tools.send_digest(OPENING, f"{cid} built adaptive retrieval.", [cid])["sent"] is True


def test_nothing_is_sent_when_the_allowlist_blocks_a_later_operator(configure, assessed, position, sent):
    """A partial send reported as no send invites a duplicate retry."""
    configure(
        outbound=config.Outbound(
            user="bot@example.com",
            operators=("you@example.com", "them@elsewhere.test"),
            allow_domains=("example.com",),
        )
    )
    cid = assessed()
    result = tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert result["sent"] is False
    assert sent == [], "the first operator was mailed while the tool reported nothing sent"


def test_the_link_block_carries_no_name_on_a_real_location(cv, position, sent):
    """The summary refuses "Marco", then the tool appends a link built from the
    location itself. On a local or GCS backend that link is the filename, so
    the name went out in the same message that refused it.

    Uses the real save_assessment rather than the fixture, because the fixture
    substitutes a fake URI and would hide exactly this."""
    from talanton import store

    name = cv("marco-rossi.pdf")
    cid = store.candidate_id(name)
    tools.save_assessment(
        OPENING,
        name,
        {
            "overall": 8,
            "justification": "Strong.",
            "knockouts": {"work_permit": "pass"},
            "facts": {"name": "Marco Rossi", "email": "marco@example.test"},
        },
    )
    result = tools.send_digest(OPENING, f"{cid} is worth a look", [cid])
    assert result["sent"] is False, "a link naming the candidate went out"
    assert "marco" in result["reason"].lower()
    assert sent == []


def test_a_fetched_cv_is_stored_under_the_candidate_id(position):
    """The link can only be as anonymous as the filename it points at."""
    from talanton import store

    store.write_cv("marco-rossi.pdf", b"a CV. " * 40, OPENING)
    stored = [i.name for i in store.list_cvs(OPENING)]
    assert stored == [f"{store.candidate_id('marco-rossi.pdf')}.pdf"], stored


def test_an_id_shaped_name_is_not_hashed_again(position):
    """Otherwise every listing would invent a new candidate for the same file."""
    from talanton import store

    item = store.write_cv("marco-rossi.pdf", b"a CV. " * 40, OPENING)
    assert store.candidate_id(item.name) == store.candidate_id("marco-rossi.pdf")


def test_a_digest_for_a_fetched_cv_goes_out_clean(position, sent):
    """The whole point: renamed on the way in, so the link names nobody."""
    from talanton import store

    store.write_cv("marco-rossi.pdf", b"a CV. " * 40, OPENING)
    cid = store.candidate_id("marco-rossi.pdf")
    tools.save_assessment(
        OPENING,
        f"{cid}.pdf",
        {
            "overall": 8,
            "justification": "Strong.",
            "knockouts": {"work_permit": "pass"},
            "facts": {"name": "Marco Rossi", "email": "marco@example.test"},
        },
    )
    assert tools.send_digest(OPENING, f"{cid} is worth a look", [cid])["sent"] is True
    body = sent[0]["body"].lower()
    assert "marco" not in body and "rossi" not in body


def test_the_original_filename_survives_in_the_assessment(assessed, position):
    """Renaming on disk must not lose which file a person actually sent."""
    from talanton import store

    cid = assessed("marco-rossi.pdf")
    assert store.assessment(cid, OPENING)["cv"] == "marco-rossi.pdf"


# --------------------------------------------------- when delivery itself fails


def test_a_refused_login_is_reported_as_an_error_not_a_silent_traceback(
    assessed, position, sent, configure, monkeypatch
):
    """ADK turns an exception inside a tool call into text and carries on, so
    the run reported success having sent nothing. The tool has to answer with
    something the process can act on."""
    import smtplib

    from tests.test_mail import FakeSMTP

    FakeSMTP.logged_in, FakeSMTP.messages, FakeSMTP.rejects = [], [], True
    monkeypatch.undo()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "app-password")
    configure(
        outbound=config.Outbound(
            user="bot@example.com",
            operators=("you@example.com",),
            allow_domains=("example.com",),
            dry_run=False,
        )
    )
    cid = assessed()
    result = tools.send_digest(OPENING, f"{cid} is worth a look", [cid])

    assert result["sent"] is False
    assert "not accepted" in result["error"].lower()
    assert "reason" not in result, "a delivery failure is not a guardrail declining"


def test_a_guardrail_declining_is_a_reason_and_not_an_error(assessed, position, sent):
    """The two have to stay distinguishable: a refused name is something the
    agent can fix and retry, a refused login is not."""
    cid = assessed(facts={"name": "Marco Rossi"})
    result = tools.send_digest(OPENING, "Marco Rossi is the strongest.", [cid])
    assert "reason" in result and "error" not in result


def test_a_tool_error_fails_the_stage():
    """`cycle` exited 0 with an SMTP traceback in its log. This is the check
    that turns that into a non-zero exit."""
    from talanton import run

    assert run.tool_failures(_event({"sent": False, "error": "login refused"})) == ["login refused"]


def test_a_tool_reason_does_not_fail_the_stage():
    from talanton import run

    assert run.tool_failures(_event({"sent": False, "reason": "names a candidate"})) == []


def test_a_successful_tool_call_fails_nothing():
    from talanton import run

    assert run.tool_failures(_event({"sent": True})) == []


def test_an_event_with_no_content_fails_nothing():
    from talanton import run

    assert run.tool_failures(_Event(None)) == []


class _Event:
    def __init__(self, content):
        self.content = content


def _event(response: dict):
    """One ADK event carrying a single function response."""
    from google.genai import types

    return _Event(
        types.Content(
            role="user",
            parts=[types.Part(function_response=types.FunctionResponse(name="send_digest", response=response))],
        )
    )


def test_an_umlaut_spelled_out_is_still_the_same_person(assessed, position, sent):
    """A CV that says Müller and a summary that says Mueller name one
    candidate. Folding alone turns the first into "muller"."""
    cid = assessed(facts={"name": "Anna Müller"})
    assert tools.send_digest(OPENING, "Mueller is the strongest by far.", [cid])["sent"] is False
    assert tools.send_digest(OPENING, "Muller is the strongest by far.", [cid])["sent"] is False
    assert sent == []


def test_a_name_run_together_is_refused(assessed, position, sent):
    """ "MarcoRossi" is one word to a regex and two to whoever reads the mail."""
    cid = assessed(facts={"name": "Marco Rossi"})
    assert tools.send_digest(OPENING, "MarcoRossi is worth a call.", [cid])["sent"] is False
    assert sent == []


def test_an_unrecorded_name_leaves_the_word_unknown_sayable(assessed, position, sent):
    """ "unknown" is the schema's word for what the CV did not say. Guarding on
    it would refuse the digest that exists to report what is not yet known."""
    cid = assessed(facts={"name": "unknown", "email": "unknown"})
    result = tools.send_digest(OPENING, f"{cid} is strong; work permit unknown.", [cid])
    assert result["sent"] is True, result.get("reason")
