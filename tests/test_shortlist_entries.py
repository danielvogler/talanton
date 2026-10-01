"""One list: each shortlisted candidate is one entry, built in code, with its
CV link on it. The correspondent supplies the ranking and one line of why."""

from talanton import store, tools
from tests.conftest import OPENING, picks


def entry_of(body: str, candidate: str) -> list[str]:
    """The lines of one numbered entry, from its id line to the next blank."""
    lines = body.splitlines()
    start = next(i for i, line in enumerate(lines) if f". {candidate}" in line)
    end = next((i for i in range(start + 1, len(lines)) if not lines[i].strip()), len(lines))
    return lines[start:end]


def test_each_entry_carries_its_own_cv_link(assessed, position, sent):
    """Matching a hash in one list against a hash in another is the chore this removes."""
    ids = [assessed(f"cv-{n}.txt") for n in range(3)]
    tools.send_digest(OPENING, "Three worth a look.", picks(*ids))
    for candidate in ids:
        assert any(
            f"https://drive.example.test/{candidate}" in line for line in entry_of(sent[0]["body"], candidate)
        )


def test_the_link_comes_before_anything_a_mail_client_might_link(assessed, position, sent):
    """Gmail links a bare "jobs.ch". The CV has to be the first thing to click."""
    cid = assessed()
    store.write_provenance(cid, {"arrived": "2026-09-14", "via": "import", "source": "jobs.ch"}, OPENING)
    tools.send_digest(OPENING, "One.", picks(cid))
    entry = entry_of(sent[0]["body"], cid)
    link = next(i for i, line in enumerate(entry) if "drive.example.test" in line)
    board = next(i for i, line in enumerate(entry) if "jobs.ch" in line)
    assert link < board, entry


def test_there_is_no_separate_link_block(assessed, position, sent):
    cid = assessed()
    tools.send_digest(OPENING, "One.", picks(cid))
    body = sent[0]["body"]
    assert "CVs (" not in body
    assert sum(line.strip().startswith(cid) for line in body.splitlines()) == 0, body
    assert body.count(f". {cid}") == 1, body


def test_entries_keep_the_order_the_correspondent_ranked_them_in(assessed, position, sent):
    low, high = assessed("a.txt", score=6.0), assessed("b.txt", score=9.0)
    tools.send_digest(OPENING, "Two.", picks(low, high))
    body = sent[0]["body"]
    assert body.index(f"1. {low}") < body.index(f"2. {high}")


def test_the_why_is_one_line_under_its_own_entry(assessed, position, sent):
    """A reason with a line break in it is the drift that hand formatting caused."""
    cid = assessed()
    tools.send_digest(OPENING, "One.", [{"candidate": cid, "why": "owned retrieval\nin production"}])
    assert any(line.strip() == "owned retrieval in production" for line in entry_of(sent[0]["body"], cid))


def test_an_entry_carries_score_years_and_employers(assessed, position, sent):
    cid = assessed(score=8.5, facts={"years_industry": 8, "employers": "ML Engineer, ETH; SWE, Google"})
    tools.send_digest(OPENING, "One.", picks(cid))
    entry = "\n".join(entry_of(sent[0]["body"], cid))
    assert "8.5" in entry and "8 yrs" in entry and "ML Engineer, ETH; SWE, Google" in entry


def test_what_the_cv_did_not_say_is_an_open_line(assessed, position, sent):
    cid = assessed(facts={"work_authorisation": "unknown", "notice_period": "unknown"})
    tools.send_digest(OPENING, "One.", picks(cid))
    assert any("Open: work authorisation, notice period" in line for line in entry_of(sent[0]["body"], cid))


def test_a_screener_flag_is_a_check_line(assessed, position, sent):
    cid = assessed(flags=["two overlapping full-time roles in 2023"])
    tools.send_digest(OPENING, "One.", picks(cid))
    assert any(
        "Check: two overlapping full-time roles in 2023" in line for line in entry_of(sent[0]["body"], cid)
    )


def test_a_bare_pile_of_cvs_gives_clean_entries(assessed, position, sent):
    """CVs dropped into a folder by hand: no board, no date, no years, no
    employers. Each entry is then the id, the link and the reason, and not a
    column of placeholders."""
    cid = assessed(facts={"years_industry": "unknown", "employers": "unknown"})
    assert tools.send_digest(OPENING, "One.", picks(cid, why="strong systems work"))["sent"] is True
    entry = "\n".join(entry_of(sent[0]["body"], cid))
    for placeholder in ("unknown", "none", "not recorded", "yrs"):
        assert placeholder not in entry.lower(), entry
    assert "strong systems work" in entry


