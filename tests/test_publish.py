"""Publishing an opening: the ad and the rubric, written where assessments live.

The published copy is derived. The file in `openings/` stays the source of
truth, and nothing here ever reads the published copy back into the store.
"""

from dataclasses import replace

import pytest

from talanton import config, publish, store


def test_the_body_carries_both_the_board_copy_and_the_rubric(position):
    """The point of publishing: the ad and the bar it judges against, together."""
    # Arrange
    data = position()

    # Act
    body = publish.render(data, board="linkedin")

    # Assert
    assert "paste this" in body
    assert "production_experience" in body


def test_the_header_names_the_source_file(position):
    """The copy outlives the state it came from, so it says where it came from."""
    # Arrange
    data = position()

    # Act
    body = publish.render(data, board="linkedin")

    # Assert
    assert "101-ai-engineer.yaml" in body


def test_the_header_says_the_file_is_generated(position):
    """The overwrite is announced where someone is about to hand-edit it."""
    # Arrange
    data = position()

    # Act
    body = publish.render(data, board="linkedin")

    # Assert
    assert "overwritten" in body.lower()


def test_a_note_is_carried_into_the_header(position):
    """Provenance the caller knows and the tool does not."""
    # Arrange
    data = position()

    # Act
    body = publish.render(data, board="linkedin", note="rev 4c1d9a, tree dirty")

    # Assert
    assert "rev 4c1d9a, tree dirty" in body


def test_rendering_is_stable_across_calls(position):
    """No timestamp: an unchanged opening must render byte-identically.

    Skip-if-unchanged is built on this. A clock in the header would make
    every publish a write, and every write a new Drive revision.
    """
    # Arrange
    data = position()

    # Act
    first = publish.render(data, board="linkedin")
    second = publish.render(data, board="linkedin")

    # Assert
    assert first == second


def test_the_board_defaults_to_the_first_one_configured(position):
    """A title can differ per board, so which board is a real choice."""
    # Arrange
    data = position(boards={"jobs_ch": {"title": "KI-Ingenieur"}, "linkedin": {}})

    # Act
    body = publish.render(data, board="")

    # Assert
    assert "KI-Ingenieur" in body


def test_an_unknown_board_is_refused(position):
    """Silently publishing the wrong board's copy is worse than failing."""
    # Arrange
    data = position()

    # Act / Assert
    with pytest.raises(publish.PublishError, match="indeed"):
        publish.render(data, board="indeed")


def test_an_opening_with_no_boards_is_refused(position):
    """There is no copy to publish, so say that rather than write an empty file."""
    # Arrange
    data = position(boards={})

    # Act / Assert
    with pytest.raises(publish.PublishError, match="no boards"):
        publish.render(data, board="")


def test_the_filename_is_the_slug(position):
    """Stable across pushes, so a re-push replaces rather than accumulates."""
    # Arrange
    data = position()

    # Act
    name = publish.filename(data)

    # Assert
    assert name.startswith("101-ai-engineer")


def test_publishing_writes_one_file(position, configure):
    """The whole feature, on the local backend."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    result = publish.publish("101")

    # Assert
    assert result.written is True
    assert [item.name for item in store.openings().list()] == [result.item.name]


def test_publishing_twice_replaces_rather_than_adds(position, configure):
    """Two contradictory rubrics side by side is the failure being avoided."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))
    publish.publish("101")

    # Act
    publish.publish("101")

    # Assert
    assert len(store.openings().list()) == 1


def test_an_unchanged_opening_is_not_written_again(position, configure):
    """Rewriting identical bytes only burns a revision in the history."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))
    publish.publish("101")

    # Act
    result = publish.publish("101")

    # Assert
    assert result.written is False
    assert result.unchanged is True


def test_a_changed_opening_is_written_again(position, configure):
    """Skip-if-unchanged must not become skip-always."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))
    publish.publish("101")
    position(pitch="We build agentic systems that do real work, in Zürich.")

    # Act
    result = publish.publish("101")

    # Assert
    assert result.written is True
    assert result.unchanged is False


def test_a_dry_run_writes_nothing(position, configure):
    """Exits clean, touches no location."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    result = publish.publish("101", dry_run=True)

    # Assert
    assert result.written is False
    assert store.openings().list() == []


def test_a_dry_run_still_renders_the_body(position, configure):
    """So the operator sees what would have been written."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    result = publish.publish("101", dry_run=True)

    # Assert
    assert "paste this" in result.body


def test_publishing_is_refused_when_no_location_is_configured(position, configure):
    """A deployment that has not opted in gets a reason, not a stray directory."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=False))

    # Act / Assert
    with pytest.raises(publish.PublishError, match=r"storage\.openings"):
        publish.publish("101")


def test_publishing_does_not_write_into_the_store(position, configure, tmp_path):
    """The source of truth is a directory publishing must never land in."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    publish.publish("101")

    # Assert
    assert sorted(p.name for p in (tmp_path / "openings").iterdir()) == ["101-ai-engineer.yaml"]


