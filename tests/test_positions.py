"""The position file is the backbone, and the opening number is its handle."""

import shutil
from pathlib import Path

import pytest

from talanton import positions

EXAMPLE = Path(__file__).resolve().parents[1] / "example"


@pytest.fixture
def example(tmp_path):
    shutil.copytree(EXAMPLE / "openings", tmp_path / "openings", dirs_exist_ok=True)
    return positions.resolve("101")


def test_the_example_openings_load(example):
    assert example["id"] == "ai-engineer" and example["opening"] == 101
    assert example["knockouts"] and example["rubric"]


def test_an_opening_resolves_by_number_slug_or_role(example):
    """Whatever the operator types, as long as it is unambiguous."""
    for reference in ("101", "101-ai-engineer", "ai-engineer"):
        assert positions.resolve(reference)["opening"] == 101


def test_a_missing_opening_lists_the_ones_that_exist(example):
    with pytest.raises(FileNotFoundError, match="101-ai-engineer"):
        positions.resolve("999")


def test_an_ambiguous_reference_is_refused_rather_than_guessed(example, tmp_path):
    """Screening someone against the wrong posting is not worth saving keystrokes."""
    import yaml

    duplicate = {**example, "opening": 103}
    (tmp_path / "openings" / "103-ai-engineer.yaml").write_text(yaml.safe_dump(duplicate), encoding="utf-8")
    with pytest.raises(positions.AmbiguousOpeningError, match="Give the number"):
        positions.resolve("ai-engineer")


def test_the_slug_is_the_folder_name(example):
    assert positions.slug(example) == "101-ai-engineer"


def test_a_position_without_an_opening_number_is_refused(tmp_path):
    (tmp_path / "openings").mkdir(parents=True, exist_ok=True)
    (tmp_path / "openings" / "broken.yaml").write_text("id: broken\ntitle: Broken\n", encoding="utf-8")
    with pytest.raises(positions.PositionError, match="opening"):
        positions.load("broken")


def test_two_openings_can_share_a_title(example):
    """The whole reason numbers exist."""
    assert {p["opening"] for p in positions.every()} == {101, 102}


def test_knockouts_are_rendered_apart_from_scored_dimensions(example):
    text = positions.rubric_text(example)
    assert text.index("## Knockouts") < text.index("## Scored dimensions")
    assert "never traded off" in text


def test_the_rubric_carries_what_must_not_influence_the_score(example):
    assert "photograph" in positions.rubric_text(example).lower()


def test_the_board_ad_keeps_its_section_breaks(example):
    """A pasted ad with no blank lines is unreadable."""
    ad = positions.board_ad(example, "linkedin")
    assert "\n\nWhat you will do:" in ad
    assert "\n\nNice to have:" in ad


def test_the_ad_carries_the_apply_address_and_closing_date(example):
    ad = positions.board_ad(example, "linkedin")
    assert "apply@example.com" in ad and "2026-11-30" in ad


def test_the_second_opening_has_its_own_apply_address(example):
    """Applications sort themselves by the address they were sent to."""
    ad = positions.board_ad(positions.resolve("102"), "linkedin")
    assert "apply+102@example.com" in ad


def test_over_length_copy_is_flagged_not_truncated(example):
    ad = positions.board_ad({**example, "title": "A" * 150}, "jobs-ch")
    assert "LIMIT 100" in ad and "A" * 150 in ad


def test_board_setup_notes_are_included(example):
    assert "Easy Apply" in positions.board_ad(example, "linkedin")


def test_indeed_copy_is_generated(example):
    assert "indeed" in example["boards"]
    assert positions.board_ad(example, "indeed").startswith("=== indeed:")


def test_a_board_may_carry_its_own_title(example):
    with_title = {**example, "boards": {**example["boards"], "indeed": {"title": "AI Engineer (Python, LLMs)"}}}
    assert "TITLE: AI Engineer (Python, LLMs)" in positions.board_ad(with_title, "indeed")


def test_a_salary_range_is_rendered_readably(example):
    assert "CHF 120,000 – 150,000 per year" in positions.board_ad(example, "linkedin")


def test_every_board_gets_copy_in_one_go(example):
    output = positions.ads(example)
    for board in example["boards"]:
        assert f"=== {board}: paste this ===" in output
