"""The stages, and the loop that runs them.

The core is two stages and needs no mailbox at all:

    assess     read the CVs that have no assessment yet, and assess them
    shortlist  rank what is assessed, and hand the operator who is worth reading

Mail is an adapter on either side, and the two sides hold different
credentials on purpose:

    inbound    reads the apply mailbox. IT CANNOT SEND — no SMTP path, and no
               import of the module that has one. A message a candidate writes
               cannot provoke a reply.
    outbound   sends the shortlist. A separate account, with no access to the
               apply mailbox, so it could not read a CV if it were misused.

Run them by hand from a coding agent, or on a schedule. Nothing is kept warm
between runs; every stage reads its state from the configured locations.
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from google.genai import types

from . import inbound
from .agent import app
from .config import current

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s", force=True)

RETRY_DELAY_SECONDS = 10

ASSESS_PROMPT = (
    "Assess the CVs for opening {role} that do not have an assessment yet.\n\n"
    "Read the position file first. Call list_new_cvs for that opening's queue, then "
    "assess_cv on each one, which reads the CV, screens it and saves the result. "
    "A CV that comes back unreadable is not a zero — nothing is saved for it, so "
    "report the filename. Finish by saying how many you assessed, how many were "
    "unreadable, and how many the knockout filter excluded."
)

RESCREEN_PROMPT = (
    "The rubric for opening {role} has changed. Assess EVERY CV again, including those already "
    "assessed and those the filter is holding back, and overwrite each assessment.\n\n"
    "Read the position file first, then list_candidates and list_excluded so you have "
    "the whole pool. Call assess_cv on every CV again. Report who moved: who now "
    "clears the bar who did not before, and who no longer does."
)

SHORTLIST_PROMPT = (
    "For opening {role}, list the assessed candidates and decide who is worth the operator's "
    "time. If any are, hand the correspondent a shortlist saying who and why and what "
    "to ask them, with their ids so the CV links are included. Refer to candidates by "
    "id only, never by name. If none clear the bar, send a digest saying so with an "
    "empty candidate list — every run reports, including the ones with nothing to report."
)

NOBODY_CLEARED = (
    "No candidate cleared the bar for opening {role} in this run.\n\n"
    "This message is sent whether or not there is a shortlist, on purpose: silence "
    "would not tell you whether nobody applied, everybody was held back, or the run "
    "failed. The counts below say which."
)

SHORTLIST_DECLINED = (
    "A shortlist for opening {role} was prepared but declined before sending, so nobody "
    "has been recommended in this run.\n\n"
    "The reason is in the run log and is deliberately not repeated here: the usual cause "
    "is a summary naming a candidate, and putting that reason in this mail would send the "
    "name the guard just refused."
)


class StageFailedError(RuntimeError):
    """Raised when a stage did not actually do its work.

    The runner logs model errors and carries on, which would otherwise leave a
    stage exiting zero having assessed nobody. A run that produced nothing is a
    failure and has to be reported as one.
    """


@dataclass(frozen=True)
class Turn:
    """What one agent turn produced, beyond the text it ended with.

    `delivered` and `declined` are read off the tool results rather than out of
    the agent's prose, because whether a shortlist actually went out is a fact
    about the process and not something to infer from what it says it did.
    """

    text: str
    delivered: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()


def responses(event) -> list[dict]:
    """Every tool result carried by one event."""
    found = []
    for part in (event.content.parts if getattr(event, "content", None) else []) or []:
        response = getattr(part.function_response, "response", None) if part.function_response else None
        if isinstance(response, dict):
            found.append(response)
    return found


def tool_failures(event) -> list[str]:
    """Delivery failures a tool reported, which the runner would otherwise absorb.

    An exception raised inside a tool call becomes text in a function response
    and the turn carries on, so `cycle` exited zero having sent nothing and
    anything scheduled on top of it read that as a good run.

    A tool that could not do its work answers with `error`. A `reason` is
    deliberately not read here: that is a guardrail declining, which the agent
    can act on and retry.
    """
    return [str(r["error"]) for r in responses(event) if r.get("error")]


def converse(question: str, user_id: str = "operator") -> Turn:
    """Puts a question to the agent and reports what the turn actually did.

    Raises:
        StageFailedError: If the run errored, or produced no text at all.
    """
    from google.adk.runners import InMemoryRunner

    runner = InMemoryRunner(app=app)
    session = asyncio.run(runner.session_service.create_session(app_name=app.name, user_id=user_id))
    said: list[str] = []
    errors: list[str] = []
    delivered: list[str] = []
    declined: list[str] = []

    for event in runner.run(
        user_id=user_id,
        session_id=session.id,
        new_message=types.Content(role="user", parts=[types.Part(text=question)]),
    ):
        message = getattr(event, "error_message", None)
        if message:
            errors.append(str(message))
        errors.extend(tool_failures(event))
        for response in responses(event):
            if response.get("sent") is True:
                delivered.extend(str(a) for a in response.get("to") or ("operator",))
            elif response.get("reason"):
                declined.append(str(response["reason"]))
        for part in (event.content.parts if event.content else []) or []:
            if part.text:
                said.append(part.text)

    text = "".join(said).strip()
    if errors:
        raise StageFailedError("; ".join(dict.fromkeys(errors)))
    if not text:
        raise StageFailedError(
            "the agent produced no output. The run log above usually says why — most often "
            "the model is unreachable or the model id is not served in this region."
        )
    return Turn(text=text, delivered=tuple(delivered), declined=tuple(declined))


def ask(question: str, user_id: str = "operator") -> str:
    """Puts a question to the agent and returns its final text."""
    return converse(question, user_id).text


# ---------------------------------------------------------------- core stages


def assess(role: str, rescreen: bool = False) -> str:
    """Assess the CVs waiting in the CVs location.

    Args:
        role: The role to assess against.
        rescreen: Re-assess everyone, after a rubric change, so the new
            standard applies to the whole pool rather than only to whoever
            arrives next.
    """
    prompt = RESCREEN_PROMPT if rescreen else ASSESS_PROMPT
    return ask(prompt.format(role=role), user_id="system")


def shortlist(role: str) -> str:
    """Hand the operator whoever is worth reading, by id, with CV links.

    Always sends. If the agent recommended nobody, or its shortlist was
    declined, the report goes out anyway with the counts — an operator who
    receives nothing cannot tell that from a pipeline that failed silently.
    """
    turn = converse(SHORTLIST_PROMPT.format(role=role), user_id="system")
    if not turn.delivered:
        report(role, turn)
    return turn.text


def report(role: str, turn: Turn) -> None:
    """Sends the standing report for a run that produced no shortlist.

    Goes through `send_digest` rather than around it, so the allowlist and the
    name check apply to this mail exactly as they do to a real shortlist.

    Raises:
        StageFailedError: If the report itself could not be delivered.
    """
    from . import tools

    template = SHORTLIST_DECLINED if turn.declined else NOBODY_CLEARED
    result = tools.send_digest(role, template.format(role=role), [])

    if result.get("error"):
        raise StageFailedError(f"the run produced no shortlist and the report failed: {result['error']}")
    if not result.get("sent"):
        # No operator address is a documented setup, not a fault: `check` says
        # so, and `status` is how that deployment reads a run.
        logging.info("No report sent: %s", result.get("reason"))


def cycle(role: str) -> dict[str, str]:
    """Everything, in order: fetch if a mailbox is configured, assess, shortlist."""
    reported = {}
    if current().inbound.user:
        reported["fetched"] = f"{len(inbound.fetch())} new CV(s)"
    reported["assessed"] = assess(role)
    reported["shortlist"] = shortlist(role)
    return reported


def wait_for_mail() -> None:
    """Blocks on IMAP IDLE until something arrives or the timeout expires.

    The session is closed on every path. This loop runs for weeks, and a
    provider counts simultaneous IMAP connections: one dropped unclosed per
    transient failure exhausts the account's allowance and the watch stops
    working until somebody restarts the process.
    """
    session = inbound.client()
    try:
        session.select_folder("INBOX")
        session.idle()
        try:
            session.idle_check(timeout=current().schedule.idle_timeout_seconds)
        finally:
            session.idle_done()
    finally:
        session.logout()


def watch(role: str) -> None:
    """Runs the cycle, then waits on IMAP IDLE for the next message."""
    while True:
        try:
            cycle(role)
            wait_for_mail()
        except Exception as exc:
            logging.error("Cycle failed: %s", exc, exc_info=True)
            time.sleep(RETRY_DELAY_SECONDS)