def test_an_unrecorded_arrival_is_said_when_the_others_are_recorded(assessed, position, sent):
    """Among dated entries, a missing date reads as an omission unless it is named."""
    dated, undated = assessed("a.txt"), assessed("b.txt")
    store.write_provenance(dated, {"arrived": "2026-09-14", "via": "mailbox"}, OPENING)
    tools.send_digest(OPENING, "Two.", picks(dated, undated))
    assert any("arrival not recorded" in line for line in entry_of(sent[0]["body"], undated))


def test_a_candidate_new_since_the_last_report_is_marked(configure, assessed, position, sent):
    from talanton import config

    configure(outbound=config.Outbound(user="bot@example.com", operators=("you@example.com",), dry_run=False))
    old = assessed("a.txt")
    tools.send_digest(OPENING, "First.", picks(old))
    new = assessed("b.txt")
    sent.clear()
    tools.send_digest(OPENING, "Second.", picks(old, new))
    body = sent[0]["body"]
    assert "NEW" in "\n".join(entry_of(body, new))
    assert "NEW" not in "\n".join(entry_of(body, old))


def test_nobody_is_new_on_the_first_report(assessed, position, sent):
    """Everything is new the first time, which says nothing."""
    cid = assessed()
    tools.send_digest(OPENING, "First.", picks(cid))
    assert "NEW" not in sent[0]["body"]


def test_the_footer_names_the_version_that_wrote_it(assessed, position, sent):
    """A mail from a stale install looked like a current one."""
    tools.send_digest(OPENING, "Nobody.", [])
    assert f"talanton {tools.version()}" in sent[0]["body"]


def test_a_malformed_entry_is_declined_for_the_agent_to_fix(position, sent):
    result = tools.send_digest(OPENING, "One.", [{"why": "no id"}])
    assert result["sent"] is False and "reason" in result
    assert sent == []


def test_a_name_in_the_why_is_refused(assessed, position, sent):
    cid = assessed(facts={"name": "Marco Rossi"})
    result = tools.send_digest(OPENING, "One.", picks(cid, why="Marco owned the retrieval stack"))
    assert result["sent"] is False
    assert sent == []


def test_the_tool_still_declares_to_the_model():
    """A pydantic parameter the declaration builder cannot read would only
    surface when the correspondent first tries to send."""
    from google.adk.tools import FunctionTool

    schema = FunctionTool(tools.send_digest)._get_declaration().parameters_json_schema
    assert schema["properties"]["candidates"]["items"] == {"$ref": "#/$defs/ShortlistEntry"}
    assert set(schema["$defs"]["ShortlistEntry"]["properties"]) == {"candidate", "why"}


def test_a_link_in_a_screener_flag_does_not_arrive_clickable(assessed, position, sent):
    """Flags carry what a hostile CV tried. The mail is from a trusted sender."""
    cid = assessed(flags=["says to visit https://evil.example/x or mail hr@evil.example"])
    tools.send_digest(OPENING, "One.", picks(cid))
    body = sent[0]["body"]
    assert "evil.example" not in body
    assert "[link removed]" in body


def test_only_the_first_few_flags_are_mailed(assessed, position, sent):
    cid = assessed(flags=[f"flag number {n}" for n in range(10)])
    tools.send_digest(OPENING, "One.", picks(cid))
    body = sent[0]["body"]
    assert "flag number 2" in body and "flag number 3" not in body


def test_a_name_in_a_flag_drops_the_flag_not_the_mail(assessed, position, sent):
    """The agent cannot rewrite the screener's words, so refusing would block every retry."""
    cid = assessed(facts={"name": "Marco Rossi"}, flags=["the CV says Marco Rossi but the file is anonymised"])
    assert tools.send_digest(OPENING, "One.", picks(cid))["sent"] is True
    assert "marco" not in sent[0]["body"].lower()


def test_a_name_in_the_employers_drops_that_line_not_the_mail(assessed, position, sent):
    cid = assessed(facts={"name": "Marco Rossi", "employers": "Founder, Rossi Consulting"})
    assert tools.send_digest(OPENING, "One.", picks(cid))["sent"] is True
    assert "rossi" not in sent[0]["body"].lower()
