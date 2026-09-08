"""Mailbox passwords from Secret Manager, so access is an IAM decision.

The point is that someone without the grant is stopped by Google, not by
whether they happen to have a .env file.
"""

import pytest

from talanton import config, inbound, outbound, secrets


def test_a_bare_name_becomes_a_full_resource_path():
    assert secrets.resource_name("talanton-inbound", "acme") == (
        "projects/acme/secrets/talanton-inbound/versions/latest"
    )


def test_a_full_path_is_left_alone_but_gets_a_version():
    assert secrets.resource_name("projects/other/secrets/x", "acme") == (
        "projects/other/secrets/x/versions/latest"
    )


def test_an_explicit_version_is_respected():
    reference = "projects/other/secrets/x/versions/3"
    assert secrets.resource_name(reference, "acme") == reference


def test_a_bare_name_with_no_project_says_what_to_do():
    with pytest.raises(secrets.SecretError, match="needs a project"):
        secrets.resource_name("talanton-inbound", "")


def test_being_denied_says_it_is_the_access_control_working():
    """The message a colleague without the grant should see."""
    message = secrets._explain("projects/p/secrets/s/versions/latest", Exception("403 PermissionDenied"))
    assert "secretAccessor" in message
    assert "Do not ask anyone to send you the password" in message


def test_a_missing_secret_is_distinguished_from_a_denied_one():
    assert "no secret at" in secrets._explain("projects/p/secrets/s", Exception("404 NotFound"))


def test_missing_credentials_say_how_to_get_them():
    message = secrets._explain("projects/p/secrets/s", Exception("DefaultCredentialsError: nope"))
    assert "gcloud auth application-default login" in message


def test_the_environment_wins_over_the_secret(monkeypatch):
    """A local override and CI both keep working."""
    monkeypatch.setenv("TALANTON_INBOUND_PASSWORD", "abcd efgh ijkl mnop")
    assert secrets.password(("TALANTON_INBOUND_PASSWORD",), "should-not-be-read", "p") == ("abcdefghijklmnop")


def test_no_reference_and_no_environment_is_empty_not_an_error(monkeypatch):
    """An unconfigured mailbox is reported by the caller, not raised here."""
    monkeypatch.delenv("TALANTON_INBOUND_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    assert secrets.password(("TALANTON_INBOUND_PASSWORD",), "", "p") == ""


def test_a_secret_is_read_and_its_display_spaces_stripped(monkeypatch):
    """An app password pasted into a secret carries the spaces Google showed."""
    monkeypatch.delenv("TALANTON_INBOUND_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    monkeypatch.setattr(secrets, "read", lambda ref, project="": "abcdefghijklmnop")
    assert secrets.password(("TALANTON_INBOUND_PASSWORD",), "ref", "p") == "abcdefghijklmnop"


def test_the_inbound_mailbox_resolves_its_secret(configure, monkeypatch):
    monkeypatch.delenv("TALANTON_INBOUND_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    configure(
        inbound=config.Inbound(user="apply@example.com", password_secret="k-inbound"),
        screening=config.Screening(project="acme"),
    )
    monkeypatch.setattr(secrets, "read", lambda ref, project="": f"secret-for-{ref}-in-{project}")
    assert inbound.password() == "secret-for-k-inbound-in-acme"


def test_the_outbound_identity_resolves_its_own_separate_secret(configure, monkeypatch):
    """Two mailboxes, two secrets, two IAM grants."""
    monkeypatch.delenv("TALANTON_OUTBOUND_PASSWORD", raising=False)
    configure(
        outbound=config.Outbound(user="bot@example.com", password_secret="k-outbound"),
        screening=config.Screening(project="acme"),
    )
    monkeypatch.setattr(secrets, "read", lambda ref, project="": f"secret-for-{ref}")
    assert outbound.password() == "secret-for-k-outbound"


def test_a_dry_run_never_needs_the_secret(configure, monkeypatch, sent):
    """Reading a shortlist must not require credentials nobody has yet."""
    configure(
        outbound=config.Outbound(user="bot@example.com", password_secret="k-outbound", dry_run=True),
    )

    def explode(*args, **kwargs):
        raise AssertionError("a dry run read the secret")

    monkeypatch.setattr(secrets, "read", explode)
    monkeypatch.undo()
    outbound.send("you@example.com", "s", "b")


def test_the_config_carries_the_reference_not_the_secret():
    """A committed file names the secret; it never holds one."""
    parsed = config.parse({"mail": {"inbound": {"password_secret": "k-inbound"}}})
    assert parsed.inbound.password_secret == "k-inbound"
    assert parsed.inbound.password == ""


def test_sending_uses_the_secret_when_the_environment_has_no_password(configure, monkeypatch):
    """`talanton secret outbound` is the documented setup for a shared
    deployment. If `send` reads only the environment, that setup cannot send."""
    monkeypatch.delenv("TALANTON_OUTBOUND_PASSWORD", raising=False)
    configure(
        outbound=config.Outbound(
            user="bot@example.com",
            password_secret="k-outbound",
            operators=("you@example.com",),
            dry_run=False,
        ),
        screening=config.Screening(project="acme"),
    )
    # Before any patch below: undo() also drops the conftest stub on
    # outbound.send, which is the point — this test needs the real one.
    monkeypatch.undo()
    monkeypatch.setattr(secrets, "read", lambda ref, project="": "abcdefghijklmnop")

    logged_in: list[tuple[str, str]] = []

    class FakeSMTP:
        def __init__(self, server, port):
            self.server, self.port = server, port

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def login(self, user, secret):
            logged_in.append((user, secret))

        def send_message(self, msg):
            pass

    monkeypatch.setattr(outbound.smtplib, "SMTP_SSL", FakeSMTP)
    outbound.send("you@example.com", "s", "b")
    assert logged_in == [("bot@example.com", "abcdefghijklmnop")]


def test_check_does_not_claim_sending_will_fail_when_a_secret_is_configured(configure, monkeypatch, capsys):
    from talanton import cli

    monkeypatch.delenv("TALANTON_OUTBOUND_PASSWORD", raising=False)
    active = configure(
        outbound=config.Outbound(
            user="bot@example.com",
            password_secret="k-outbound",
            operators=("you@example.com",),
            dry_run=False,
        ),
        screening=config.Screening(project="acme"),
    )
    monkeypatch.setattr(secrets, "read", lambda ref, project="": "abcdefghijklmnop")
    # This test is about where the password comes from. Whether Google accepts
    # it is a different question, and a different test — one that must not open
    # a socket to gmail from a unit run.
    monkeypatch.setattr(outbound, "probe", lambda: "")
    assert cli._check_sending(active) is True
    assert "TALANTON_OUTBOUND_PASSWORD is unset" not in capsys.readouterr().out
