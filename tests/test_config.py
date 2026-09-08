"""Settings come from a file. Secrets never do."""

import re

import pytest

from talanton import config


def test_an_empty_config_still_loads_with_safe_defaults():
    parsed = config.parse({})
    assert parsed.outbound.dry_run is True
    assert parsed.outbound.operators == ()


def test_dry_run_defaults_to_on():
    """Sending for real is a deliberate act, made in one place."""
    assert config.Outbound().dry_run is True


def test_a_password_in_the_config_file_is_ignored(monkeypatch):
    """A committed file must never be able to carry a secret."""
    for name in ("EMAIL_PASSWORD", "TALANTON_INBOUND_PASSWORD", "TALANTON_OUTBOUND_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    parsed = config.parse(
        {
            "mail": {
                "inbound": {"user": "a@example.com", "password": "hunter2"},
                "outbound": {"user": "b@example.com", "password": "hunter2"},
            }
        }
    )
    assert parsed.inbound.password == "" and parsed.outbound.password == ""


def test_the_two_mail_identities_are_separate(monkeypatch):
    """The sending account must not be the one holding the CVs."""
    monkeypatch.delenv("EMAIL_USER", raising=False)
    parsed = config.parse(
        {"mail": {"inbound": {"user": "apply@example.com"}, "outbound": {"user": "bot@example.com"}}}
    )
    assert parsed.inbound.user != parsed.outbound.user


def test_a_reply_defaults_back_to_the_apply_mailbox(monkeypatch):
    """Otherwise a reply to the shortlist lands in an account nobody reads."""
    monkeypatch.delenv("EMAIL_USER", raising=False)
    parsed = config.parse({"mail": {"inbound": {"user": "apply@example.com"}}})
    assert parsed.outbound.reply_to == "apply@example.com"


def test_an_explicit_reply_to_wins(monkeypatch):
    monkeypatch.delenv("EMAIL_USER", raising=False)
    parsed = config.parse(
        {"mail": {"inbound": {"user": "apply@example.com"}, "outbound": {"reply_to": "people@example.com"}}}
    )
    assert parsed.outbound.reply_to == "people@example.com"


def test_the_password_comes_from_the_environment(monkeypatch):
    monkeypatch.setenv("TALANTON_INBOUND_PASSWORD", "in-secret")
    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "out-secret")
    parsed = config.parse({})
    assert parsed.inbound.password == "in-secret"
    assert parsed.outbound.password == "out-secret"


def test_addresses_are_lowercased_so_matching_is_exact():
    parsed = config.parse({"mail": {"outbound": {"operators": ["You@Example.COM "]}}})
    assert parsed.outbound.operators == ("you@example.com",)


def test_a_malformed_section_says_which_one():
    with pytest.raises(config.ConfigError, match=re.escape("mail.outbound.operators")):
        config.parse({"mail": {"outbound": {"operators": "you@example.com"}}})


def test_an_explicitly_named_missing_file_is_an_error(tmp_path):
    with pytest.raises(config.ConfigError, match="no config file"):
        config.load(tmp_path / "nope.toml")


def test_locations_default_to_local_beside_the_config():
    parsed = config.parse({})
    assert parsed.cvs.backend == "local" and parsed.cvs.path == "cvs"
    assert parsed.assessments.backend == "local" and parsed.assessments.path == "assessments"


def test_the_two_locations_are_configured_independently():
    parsed = config.parse(
        {"storage": {"cvs": {"backend": "gdrive", "folder": "hr/recruiting"}, "assessments": {"path": "out"}}}
    )
    assert parsed.cvs.backend == "gdrive" and parsed.cvs.folder == "hr/recruiting"
    assert parsed.assessments.backend == "local" and parsed.assessments.path == "out"


def test_a_malformed_storage_section_says_which_one():
    with pytest.raises(config.ConfigError, match=re.escape("storage.cvs")):
        config.parse({"storage": {"cvs": "hr/recruiting"}})


def test_a_config_file_round_trips(tmp_path, monkeypatch):
    monkeypatch.delenv("EMAIL_USER", raising=False)
    (tmp_path / "talanton.toml").write_text(
        '[company]\nname = "Acme"\n[store]\npath = "./records"\n[mail.inbound]\nuser = "apply@acme.test"\n',
        encoding="utf-8",
    )
    parsed = config.load(tmp_path / "talanton.toml")
    assert parsed.company.name == "Acme"
    assert parsed.inbound.user == "apply@acme.test"
    assert parsed.store == (tmp_path / "records").resolve()


def test_the_config_is_frozen():
    """Build a new one; never mutate the active one."""
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        config.Config().store = "/somewhere/else"


def test_a_company_installs_its_own_config():
    """The extension point the company repository uses."""
    original = config.current()
    config.use(config.parse({"company": {"name": "Acme"}}))
    assert config.current().company.name == "Acme"
    config.use(original)


def test_an_app_password_pasted_with_its_display_spaces_still_works(monkeypatch):
    """Google shows them as four groups of four. People paste what they see,
    and the spaces are display only — leaving them in fails the login with an
    error that says nothing about spaces."""
    monkeypatch.setenv("TALANTON_INBOUND_PASSWORD", "abcd efgh ijkl mnop")
    assert config.parse({}).inbound.password == "abcdefghijklmnop"


def test_surrounding_whitespace_goes_too(monkeypatch):
    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "  wxyz 1234 5678 90ab \n")
    assert config.parse({}).outbound.password == "wxyz1234567890ab"


def test_a_password_with_no_spaces_is_untouched(monkeypatch):
    monkeypatch.setenv("TALANTON_INBOUND_PASSWORD", "abcdefghijklmnop")
    assert config.parse({}).inbound.password == "abcdefghijklmnop"


def test_the_legacy_variable_name_still_works(monkeypatch):
    """The EMAIL_* names match email-assistance-agent, so one .env serves both."""
    monkeypatch.delenv("TALANTON_INBOUND_PASSWORD", raising=False)
    monkeypatch.setenv("EMAIL_PASSWORD", "abcd efgh ijkl mnop")
    assert config.parse({}).inbound.password == "abcdefghijklmnop"


def test_dotenv_reads_a_quoted_value_with_spaces(tmp_path, monkeypatch):
    monkeypatch.delenv("TALANTON_INBOUND_PASSWORD", raising=False)
    env = tmp_path / ".env"
    env.write_text('TALANTON_INBOUND_PASSWORD="abcd efgh ijkl mnop"\n', encoding="utf-8")
    config.load_dotenv(env)
    assert config.parse({}).inbound.password == "abcdefghijklmnop"


def test_dotenv_never_overwrites_the_real_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("TALANTON_INBOUND_PASSWORD", "from-the-shell")
    env = tmp_path / ".env"
    env.write_text("TALANTON_INBOUND_PASSWORD=from-the-file\n", encoding="utf-8")
    config.load_dotenv(env)
    assert config.parse({}).inbound.password == "from-the-shell"


def test_vertex_routing_is_switched_on_with_the_project(monkeypatch):
    """Without this, a Gemini id routes to the Developer API and asks for an
    API key, ignoring the project entirely."""
    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)
    import os

    config.apply_environment(config.parse({"screening": {"project": "p", "location": "global"}}))
    assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "TRUE"
    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)


def test_no_project_means_no_vertex_flag(monkeypatch):
    """Someone with no project configured is not using Vertex."""
    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_GENAI_USE_VERTEXAI"):
        monkeypatch.delenv(name, raising=False)
    import os

    config.apply_environment(config.parse({}))
    assert "GOOGLE_GENAI_USE_VERTEXAI" not in os.environ
