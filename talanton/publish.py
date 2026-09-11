"""Publishing one opening: the board copy and the rubric, as a single file.

Screening output lands in a shared location; until now the opening it was
scored against did not. Somebody reading an assessment had no way to see the
ad or the bar without opening the repository that holds the position file.

This is write-only. Nothing reads the published copy back — the file in
`positions.OPENINGS_DIR` stays the source of truth, and a published copy that
has been edited in place is a stale artifact, never an input.
"""

from dataclasses import dataclass
from typing import Any

from . import config, locations, positions, store

# Plain text, so Drive previews it and a diff of it reads like prose.
SUFFIX = ".txt"
MARKER = "=== published by talanton ==="
WARNING = "This file is generated. Edits here are overwritten on the next publish."


class PublishError(RuntimeError):
    """Raised when there is nothing to publish, or nowhere to publish it."""


@dataclass(frozen=True)
class Result:
    """What one publish did, so the caller can report it without guessing."""

    body: str
    name: str
    written: bool
    unchanged: bool
    item: locations.Item | None = None


def _board(position: dict[str, Any], board: str) -> str:
    """The board whose copy gets published, defaulting to the first configured.

    A title can differ per board, so this is a real choice rather than a
    detail. Naming a board that does not exist is refused: publishing the
    wrong board's copy under the right filename is worse than failing.
    """
    boards = list(position.get("boards") or {})
    if not boards:
        raise PublishError(f"{positions.slug(position)} has no boards to publish. Add a [boards] entry.")
    if not board:
        return boards[0]
    if board not in boards:
        raise PublishError(f"no board {board!r} on {positions.slug(position)}. Configured: {', '.join(boards)}")
    return board


def header(position: dict[str, Any], note: str = "") -> list[str]:
    """Where this copy came from.

    Deliberately clock-free. An unchanged opening has to render byte-identical
    or `publish` can never tell a real change from a re-run, and every push
    burns a revision in the destination's history.
    """
    lines = [MARKER, f"source: {positions.slug(position)}.yaml"]
    if note:
        lines.append(f"note: {note}")
    return [*lines, WARNING, ""]


def render(position: dict[str, Any], board: str = "", note: str = "") -> str:
    """The published body: provenance, the board ad, then the rubric."""
    chosen = _board(position, board)
    return "\n".join(
        [
            *header(position, note),
            positions.board_ad(position, chosen),
            "",
            positions.rubric_text(position),
        ]
    )


def filename(position: dict[str, Any]) -> str:
    """The opening's slug. Stable across pushes, so a re-push replaces."""
    return f"{positions.slug(position)}{SUFFIX}"


def _existing(location: locations.Location, name: str) -> bytes | None:
    """What is already there under this name, or None.

    Used only to skip an identical write. A location that cannot be listed is
    not an error here — the write itself will report it far better.
    """
    try:
        for item in location.list():
            if item.name == name:
                return location.read(item)
    except locations.LocationError:
        return None
    return None


def publish(reference: str, board: str = "", note: str = "", dry_run: bool = False) -> Result:
    """Renders one opening and writes it to the openings location.

    Args:
        reference: An opening number, slug or role id — whatever the other
            commands take. Ambiguity is refused, not guessed.
        board: Which board's copy. Defaults to the first configured.
        note: Provenance the caller knows and this does not, carried verbatim.
        dry_run: Render and report, touching nothing.

    Returns:
        Result: The body, the filename, and what was actually done.

    Raises:
        PublishError: If no location is configured, or there is no copy.
    """
    spec = config.current().openings
    if not spec.configured:
        raise PublishError("no [storage.openings] configured. Add one to publish an opening.")

    position = positions.resolve(reference)
    body = render(position, board, note)
    name = filename(position)
    payload = body.encode("utf-8")

    if dry_run:
        return Result(body=body, name=name, written=False, unchanged=False)

    location = store.openings()
    if _existing(location, name) == payload:
        return Result(body=body, name=name, written=False, unchanged=True)

    item = location.write(name, payload)
    return Result(body=body, name=name, written=True, unchanged=False, item=item)
