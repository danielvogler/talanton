"""The documentation is the interface.

Someone points a coding agent at AGENTS.md and it runs what it reads there. A
command that has been renamed, or one that was documented but never built, is
therefore a real defect and not a typo — so it fails the build.
"""

import re
from pathlib import Path

import pytest

from talanton import cli

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "AGENTS.md",
    "README.md",
    "CLAUDE.md",
    ".claude/commands/hiring-cycle.md",
    ".claude/commands/draft-role.md",
    ".claude/commands/review-filter.md",
    "talanton.example.toml",
    "docs/example-cvs.md",
]

# Only a command being *invoked*: in a shell line, or in backticks. Prose like
# "talanton holds the rubric" is not a command reference.
INVOCATION = re.compile(
    r"(?:^|`|\$ |\n)\s*(?:uv run )?talanton\s+(?:--config\s+\S+\s+)?([a-z][a-z-]{2,})",
    re.MULTILINE,
)


def commands() -> set[str]:
    return set(cli.build_parser()._subparsers._group_actions[0].choices)


@pytest.mark.parametrize("document", DOCS)
def test_every_command_the_docs_tell_you_to_run_exists(document):
    path = ROOT / document
    if not path.exists():
        pytest.skip(f"{document} is not in this checkout")

    referenced = set(INVOCATION.findall(path.read_text(encoding="utf-8")))
    unknown = referenced - commands()
    assert not unknown, f"{document} tells you to run {sorted(unknown)}, which the CLI does not have"


def test_agents_md_covers_every_command():
    """A command an agent cannot discover may as well not exist."""
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    undocumented = {c for c in commands() if f"`{c}" not in text and f" {c} " not in text}
    assert not undocumented, f"AGENTS.md documents no way to reach {sorted(undocumented)}"


def test_the_runbook_is_reachable_from_the_readme():
    assert "AGENTS.md" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_first_run_walk_does_not_send_a_coding_agent_to_vertex():
    """The walk in AGENTS.md is what an agent follows literally. Pointing it at
    `assess` starts a second agent on Vertex to do the reading the agent
    reading the file can already do — which is what happened once."""
    walk = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    walk = walk[walk.index("## Run it by hand, the first time") :]
    walk = walk[: walk.index("\n---")]
    assert "talanton next" in walk and "talanton record" in walk
    assert "talanton assess" not in walk


def test_agents_md_says_which_path_a_coding_agent_is_on_before_listing_commands():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    routing = text.index("are you the model")
    assert routing < text.index("## Every command"), "the routing decision comes after the command list"
    assert "not for you" in text
