"""Least privilege across the three agents. These are the invariants."""

import asyncio
import inspect
import json

from talanton import correspondent, root_agent, screener, store, tools
from tests.conftest import OPENING

# The README claims this system gathers only what the candidate sent, from
# nowhere else, and cannot contact anyone. Both are true only while the tool
# surface stays exactly this.
ROOT_TOOLS = {
    "correspondent",
    "get_position",
    "list_openings",
    "list_new_cvs",
    "assess_cv",
    "list_candidates",
    "list_excluded",
    "get_candidate",
}


def names(agent):
    return [getattr(t, "__name__", getattr(t, "name", "?")) for t in agent.tools]


def test_the_screener_has_no_tools():
    """Whatever reads untrusted text cannot act."""
    assert screener.tools == []


def test_the_root_agent_cannot_send_anything():
    for tool in names(root_agent):
        assert "send" not in tool, f"root can send via {tool}"


def test_the_correspondent_holds_exactly_one_tool():
    assert set(names(correspondent)) == {"send_digest"}


def test_the_root_agent_reaches_the_correspondent_but_not_the_screener():
    """It delegates delivery, and it no longer holds the screener directly.
    Reaching the screener meant holding the CV to hand it, which put applicant
    text in the context of an agent that can send."""
    assert "correspondent" in names(root_agent)
    assert "screener" not in names(root_agent)


def test_the_tool_surface_is_exactly_what_is_documented():
    assert set(names(root_agent)) == ROOT_TOOLS


# The complete set of tools any agent here may hold. A guard that only forbids
# name shapes passes a tool called `dispatch_to_applicant`; this one does not,
# because anything new has to be added here on purpose and explained.
PERMITTED = {
    "screener": set(),
    "correspondent": {"send_digest"},
    "hiring_assistant": {
        "correspondent",
        "get_position",
        "list_openings",
        "list_new_cvs",
        "assess_cv",
        "list_candidates",
        "list_excluded",
        "get_candidate",
    },
}


def test_no_agent_holds_a_tool_that_is_not_on_the_list():
    """An allowlist, not a list of forbidden words. Adding a capability has to
    be a deliberate edit here, with a reason in the diff."""
    for agent in (root_agent, correspondent, screener):
        extra = set(names(agent)) - PERMITTED[agent.name]
        assert not extra, f"{agent.name} has undeclared tools: {sorted(extra)}"


def test_the_list_itself_contains_nothing_that_reaches_a_candidate():
    """Guards the allowlist against a careless addition to it."""
    for tools_held in PERMITTED.values():
        for tool in tools_held:
            for forbidden in ("clarification", "reply", "notify", "contact", "applicant", "template"):
                assert forbidden not in tool.lower(), f"{tool} looks like it reaches a candidate"


def test_the_list_contains_nothing_that_reaches_outside():
    for tools_held in PERMITTED.values():
        for tool in tools_held:
            for forbidden in ("search", "http", "browse", "scrape", "url", "enrich"):
                assert forbidden not in tool.lower(), f"{tool} looks like it reaches outside"


def test_no_tool_anywhere_decides_anything():
    for tools_held in PERMITTED.values():
        for tool in tools_held:
            for forbidden in ("reject", "advance", "offer", "hire", "delete"):
                assert forbidden not in tool, f"a tool is named like {forbidden!r}"


def test_the_only_outbound_tool_takes_no_recipient():
    assert list(inspect.signature(tools.send_digest).parameters) == ["opening", "summary", "candidates"]


def test_the_agents_name_the_configured_company():
    from talanton import agent

    assert "Example Co" in agent.root_instruction()


def test_the_screener_declares_its_output_shape(configure):
    """The shape is a schema the API enforces, not a JSON example in a prompt
    that the model is trusted to have honoured."""
    from talanton import agent
    from talanton.assessment import Assessment

    assert agent.screener.output_schema is Assessment


def test_the_shape_is_enforced_on_every_model_not_only_gemini(configure):
    """The old mime-type workaround existed only on the Gemini path, which left
    the Anthropic-on-Vertex path with nothing but the prompt."""
    from talanton import agent

    assert not hasattr(agent, "_screener_config")
    assert agent.screener.generate_content_config.response_mime_type is None


