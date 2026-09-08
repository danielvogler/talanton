"""The position file: one YAML per role, and the backbone of everything.

It carries the ad copy, the knockouts and the rubric together, because they are
the same decision written three ways. Change what the role requires and the ad,
the screening standard and the questions candidates get asked all move with it.

    <store>/openings/<number>-<id>.yaml

Board ads are generated from it and pasted by a human. Nothing here posts
anything anywhere, and nothing here logs into a job board — automating those
interfaces breaks their terms and risks the company account.
"""

from typing import Any

import yaml

from .config import current

OPENINGS_DIR = "openings"
REQUIRED_FIELDS = ("opening", "id", "title", "pitch", "apply_to", "closes")
SECTIONS = (
    ("responsibilities", "What you will do"),
    ("requirements", "What we need from you"),
    ("nice_to_have", "Nice to have"),
)


class PositionError(ValueError):
    """Raised when a position file is missing something a board ad needs."""


class AmbiguousOpeningError(ValueError):
    """Raised when a reference matches more than one opening."""


def slug(position: dict[str, Any]) -> str:
    """The folder name for one opening: `123-ai-engineer`.

    Every opening gets its own drawer in each location, so five AI engineer
    postings do not share a pile of CVs and nobody has to work out which
    applicant meant which.
    """
    return f"{position['opening']}-{position['id']}"


def path(role: str):
    return current().store / OPENINGS_DIR / f"{role}.yaml"


def resolve(reference: str) -> dict[str, Any]:
    """Finds one opening from whatever the operator typed.

    Accepts the number on its own (`123`), the full slug (`123-ai-engineer`),
    or the role id when only one opening is using it. Anything ambiguous is
    refused rather than guessed — screening someone against the wrong posting
    is not a mistake worth risking to save a few keystrokes.

    Args:
        reference: What the operator typed.

    Returns:
        dict: The loaded position.

    Raises:
        FileNotFoundError: If nothing matches.
        AmbiguousOpeningError: If more than one does.
    """
    wanted = str(reference).strip().lower()
    matches = []
    for role in all_roles():
        try:
            position = load(role)
        except (PositionError, FileNotFoundError):
            continue
        if wanted in {str(position["opening"]).lower(), slug(position).lower(), str(position["id"]).lower()}:
            matches.append(position)

    if not matches:
        known = ", ".join(f"{slug(p)}" for p in every()) or "none yet"
        raise FileNotFoundError(f"no opening matching {reference!r}. Open: {known}")
    if len(matches) > 1:
        raise AmbiguousOpeningError(
            f"{reference!r} matches {len(matches)} openings: {', '.join(slug(p) for p in matches)}. "
            "Give the number."
        )
    return matches[0]


def every() -> list[dict[str, Any]]:
    """Every position that parses, ordered by opening number."""
    out = []
    for role in all_roles():
        try:
            out.append(load(role))
        except (PositionError, FileNotFoundError):
            continue
    return sorted(out, key=lambda p: str(p["opening"]))


def load(role: str) -> dict[str, Any]:
    """Reads and checks one position file.

    Args:
        role: The position id, e.g. "ai-engineer".

    Returns:
        dict: The parsed position.

    Raises:
        FileNotFoundError: If there is no such position.
        PositionError: If a required field is missing.
    """
    target = path(role)
    if not target.exists():
        raise FileNotFoundError(f"no position file at {target}")
    position = yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    missing = [f for f in REQUIRED_FIELDS if not position.get(f)]
    if missing:
        raise PositionError(f"{target} is missing required field(s): {', '.join(missing)}")
    return position


def all_roles() -> list[str]:
    """Every position id with a file."""
    directory = current().store / OPENINGS_DIR
    return sorted(p.stem for p in directory.glob("*.yaml")) if directory.exists() else []


def apply_addresses() -> dict[str, str]:
    """Maps each position's apply address to its role id, for routing intake.

    A company running three roles gives each one its own address — or one
    address with a plus tag — and an application lands against the right
    position without anyone setting an environment variable.
    """
    out = {}
    for role in all_roles():
        try:
            out[str(load(role)["apply_to"]).strip().lower()] = role
        except (PositionError, KeyError):
            continue  # a half-written position must not break intake for the others
    return out


def rubric_text(position: dict[str, Any]) -> str:
    """Renders the screening standard the screener is given.

    Knockouts are kept apart from scored dimensions on purpose: a knockout is
    not something a high score elsewhere can compensate for.
    """
    lines = [f"# Rubric for {position['title']} (version {position.get('version', 1)})", ""]

    if position.get("knockouts"):
        lines.append("## Knockouts — pass or fail, never traded off against a score")
        for knockout in position["knockouts"]:
            lines.append(f"- {knockout['id']}: {knockout['test']}")
        lines.append("")

    lines.append("## Scored dimensions")
    for dimension in position.get("rubric", []):
        lines += [f"\n### {dimension['id']} — weight {dimension['weight']}%", dimension["guide"].strip()]

    if position.get("must_not_influence"):
        lines += ["", "## Must not influence the score", *[f"- {x}" for x in position["must_not_influence"]]]

    return "\n".join(lines)


def board_ad(position: dict[str, Any], board: str) -> str:
    """Renders paste-ready ad copy for one job board.

    Over-length copy is flagged, never silently cut — a human decides what goes.

    Args:
        position: A loaded position.
        board: A key under the position's `boards`.

    Returns:
        str: The text to paste, with any length warnings at the top.
    """
    limits = (position.get("boards") or {}).get(board) or {}
    title = _title(position, limits)
    warnings = []

    if limits.get("title_max") and len(title) > limits["title_max"]:
        warnings.append(f"!! TITLE IS {len(title)} CHARS, LIMIT {limits['title_max']} — shorten before pasting")

    body = [position["pitch"].strip(), ""]
    for key, heading in SECTIONS:
        if position.get(key):
            body += [heading + ":", *[f"- {item}" for item in position[key]], ""]

    text = "\n".join([*body, *[line for line in _tail(position) if line]])

    if limits.get("body_max") and len(text) > limits["body_max"]:
        warnings.append(f"!! BODY IS {len(text)} CHARS, LIMIT {limits['body_max']} — trim before pasting")

    header = [f"=== {board}: paste this ===", *warnings, "", f"TITLE: {title}", "", "BODY:", ""]
    footer = (
        ["", "Setup for this board:", *[f"- {s}" for s in limits.get("setup", [])]]
        if limits.get("setup")
        else []
    )
    return "\n".join([*header, text, *footer])


def _title(position: dict[str, Any], limits: dict[str, Any]) -> str:
    """A board may carry its own title, for one that indexes better there."""
    return str(limits.get("title") or position["title"])


def _tail(position: dict[str, Any]) -> list[str]:
    where = position.get("location", "")
    return [
        f"Location: {where} ({position.get('workplace', 'onsite')})" if where else "",
        _salary(position),
        f"Apply: {position['apply_to']}",
        f"Closes: {position['closes']}",
    ]


def _salary(position: dict[str, Any]) -> str:
    salary = position.get("salary")
    if not salary:
        return ""
    low, high, currency = salary.get("min"), salary.get("max"), salary["currency"]
    if low and high:
        return f"Salary: {currency} {low:,} – {high:,} per year"
    return f"Salary: {currency} {low or high:,} per year"


def ads(position: dict[str, Any]) -> str:
    """Every board ad for one opening, ready to paste."""
    return "\n\n".join(board_ad(position, board) for board in (position.get("boards") or {}))
