"""Finding the configuration, and refusing to guess when it is not found.

The config sat in one directory and was found only by a command run in that
exact directory. In a repository that does more than hiring it lives several
levels down, while everything else resolves against the repository root — so
every shell needed an export, and a forgotten one did not fail. It ran against
default locations instead, which is an empty pool that looks like a quiet week.
"""

import pytest

from talanton import config


def test_a_config_in_the_working_directory_is_found(tmp_path, monkeypatch):
    (tmp_path / "talanton.toml").write_text("[company]\nname='X'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert config.find() == tmp_path / "talanton.toml"


def test_a_config_above_the_working_directory_is_found(tmp_path, monkeypatch):
    """The ordinary case in a repository that is not only a hiring repository."""
    (tmp_path / "talanton.toml").write_text("[company]\nname='X'\n", encoding="utf-8")
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert config.find() == tmp_path / "talanton.toml"


def test_the_nearest_one_wins(tmp_path, monkeypatch):
    """Two configs means the one you are standing in, not the one further up."""
    (tmp_path / "talanton.toml").write_text("[company]\nname='outer'\n", encoding="utf-8")
    inner = tmp_path / "hiring"
    inner.mkdir()
    (inner / "talanton.toml").write_text("[company]\nname='inner'\n", encoding="utf-8")
    monkeypatch.chdir(inner)
    assert config.find() == inner / "talanton.toml"


def test_the_environment_variable_still_wins(tmp_path, monkeypatch):
    (tmp_path / "talanton.toml").write_text("[company]\nname='X'\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(config.CONFIG_ENV, "/somewhere/else.toml")
    assert str(config.find()) == "/somewhere/else.toml"


def test_no_config_anywhere_is_still_no_config(tmp_path, monkeypatch):
    """Running with defaults is a supported way to try the tool out."""
    monkeypatch.chdir(tmp_path)
    assert config.find(stop=tmp_path) is None


def test_the_walk_stops_rather_than_leaving_the_repository(tmp_path, monkeypatch):
    """A config belonging to a different project is worse than none: it would
    point this run at somebody else's candidates."""
    (tmp_path / "talanton.toml").write_text("[company]\nname='other project'\n", encoding="utf-8")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    monkeypatch.chdir(project)
    assert config.find() is None