def test_the_screener_declares_no_agent_mode(configure):
    """AgentTool runs the screener as the root of its own runner. ADK rejects
    mode="single_turn" there at call time, and mode="task" hands it a
    `finish_task` tool. `tests/test_screener_runtime.py` proves the
    consequences; this pins the setting itself."""
    from talanton import agent

    assert agent.screener.mode is None


def test_the_assessment_shape_survives_conversion_for_the_api(configure):
    """`dimensions` and `knockouts` are keyed by ids from the position file, so
    they have to reach the API as maps and not be flattened into bare objects."""
    from google.genai import _transformers

    from talanton.assessment import Assessment

    schema = _transformers.t_schema(None, Assessment)
    # Lists of records, not maps. A map becomes an object with no named
    # properties, which a model satisfies by returning {} -- three live runs
    # did exactly that, and every knockout went unevaluated.
    for field in ("dimensions", "knockouts"):
        assert schema.properties[field].type.name == "ARRAY", field
        assert "id" in schema.properties[field].items.properties


def test_an_unanswered_knockout_is_sayable(configure):
    """A knockout the CV does not address must not be forced to pass or fail;
    only "fail" removes somebody from the process."""
    from talanton.assessment import Assessment

    parsed = Assessment(overall=6, justification="x", dimensions={"d": 6}, knockouts={"work_permit": "unknown"})
    assert [(k.id, k.verdict) for k in parsed.knockouts] == [("work_permit", "unknown")]


def test_a_score_outside_the_scale_is_refused(configure):
    import pytest as _pytest
    from pydantic import ValidationError

    from talanton.assessment import Assessment

    with _pytest.raises(ValidationError):
        Assessment(overall=11, justification="x", dimensions={}, knockouts={})


def test_the_deciding_agents_never_constrain_their_output(configure):
    """Root and correspondent write prose and call tools; forcing JSON on them
    would break both."""
    from talanton import agent, config

    config.use(config.parse({"screening": {"model": "gemini-3.8-flash"}}))
    assert agent._content_config().response_mime_type is None


def test_the_root_agent_never_receives_applicant_text():
    """The claim is that whatever reads untrusted text cannot act. The screener
    has no tools, but `get_cv_text` was a root tool, so the CV landed in root's
    context on its way there -- and root can delegate to the correspondent,
    which sends. Root now gets an assessment, never the prose."""
    assert "get_cv_text" not in names(root_agent)
    assert "assess_cv" in names(root_agent)


def test_the_tool_that_reads_a_cv_returns_no_cv_text(configure, cv, position, monkeypatch):
    """Whatever assess_cv hands back goes into root's context, so it has to be
    the assessment and nothing else."""
    from talanton import tools

    cv("anna.txt", "Ten years shipping production systems, on call for all of them. " * 6)

    async def fake_screen(request: str, tool_context=None) -> dict:
        assert "Ten years shipping" in request, "the screener was not given the CV"
        return {
            "overall": 7,
            "dimensions": {},
            "facts": {"name": "Anna Mueller", "email": "anna@example.test"},
            "knockouts": {"work_permit": "pass"},
            "justification": "Owned a production system.",
            "probe": [],
            "flags": [],
        }

    monkeypatch.setattr(tools, "_screen", fake_screen)
    result = asyncio.run(tools.assess_cv(OPENING, "anna.txt"))

    flat = json.dumps(result)
    assert "Ten years shipping" not in flat, "applicant prose reached the caller"
    assert result["saved"] is True
    assert result["candidate"] == store.candidate_id("anna.txt")


def test_the_assessor_is_told_everything_the_root_agent_is_told():
    """Two copies of one instruction drift, and the copy that drifts is the one
    deployed unattended."""
    from talanton import agent

    # Everything below the first paragraph, which is the only part a company
    # name reaches. Both agents are built at import, against whatever config
    # was current then, so the shared text is what can be compared.
    body = agent.ROOT_INSTRUCTION_TEMPLATE.split("\n\n", 1)[1]
    assert body in agent.root_agent.instruction
    assert body in agent.assessor.instruction
    assert "cannot send anything" in agent.assessor.instruction
