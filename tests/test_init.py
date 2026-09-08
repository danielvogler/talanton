"""Scaffolding a hiring setup. Getting this shape wrong is how CVs end up in git."""

import pytest

from talanton import cli


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_writes_a_working_config(repo, capsys):
    assert cli.main(["init", "--company", "Acme"]) == 0
    assert (repo / "hiring" / "talanton.toml").exists()
    assert 'name = "Acme"' in (repo / "hiring" / "talanton.toml").read_text()


def test_init_makes_the_three_directories(repo):
    cli.main(["init"])
    for name in ("openings", "cvs", "assessments"):
        assert (repo / "hiring" / name).is_dir()


def test_init_gitignores_candidate_data_before_any_arrives(repo):
    """The whole point of doing this at setup rather than afterwards."""
    cli.main(["init"])
    ignored = (repo / ".gitignore").read_text()
    assert "hiring/cvs/" in ignored
    assert "hiring/assessments/" in ignored
    assert "hiring/.env" in ignored


def test_init_keeps_an_existing_gitignore(repo):
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    cli.main(["init"])
    ignored = (repo / ".gitignore").read_text()
    assert "__pycache__/" in ignored and "hiring/cvs/" in ignored


def test_init_never_overwrites_a_config(repo, capsys):
    cli.main(["init"])
    (repo / "hiring" / "talanton.toml").write_text("# mine\n", encoding="utf-8")
    cli.main(["init"])
    assert (repo / "hiring" / "talanton.toml").read_text() == "# mine\n"
    assert "left alone" in capsys.readouterr().out


def test_init_is_idempotent(repo):
    assert cli.main(["init"]) == 0
    assert cli.main(["init"]) == 0


def test_the_env_file_carries_no_secret(repo):
    cli.main(["init"])
    env = (repo / "hiring" / ".env").read_text()
    assert "TALANTON_INBOUND_PASSWORD=" in env
    assert env.strip().endswith("=")  # placeholders only


def test_check_passes_immediately_after_init(repo, capsys):
    """Setup that does not validate is setup that will be abandoned."""
    cli.main(["init"])
    assert cli.main(["--config", "hiring/talanton.toml", "check"]) == 0


def test_init_can_go_somewhere_else(repo):
    cli.main(["init", "--dir", "recruiting"])
    assert (repo / "recruiting" / "talanton.toml").exists()
    assert "recruiting/cvs/" in (repo / ".gitignore").read_text()
