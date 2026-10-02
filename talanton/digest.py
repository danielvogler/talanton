"""The shortlist mail, laid out in code.

The correspondent decides who is on the shortlist, in what order, and says in
one line why. Everything else in an entry is a recorded fact, and is written
here rather than by the model: a model formatting twenty entries by hand drifts
a column every few, and it put the CV links in a second list at the bottom that
an operator had to match against the first by hash.

Every part of an entry other than the id, the link and the reason is optional.
A pool can be a folder of CVs somebody dropped in by hand, with no board, no
date and a screener that could not find the years; such an entry is short, not
a column of placeholders.
"""

import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# How an application got in, said in words an operator reads rather than the
# value the record stores. Anything else is reported as the record spells it.
ROUTES = {"mailbox": "by email", "import": "imported"}

# An arrival record's `source` is free text where it is a board or a referrer.
# It is rendered into a mail, so it is held to one line of reasonable length.
MAX_SOURCE_LENGTH = 60

# Text from the screener or the correspondent, held to one readable line each.
# Long enough for "eight years, ETH then Google Zürich"; short enough that one
# entry cannot push the rest of the list off a phone screen.
MAX_EMPLOYERS_LENGTH = 120
MAX_FLAG_LENGTH = 160
MAX_WHY_LENGTH = 240

# Flags are the screener's notes, and a hostile CV can steer them. The mail
# carries the first few; the rest are in the assessment for whoever opens it.
MAX_FLAGS = 3

# Links and addresses in text that came out of a CV. The mail is from a sender
# the operator trusts, and a URL a stranger wrote should not arrive clickable
# under that sender, directly beneath the real CV link.
FOREIGN_LINK = re.compile(r"\b(?:https?://|www\.)\S+|\S+@\S+\.\w+", re.IGNORECASE)

# Facts the schema uses to say "the document does not say".
UNANSWERED = (None, "", "unknown")

# How an unestablished fact is named on an entry's "Open:" line.
FACT_LABELS = {"years_industry": "years in industry"}

ACCESS_NOTE = "Access is controlled on the folder. If you cannot open one, you were not given access."


class ShortlistEntry(BaseModel):
    """One shortlisted candidate, as the correspondent hands it over."""

    model_config = ConfigDict(frozen=True)

    candidate: str = Field(description="The candidate id, e.g. c-1a2b3c4d.")
    why: str = Field(
        default="",
        description="One line on why this person is worth the operator's time. Ids, never names.",
    )


def one_line(value: Any, limit: int = MAX_SOURCE_LENGTH) -> str:
    """A recorded value as a single bounded line, or "" if there is none."""
    if value in UNANSWERED:
        return ""
    collapsed = " ".join(str(value).split())
    if collapsed.casefold() == "unknown":
        return ""
    return collapsed[:limit]


def quoted(value: Any, limit: int) -> str:
    """CV-derived text as one bounded line, with any link or address taken out."""
    return one_line(FOREIGN_LINK.sub("[link removed]", str(value or "")), limit)


def arrival_line(record: dict[str, Any]) -> str:
    """When one application came in and by which route.

    The route, never the sender. A mailbox record's `source` is the address the
    application arrived from, and an address identifies as surely as a name
    does — which is why only `via` is used for that route, and why the board or
    referrer behind an import, which identifies nobody, is.

    `sent` is the date the applicant's own mail client claims; `arrived` is
    when talanton read the mailbox. They are different claims, so they are
    given different verbs rather than being averaged into one date.
    """
    if not record:
        return "arrival not recorded"

    via = str(record.get("via") or "").strip()
    route = ROUTES.get(via) or (f"via {via}" if via else "route not recorded")
    if via == "import" and (source := one_line(record.get("source"))):
        route = f"{route} from {source}"

    if sent := one_line(record.get("sent")):
        return f"applied {sent}, {route}"
    if arrived := one_line(record.get("arrived")):
        return f"arrived {arrived}, {route}"
    return route


class Found(BaseModel):
    """What the store holds for one shortlisted candidate."""

    model_config = ConfigDict(frozen=True)

    uri: str
    assessment: dict[str, Any]
    missing: list[str] = Field(default_factory=list)
    arrival: str = ""
    new: bool = False


