"""The outbound guardrail. It is the only place anything leaves."""

from typing import ClassVar

import pytest

from talanton import config, outbound


def test_the_domain_allowlist_blocks_a_stranger(configure):
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=("example.com",)))
    with pytest.raises(outbound.NotAllowedError):
        outbound.check("someone@elsewhere.test")


def test_an_allowed_domain_passes(configure):
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=("example.com",)))
    outbound.check("hiring@example.com")


def test_an_empty_allowlist_is_unrestricted(configure):
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=()))
    outbound.check("anyone@anywhere.test")


def test_a_lookalike_domain_does_not_pass(configure):
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=("example.com",)))
    with pytest.raises(outbound.NotAllowedError):
        outbound.check("someone@example.com.evil.test")


def test_sending_outside_the_allowlist_raises(configure, monkeypatch):
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=("example.com",)))
    monkeypatch.undo()
    with pytest.raises(outbound.NotAllowedError):
        outbound.send("stranger@elsewhere.test", "s", "b")


def test_the_plain_text_part_is_preferred_over_html():
    import email
    from email.message import EmailMessage

    from talanton import inbound

    msg = EmailMessage()
    msg.set_content("the plain version")
    msg.add_alternative("<p>the html version</p>", subtype="html")
    assert inbound.body(email.message_from_bytes(msg.as_bytes())).strip() == "the plain version"


def test_check_catches_sending_that_would_fail(configure, monkeypatch, capsys):
    """Finding this at send time means finding it after paying to assess."""
    from talanton import cli

    monkeypatch.delenv("TALANTON_OUTBOUND_PASSWORD", raising=False)
    active = configure(
        outbound=config.Outbound(user="bot@example.com", operators=("you@example.com",), dry_run=False)
    )
    assert cli._check_sending(active) is False
    assert "TALANTON_OUTBOUND_PASSWORD" in capsys.readouterr().out


def test_check_catches_an_allowlist_that_blocks_the_operator(configure, monkeypatch, capsys):
    """The shortlist would be refused by its own guardrail."""
    from talanton import cli

    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "x")
    active = configure(
        outbound=config.Outbound(
            user="bot@example.com",
            operators=("you@elsewhere.test",),
            allow_domains=("example.com",),
            dry_run=False,
        )
    )
    assert cli._check_sending(active) is False
    assert "blocks the operator" in capsys.readouterr().out


def test_dry_run_needs_no_password(configure, capsys):
    from talanton import cli

    active = configure(outbound=config.Outbound(user="bot@example.com", dry_run=True))
    assert cli._check_sending(active) is True


def test_an_empty_dry_run_variable_leaves_dry_run_on(monkeypatch):
    """`.env.example` writes empty placeholders for every other secret, so
    TALANTON_DRY_RUN= is a plausible thing to end up with. It must not be the
    thing that starts sending real mail."""
    from talanton import config

    monkeypatch.setenv("TALANTON_DRY_RUN", "")
    assert config.parse({"mail": {"outbound": {"dry_run": True}}}).outbound.dry_run is True


def test_whitespace_only_dry_run_also_leaves_it_on(monkeypatch):
    from talanton import config

    monkeypatch.setenv("TALANTON_DRY_RUN", "   ")
    assert config.parse({"mail": {"outbound": {"dry_run": True}}}).outbound.dry_run is True


def test_dry_run_can_still_be_turned_off_deliberately(monkeypatch):
    from talanton import config

    monkeypatch.setenv("TALANTON_DRY_RUN", "0")
    assert config.parse({"mail": {"outbound": {"dry_run": True}}}).outbound.dry_run is False


def test_check_warns_when_sending_is_live_with_no_allowlist(configure, monkeypatch, capsys):
    """An empty allow_domains permits every recipient on earth, and nothing
    said so."""
    from talanton import cli, config

    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "x")
    active = configure(
        outbound=config.Outbound(
            user="bot@example.com", operators=("you@example.com",), allow_domains=(), dry_run=False
        )
    )
    cli._check_sending(active)
    assert "allow_domains" in capsys.readouterr().out


class FakeSMTP:
    """Stands in for smtplib.SMTP_SSL. Records the login it was given."""

    logged_in: ClassVar[list[tuple[str, str]]] = []
    messages: ClassVar[list] = []
    rejects: ClassVar[bool] = False

    def __init__(self, server, port):
        self.server, self.port = server, port

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, user, password):
        import smtplib

        if type(self).rejects:
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted.")
        type(self).logged_in.append((user, password))

    def send_message(self, msg):
        type(self).messages.append(msg)

    def quit(self):
        pass


@pytest.fixture
def smtp(monkeypatch):
    """A fake SMTP server, and the real `outbound.send` restored over it."""
    import smtplib

    FakeSMTP.logged_in, FakeSMTP.messages, FakeSMTP.rejects = [], [], False
    monkeypatch.undo()
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("TALANTON_OUTBOUND_PASSWORD", "app-password")
    return FakeSMTP


def test_smtp_logs_in_as_the_account_not_the_alias(configure, smtp):
    """An alias cannot authenticate. Google accepts the account the alias
    belongs to, so the address a reader sees and the address that logs in are
    two different settings."""
    configure(
        outbound=config.Outbound(
            user="recruiting@example.com",
            login_user="bot@example.com",
            allow_domains=("example.com",),
            dry_run=False,
        )
    )
    outbound.send("you@example.com", "subject", "body")

    assert smtp.logged_in == [("bot@example.com", "app-password")]
    assert smtp.messages[0]["From"] == "recruiting@example.com"


def test_the_login_falls_back_to_the_from_address(configure, smtp):
    """One account and no alias is the ordinary case, and stays one setting."""
    configure(outbound=config.Outbound(user="bot@example.com", allow_domains=("example.com",), dry_run=False))
    outbound.send("you@example.com", "subject", "body")

    assert smtp.logged_in == [("bot@example.com", "app-password")]


def test_a_login_google_refuses_is_reported_by_check(configure, smtp, capsys):
    """`check` reported ok because the secret could be read, which only proves
    IAM works. Whether Google accepts the value is a different question, and it
    is the one that failed a whole run."""
    from talanton import cli

    smtp.rejects = True
    active = configure(
        outbound=config.Outbound(
            user="bot@example.com",
            operators=("you@example.com",),
            allow_domains=("example.com",),
            dry_run=False,
        )
    )
    assert cli._check_sending(active) is False
    assert "not accepted" in capsys.readouterr().out.lower()


def test_a_login_google_accepts_passes_check(configure, smtp, capsys):
    from talanton import cli

    active = configure(
        outbound=config.Outbound(
            user="bot@example.com",
            operators=("you@example.com",),
            allow_domains=("example.com",),
            dry_run=False,
        )
    )
    assert cli._check_sending(active) is True
    assert smtp.logged_in, "check did not actually attempt a login"


def test_the_probe_sends_nothing(configure, smtp):
    """Proving the login works must not mail anybody."""
    configure(outbound=config.Outbound(user="bot@example.com", dry_run=False))
    outbound.probe()
    assert smtp.messages == []


def test_login_user_is_read_from_the_config_file(tmp_path, monkeypatch):
    from talanton import config as config_module

    path = tmp_path / "talanton.toml"
    path.write_text(
        '[mail.outbound]\nuser = "recruiting@example.com"\nlogin_user = "bot@example.com"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("TALANTON_CONFIG", str(path))
    assert config_module.load(path).outbound.login_user == "bot@example.com"
