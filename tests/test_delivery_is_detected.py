"""Whether a shortlist went out, detected through the path it actually takes.

`shortlist` sends a standing report when it believes nothing was delivered, so
an operator who receives nothing can tell that from a pipeline that failed
silently. The belief was read from the outer runner's event stream — and
`send_digest` is held by the correspondent, which `AgentTool` runs in a runner
of its own, consuming those events and returning only text.

So the result never arrived, `delivered` was always empty, and every delivered
shortlist was followed a minute later by a contradicting report under the same
subject. An operator takes the later mail as the truer one and drops a
candidate who cleared the bar.

These drive the real agent path against a fake model. A stub of `converse`
would pass while the bug was live, which is how it survived two releases.
"""

from collections.abc import AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from talanton import run, tools
from tests.conftest import OPENING


class FakeCorrespondentModel(BaseLlm):
    """Calls send_digest once, as the correspondent does, then reports."""

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        called = any(
            part.function_response for content in (llm_request.contents or []) for part in (content.parts or [])
        )
        part = (
            types.Part(text="Shortlist sent.")
            if called
            else types.Part(
                function_call=types.FunctionCall(
                    name="send_digest",
                    args={"opening": OPENING, "summary": "One worth reading.", "candidates": []},
                )
            )
        )
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class FakeRootModel(BaseLlm):
    """Delegates to the correspondent, as root_agent does."""

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        called = any(
            part.function_response for content in (llm_request.contents or []) for part in (content.parts or [])
        )
        part = (
            types.Part(text="I handed the correspondent a shortlist.")
            if called
            else types.Part(function_call=types.FunctionCall(name="correspondent", args={"request": "send it"}))
        )
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def _app() -> App:
    correspondent = LlmAgent(
        name="correspondent",
        model=FakeCorrespondentModel(model="fake-correspondent"),
        instruction="Send it.",
        tools=[tools.send_digest],
    )
    root = LlmAgent(
        name="root",
        model=FakeRootModel(model="fake-root"),
        instruction="Delegate to the correspondent.",
        tools=[AgentTool(agent=correspondent)],
    )
    return App(name="probe", root_agent=root)


def test_a_delivery_made_through_the_correspondent_is_seen(position, assessed, sent):
    """The bug, at its root. AgentTool consumes the inner events, so nothing
    the outer stream carries can ever say a digest went out — the delivery has
    to be recorded where it happens."""
    assessed("anna.txt")
    with tools.deliveries_recorded() as delivered:
        run.converse("send the shortlist", agent_app=_app())
    assert sent, "the fake never actually sent, so this test proves nothing"
    assert delivered, "a digest was delivered and the run could not tell"


def test_a_delivered_shortlist_is_not_followed_by_a_report(position, assessed, sent, monkeypatch):
    """The symptom: two emails a minute apart, same subject, contradicting
    each other. An operator takes the later one as the truer one."""
    assessed("anna.txt")
    monkeypatch.setattr(run, "app", _app())
    run.shortlist(OPENING)
    assert len(sent) == 1, f"sent {len(sent)}: {[m['subject'] for m in sent]}"


def test_a_run_that_delivered_nothing_still_reports(position, assessed, sent, monkeypatch):
    """The behaviour that must survive the fix: silence cannot distinguish an
    empty pool from a broken run, so a run with no shortlist still reports."""
    assessed("anna.txt")
    monkeypatch.setattr(run, "converse", lambda q, user_id="operator", agent_app=None: run.Turn(text="nobody"))
    run.shortlist(OPENING)
    assert len(sent) == 1
    assert "No candidate cleared the bar" in sent[0]["body"]