def _headline(number: int, width: int, candidate: str, assessment: dict[str, Any]) -> str:
    """`  3. c-1a2b3c4d  score 8.5  ·  8 yrs` — the years only when known.

    The score is always there: with the link, it is the part of an entry an
    operator cannot do without.
    """
    score = assessment.get("overall")
    if score is None:
        shown = "unscored"
    else:
        shown = f"score {score:g}" if isinstance(score, float) else f"score {score}"
    parts = [f"  {number:>{width}}. {candidate}", shown]
    years = one_line((assessment.get("facts") or {}).get("years_industry"))
    if years:
        parts.append(f"·  {years} yrs" if _is_number(years) else f"·  {years}")
    return "  ".join(parts)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _open_line(missing: list[str], flags: list[Any], keep: Callable[[str], bool]) -> str:
    """What to ask: facts the CV did not settle, then what the screener flagged."""
    parts = []
    if missing:
        parts.append("Open: " + ", ".join(FACT_LABELS.get(fact, fact.replace("_", " ")) for fact in missing))
    checks = [line for flag in flags[:MAX_FLAGS] if (line := quoted(flag, MAX_FLAG_LENGTH)) and keep(line)]
    if checks:
        parts.append("Check: " + "; ".join(checks))
    return ". ".join(parts)


def entry(
    number: int,
    width: int,
    pick: ShortlistEntry,
    found: Found,
    keep: Callable[[str], bool],
) -> list[str]:
    """The lines of one entry. The CV link sits directly under the id, above
    any board name a mail client would turn into a link of its own.

    `keep` decides whether a line taken from the CV may go out. One that names
    somebody is left out rather than refusing the mail: the agent cannot
    rewrite text it did not write, so a refusal would block every retry.
    """
    indent = f"  {'':>{width}}  "
    employers = quoted((found.assessment.get("facts") or {}).get("employers"), MAX_EMPLOYERS_LENGTH)
    arrival = " · ".join(part for part in ("NEW" if found.new else "", found.arrival) if part)
    lines = [
        _headline(number, width, pick.candidate, found.assessment),
        f"{indent}CV: {found.uri}",
        employers if employers and keep(employers) else "",
        arrival,
        _open_line(found.missing, found.assessment.get("flags") or [], keep),
        one_line(pick.why, MAX_WHY_LENGTH),
    ]
    return [lines[0], lines[1], *(f"{indent}{line}" for line in lines[2:] if line)]


def entries(
    picks: list[ShortlistEntry],
    found: dict[str, Found],
    keep: Callable[[str], bool] = lambda _: True,
) -> str:
    """The numbered shortlist, one entry per pick the store could back."""
    shown = [pick for pick in picks if pick.candidate in found]
    if not shown:
        return ""
    width = len(str(len(shown)))
    blocks = [
        "\n".join(entry(n, width, pick, found[pick.candidate], keep)) for n, pick in enumerate(shown, start=1)
    ]
    return "\n\n".join(blocks)


def arrivals(records: dict[str, dict[str, Any]], candidates: list[str]) -> dict[str, str]:
    """Each candidate's arrival line, or nothing for any of them.

    Among dated entries, a missing date is named, because silence there reads
    as an omission. Where none of the shortlisted has a record — a folder of
    CVs put there by hand — the line is left out of every entry instead of
    saying "not recorded" twenty times.
    """
    if not any(records.get(c) for c in candidates):
        return {}
    return {c: arrival_line(records.get(c) or {}) for c in candidates}


def cut_line(size: int, next_scores: list[float]) -> str:
    """What the places just below the cut scored, so a tie there is visible."""
    shown = [f"{score:g}" for score in next_scores]
    if len(shown) == 1:
        return f"Place {size + 1} scored {shown[0]}."
    if len(shown) == 2:
        return f"Places {size + 1} and {size + 2} scored {shown[0]} and {shown[1]}."
    return ""


def footer(counts_line: str, version: str, linked: bool, cut: str = "") -> str:
    """The cut, the counts, the access note when there are links, and the version."""
    lines = [cut, counts_line] if cut else [counts_line]
    if linked:
        lines += ["", ACCESS_NOTE]
    if version:
        lines += ["", f"talanton {version}"]
    return "\n".join(lines)
