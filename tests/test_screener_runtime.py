"""The screener as root_agent actually invokes it: through AgentTool.

Constructing an agent proves nothing. `AgentTool` runs the wrapped agent as the
root of its own runner, and ADK rejects some agent modes there — so a screener
that builds fine can still raise the first time anything calls it. These tests
drive the real path against a fake model, with no network and no credentials.

They also pin the two properties the security model depends on, which are
decided by ADK at request time rather than by the tool list we declare:
the screener is handed no tools, and its output shape reaches the API.
"""

import asyncio
import json
from collections.abc import AsyncGenerator

from google.adk.agents import LlmAgent
from google.adk.apps import App
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.runners import InMemoryRunner
from google.adk.tools.agent_tool import AgentTool
from google.genai import types

from talanton import agent
from talanton.assessment import Assessment

ASSESSMENT = {
    "overall": 7,
    "dimensions": {"production_experience": 8},
    "facts": {
        "name": "Marco Rossi",
        "email": "marco@example.test",
        "years_industry": "9",
        "work_authorisation": "citizen",
        "language": "English fluent",
        "notice_period": "3 months",
    },
    "knockouts": {"work_permit": "pass", "english": "unknown"},
    "justification": "Owned a production system including its failures.",
    "probe": ["Ask about the rollback."],
    "flags": [],
}


class FakeScreenerModel(BaseLlm):
    """Answers with an assessment, and records what it was asked."""

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        REQUESTS.append(llm_request)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=json.dumps(ASSESSMENT))]))


class FakeParentModel(BaseLlm):
    """Calls the screener once, the way root_agent does, then reports."""

    async def generate_content_async(self, llm_request, stream=False) -> AsyncGenerator[LlmResponse, None]:
        called = any(
            part.function_response for content in (llm_request.contents or []) for part in (content.parts or [])
        )
        part = (
            types.Part(text="assessed one")
            if called
            else types.Part(
                function_call=types.FunctionCall(
                    name="screener", args={"request": "the rubric, and the fenced CV"}
                )
            )
        )
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


REQUESTS: list = []


def call_screener_as_a_tool() -> list:
    """Runs a parent agent that delegates to the screener. Returns its replies."""
    REQUESTS.clear()
    screener = agent.screener.model_copy(update={"model": FakeScreenerModel(model="fake-screener")})
    parent = LlmAgent(
        name="parent",
        model=FakeParentModel(model="fake-parent"),
        instruction="Delegate to the screener.",
        tools=[AgentTool(agent=screener)],
    )

    async def run() -> list:
        runner = InMemoryRunner(app=App(name="probe", root_agent=parent))
        session = await runner.session_service.create_session(app_name="probe", user_id="u")
        replies = []
        async for event in runner.run_async(
            user_id="u",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text="assess opening 101")]),
        ):
            for part in (event.content.parts if event.content else []) or []:
                if part.function_response:
                    replies.append(part.function_response.response)
        return replies

    return asyncio.run(run())


def test_the_screener_can_actually_be_called_as_a_tool(configure):
    """AgentTool runs the screener as the root of its own runner, and ADK
    refuses some modes there. This is the test that catches that, because
    building the agent does not."""
    replies = call_screener_as_a_tool()
    assert replies, "root_agent called the screener and got nothing back"


def test_what_comes_back_is_a_valid_assessment(configure):
    replies = call_screener_as_a_tool()
    parsed = Assessment.model_validate(replies[0])
    assert parsed.overall == 7
    assert {k.id: k.verdict for k in parsed.knockouts}["english"] == "unknown"


def test_the_output_shape_reaches_the_api(configure):
    """The schema has to be on the request, not merely declared on the agent.
    `mode="task"` builds and runs, and silently drops it."""
    call_screener_as_a_tool()
    assert REQUESTS, "the screener's model was never called"
    assert REQUESTS[0].config.response_schema is not None


def test_the_screener_is_handed_no_tools_at_request_time(configure):
    """`tools=[]` is what we declare; this is what ADK actually sends. Some
    agent modes add one of their own, and a screener reading untrusted text
    must reach the model with nothing it can call."""
    call_screener_as_a_tool()
    declared = [
        function.name
        for tool in (REQUESTS[0].config.tools or [])
        for function in (tool.function_declarations or [])
    ]
    assert declared == [], f"the screener was given {declared}"
