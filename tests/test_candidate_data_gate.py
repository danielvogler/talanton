"""The hook that refuses to commit a real person.

`.gitignore` keeps the configured locations out of this repository, and
gitleaks finds credentials. Neither catches a CV saved somewhere new or a real
address pasted into a test, and both have happened.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import refuse_candidate_data as gate


def test_a_document_outside_the_example_set_is_refused():
    """What a stray CV looks like from the outside."""
    assert gate.document_hits([Path("notes/cv.pdf")])


def test_the_invented_examples_are_allowed():
    """They are the whole point of example/cvs/, and are script-generated."""
    assert not gate.document_hits([Path("example/cvs/101-software-engineer/rossi-marco.txt")])
    assert not gate.document_hits([Path("example/cvs/101-software-engineer/keller-nadia.pdf")])


def test_a_readme_is_not_mistaken_for_a_cv():
    assert not gate.document_hits([Path("README.md"), Path("talanton/store.py")])


def test_a_real_looking_address_is_refused(tmp_path):
    # Assembled rather than written out: a literal here would be a real-looking
    # address in a tracked file, which is the thing under test. The hook
    # catching its own fixture is the hook working.
    address = "anna.mueller@" + "gmail" + ".com"
    source = tmp_path / "test_thing.py"
    source.write_text(f'SENDER = "{address}"\n', encoding="utf-8")
    assert gate.address_hits([source])


def test_reserved_placeholder_addresses_are_allowed(tmp_path):
    """RFC 2606 reserves these for exactly this purpose."""
    source = tmp_path / "test_thing.py"
    source.write_text(
        'A = "apply@example.com"\nB = "you@elsewhere.test"\nC = "talanton@your-project.iam.gserviceaccount.com"\n',
        encoding="utf-8",
    )
    assert gate.address_hits([source]) == []


def test_the_whole_repository_passes_its_own_gate():
    """A gate that fails on the repository it guards gets switched off."""
    root = Path(__file__).resolve().parents[1]
    tracked = [p for p in root.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts]
    relative = [p.relative_to(root) for p in tracked]
    assert gate.document_hits(relative) == []