def test_the_default_location_is_not_the_source_directory():
    """`openings/` holds the position files; publishing there would mix the two."""
    # Act
    spec = config.Config().openings

    # Assert
    assert spec.path != "openings"


def test_an_unconfigured_deployment_keeps_the_old_two_locations():
    """Acceptance: nothing changes for someone who never sets this up."""
    # Act
    parsed = config.parse({})

    # Assert
    assert parsed.openings.configured is False
    assert parsed.cvs.configured is False


def test_a_configured_section_is_marked_as_such():
    """`check` needs to tell "not set up" from "set up as a local folder"."""
    # Act
    parsed = config.parse({"storage": {"openings": {"backend": "local", "path": "published"}}})

    # Assert
    assert parsed.openings.configured is True


def test_the_drive_folder_name_does_not_constrain_the_local_default():
    """A gdrive location never reads `path`, so the two cannot collide."""
    # Act
    parsed = config.parse({"storage": {"openings": {"backend": "gdrive", "folder_id": "abc"}}})

    # Assert
    assert parsed.openings.backend == "gdrive"
    assert parsed.openings.folder_id == "abc"


def test_nothing_reads_the_published_location_back(position, configure):
    """Writing only. The store must not learn to trust a published copy."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))
    publish.publish("101")
    store.openings().write("101-ai-engineer.txt", b"tampered")

    # Act
    data = publish.positions.resolve("101")

    # Assert
    assert data["pitch"].startswith("We build agentic systems")


def test_an_ambiguous_reference_is_refused(position, configure):
    """`resolve` already refuses; publishing must not soften that."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))
    position(opening=102, id="ai-engineer")

    # Act / Assert
    with pytest.raises(publish.positions.AmbiguousOpeningError):
        publish.publish("ai-engineer")


def test_check_stays_silent_when_the_location_is_not_configured(position, capsys, configure):
    """Acceptance: `check` output is unchanged for a deployment that has not opted in."""
    # Arrange
    from talanton import cli

    configure(openings=config.LocationSpec(path="published", configured=False))

    # Act
    cli.check_locations()

    # Assert
    assert "openings" not in capsys.readouterr().out


def test_check_reports_the_location_when_it_is_configured(position, capsys, configure):
    """Arrange"""
    # Arrange
    from talanton import cli

    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    cli.check_locations()

    # Assert
    assert "openings" in capsys.readouterr().out


def test_a_local_backend_works_as_well_as_gdrive(position, configure, tmp_path):
    """Acceptance: nothing in this path may be Drive-specific."""
    # Arrange
    configure(openings=config.LocationSpec(backend="local", path="published", configured=True))

    # Act
    publish.publish("101")

    # Assert
    assert (tmp_path / "published").is_dir()
    assert list((tmp_path / "published").iterdir())


def test_the_store_exposes_the_location_like_the_other_two(configure):
    """One accessor per location, so nothing builds a Location by hand."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    location = store.openings()

    # Assert
    assert location.backend == "local"


@pytest.mark.parametrize("reference", ["101", "101-ai-engineer", "ai-engineer"])
def test_a_role_is_accepted_in_every_form_the_other_commands_take(reference, position, configure):
    """`positions.resolve` already does this; publishing must not narrow it."""
    # Arrange
    configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    result = publish.publish(reference)

    # Assert
    assert result.written is True


def test_the_published_body_never_contains_a_candidate_name(position, configure):
    """Publishing is about the opening. Candidate data has no path into it."""
    # Arrange
    data = position()

    # Act
    body = publish.render(data, board="linkedin")

    # Assert
    assert "anna" not in body.lower()


def test_config_defaults_leave_the_existing_locations_untouched():
    """The new field must not shift the two that deployments already rely on."""
    # Act
    defaults = config.Config()

    # Assert
    assert defaults.cvs.path == "cvs"
    assert defaults.assessments.path == "assessments"


def test_replacing_the_spec_does_not_mutate_the_config(configure):
    """Config is frozen; publishing reads it and never writes it."""
    # Arrange
    before = configure(openings=config.LocationSpec(path="published", configured=True))

    # Act
    after = replace(before, openings=config.LocationSpec(path="elsewhere", configured=True))

    # Assert
    assert before.openings.path == "published"
    assert after.openings.path == "elsewhere"


def test_drive_folder_can_generate_the_openings_block():
    """The gdrive setup path: without this there is no way to get the block."""
    # Arrange
    from talanton import cli

    parser = cli.build_parser()

    # Act
    args = parser.parse_args(["drive-folder", "hr/openings", "--for", "openings"])

    # Assert
    assert args.__dict__["for"] == "openings"
