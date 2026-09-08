"""Who a human never has to look at, decided in code rather than in prose.

A knockout is pass/fail and is never traded off against a strong score
elsewhere. That rule is worth nothing if it lives only in a prompt, so it is
enforced here: an excluded candidate is filtered out of every listing the agent
can see, which means the agent cannot write about them in a digest even if it
wanted to.

Nothing here deletes or rejects anyone. Exclusion is a filter on what reaches
the operator's inbox, and `excluded` lists exactly who it caught and why, so a
person can audit the filter and unset it.
"""

from typing import Any

# A knockout the CV simply does not answer is not a failure. Those candidates
# get asked, they are not filtered.
FAILED = "fail"


def min_score(position: dict[str, Any]) -> float:
    """The score below which a candidate is not worth the operator's time.

    Absent from the position file, there is no floor — every assessed candidate
    reaches the digest. A floor is opt-in, because a badly set one silently
    discards people.
    """
    screening = position.get("screening") or {}
    floor = screening.get("min_score")
    return float(floor) if floor is not None else -1.0


def exclusions(assessment: dict[str, Any], position: dict[str, Any]) -> tuple[str, ...]:
    """Why this candidate should not reach the operator, if they should not.

    Args:
        assessment: The saved assessment. Empty means unassessed.
        position: The loaded position file.

    Returns:
        tuple[str, ...]: Reasons, empty when the candidate stands.
    """
    if not assessment:
        return ()  # unassessed is not rejected; it is unfinished

    verdicts = assessment.get("knockouts")
    if verdicts is not None and not isinstance(verdicts, dict):
        # A list of objects, say. Nothing here can read that, and guessing at
        # it would be guessing about whether somebody stays in the process.
        return (f"malformed:knockouts is {type(verdicts).__name__}, not a map of id to verdict",)

    verdicts = verdicts or {}
    reasons = [
        f"knockout:{knockout}"
        for knockout, verdict in verdicts.items()
        if str(verdict).strip().lower() == FAILED
    ]

    floor = min_score(position)
    if floor >= 0:
        overall = numeric(assessment.get("overall"))
        if overall is None:
            reasons.append("unscored:overall is missing or not a number")
        elif overall < floor:
            reasons.append(f"below-bar:{overall}<{floor}")

    return tuple(reasons)


def declared(position: dict[str, Any]) -> tuple[str, ...]:
    """The knockout ids this position defines, in order."""
    return tuple(str(k["id"]) for k in (position.get("knockouts") or []) if isinstance(k, dict) and k.get("id"))


def unanswered(assessment: dict[str, Any], position: dict[str, Any]) -> tuple[str, ...]:
    """Knockouts the position declares that this assessment never mentions.

    Deliberately not an exclusion. A knockout the CV does not answer is not a
    failure — those candidates get asked, they are not filtered — and that rule
    holds whether the silence is the CV's or the model's.

    It is reported instead, so a gap in an assessment is visible next to the
    candidate rather than reading as a clean pass. Absent from the listing, a
    dropped knockout id looks exactly like one that was checked.
    """
    verdicts = assessment.get("knockouts")
    verdicts = verdicts if isinstance(verdicts, dict) else {}
    return tuple(k for k in declared(position) if k not in verdicts)


def dimensions(position: dict[str, Any]) -> tuple[str, ...]:
    """The rubric dimension ids this position defines, in order."""
    return tuple(str(d["id"]) for d in (position.get("rubric") or []) if isinstance(d, dict) and d.get("id"))


def unscored(assessment: dict[str, Any], position: dict[str, Any]) -> tuple[str, ...]:
    """Rubric dimensions this assessment carries no score for.

    Same reasoning as `unanswered`: reported, not punished. An overall score
    with no dimensions behind it is not wrong, but it is not traceable to the
    written standard either, and that is worth seeing.
    """
    scored = assessment.get("dimensions")
    scored = scored if isinstance(scored, dict) else {}
    return tuple(d for d in dimensions(position) if d not in scored)


def numeric(value: Any) -> float | None:
    """A score as a number, or None when it cannot be read as one.

    A model can return "8" instead of 8. Reading it is right; treating it as
    absent and skipping the floor, as this used to, is not — every unreadable
    score would clear every bar.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def is_excluded(assessment: dict[str, Any], position: dict[str, Any]) -> bool:
    """Whether this candidate is filtered out of everything the agent sees."""
    return bool(exclusions(assessment, position))
