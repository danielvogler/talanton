"""The credential split, proved structurally rather than promised.

`inbound` holds credentials to a mailbox full of CVs. If any import path from
it reached the module that can send, a compromised or confused inbound stage
could reply to a candidate. So the import graph is walked here, and reaching
`outbound` or `smtplib` from `inbound` fails the build — including through an
intermediate module, which a grep for "mail.send" would not catch.
"""

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "talanton"
SENDING = {"smtplib", "talanton.outbound", "outbound"}
READING = {"imapclient", "talanton.inbound", "inbound"}


def imports_of(module: str) -> set[str]:
    """Every module `module` imports directly, by name."""
    source = (PACKAGE / f"{module}.py").read_text(encoding="utf-8")
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # from . import x  /  from .x import y
                found |= {a.name for a in node.names}
                if node.module:
                    found.add(node.module.split(".")[0])
            elif node.module:
                found.add(node.module.split(".")[0])
    return found


def reachable_from(start: str) -> set[str]:
    """Every module reachable from `start`, following local imports."""
    seen, queue = set(), [start]
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        if not (PACKAGE / f"{module}.py").exists():
            continue  # a third-party module; recorded, not descended into
        queue += [m for m in imports_of(module) if m not in seen]
    return seen


def test_the_inbound_stage_cannot_reach_anything_that_sends():
    """The whole point of the credential split."""
    reached = reachable_from("inbound")
    assert not (reached & SENDING), f"inbound can reach {sorted(reached & SENDING)}"


def test_the_outbound_stage_cannot_reach_the_mailbox():
    """The sending identity must not be able to read a CV."""
    reached = reachable_from("outbound")
    assert not (reached & READING), f"outbound can reach {sorted(reached & READING)}"


def test_the_walk_actually_follows_indirection():
    """Guard on the guard: a grep would miss a two-hop path, so prove the
    traversal is transitive and not just checking direct imports."""
    assert "config" in reachable_from("inbound")
    assert "locations" in reachable_from("inbound")  # via store, not directly
    assert "locations" not in imports_of("inbound")


def test_the_sending_module_is_the_only_one_importing_smtplib():
    senders = [p.stem for p in PACKAGE.glob("*.py") if "smtplib" in imports_of(p.stem)]
    assert senders == ["outbound"], f"smtplib is imported by {senders}"


def test_the_reading_module_is_the_only_one_importing_imapclient():
    readers = [p.stem for p in PACKAGE.glob("*.py") if "imapclient" in imports_of(p.stem)]
    assert readers == ["inbound"], f"imapclient is imported by {readers}"


@pytest.mark.parametrize("module", ["tools", "agent"])
def test_the_agent_side_never_touches_the_mailbox(module):
    """Only the fetch stage reads mail. An agent tool must not."""
    assert "imapclient" not in reachable_from(module)
