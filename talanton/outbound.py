"""Sending, from an identity that cannot read the apply mailbox.

A separate account from the inbox, deliberately. This one sends the shortlist
and nothing else, so it needs no IMAP access — and having none means that if it
were ever misused, it could not read a single CV.

`send` is the only place anything leaves this system, so the recipient is
checked against the allowlist before anything else happens.
"""

import logging
import smtplib
from email.message import EmailMessage

from . import secrets
from .config import current


class NotAllowedError(RuntimeError):
    """Raised instead of sending to a recipient outside the allowlist."""


class SendError(RuntimeError):
    """Raised when a message could not be delivered. Never contains the password.

    One type for every way SMTP can refuse, so a caller inside an agent tool can
    answer with something the process can act on rather than letting a traceback
    become text in a function response.
    """


def check(to: str) -> None:
    """Raises NotAllowedError if this recipient is outside the allowlist.

    Args:
        to: The recipient address.

    Raises:
        NotAllowedError: If the domain is not in the configured allow list.
    """
    allowed = current().outbound.allow_domains
    domain = to.rsplit("@", 1)[-1].lower()
    if allowed and domain not in allowed:
        raise NotAllowedError(f"{to} is outside the allowed domains ({', '.join(allowed)})")


def login_identity() -> str:
    """The address SMTP authenticates as.

    Not always the address in `From`. `recruiting@` is commonly an alias on a
    `bot@` account, and an alias cannot authenticate: Google refuses it with
    535, the same answer it gives a wrong password, so it reads as a bad app
    password and sends you to regenerate one that was never the problem.
    """
    config = current().outbound
    return config.login_user or config.user


def password() -> str:
    """The sending password: the config, then the environment, then Secret
    Manager. Resolved at send time, so a dry run needs no credentials."""
    active = current()
    return active.outbound.password or secrets.password(
        ("TALANTON_OUTBOUND_PASSWORD",),
        active.outbound.password_secret,
        active.screening.project,
    )


def send(to: str, subject: str, body: str) -> None:
    """Sends one message. Checks the recipient allowlist first.

    Args:
        to: Recipient address.
        subject: Subject line.
        body: Plain-text body.

    Raises:
        NotAllowedError: If the recipient is outside the allowlist.
        ValueError: If the outbound identity is not configured.
        SecretError: If the password is in Secret Manager and you cannot read it.
        SendError: If the server refused the login or the message.
    """
    check(to)
    config = current().outbound

    msg = EmailMessage()
    msg["To"], msg["From"], msg["Subject"] = to, config.user, subject
    if config.reply_to:
        # A reply belongs in the apply mailbox, not in an unread bot account.
        msg["Reply-To"] = config.reply_to
    msg.set_content(body)

    if config.dry_run:
        logging.info(
            "DRY RUN, not sending:\n--- to %s (reply-to %s)\n%s\n\n%s", to, config.reply_to, subject, body
        )
        return

    # Resolved here rather than read off the config, so a password held in
    # Secret Manager — the setup for anything with more than one operator —
    # actually reaches the login. A dry run has already returned above and
    # never asks for it.
    secret = password()
    if not config.user or not secret:
        raise ValueError(
            "sending needs mail.outbound.user, and a password from $TALANTON_OUTBOUND_PASSWORD "
            "or mail.outbound.password_secret, or dry_run left on"
        )

    try:
        with smtplib.SMTP_SSL(config.smtp_server, config.smtp_port) as smtp:
            smtp.login(login_identity(), secret)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise SendError(_refused(exc)) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise SendError(
            f"could not send to {to} through {config.smtp_server}:{config.smtp_port} — "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    logging.info("Sent %r to %s", subject, to)


def probe() -> str:
    """Logs in and hangs up, sending nothing. Returns "" if Google accepted it.

    `check` used to report the sending password `ok` on the strength of having
    read it out of Secret Manager. That proves the IAM grant works and says
    nothing about whether the value is a password Google accepts — which is the
    one thing that matters, and the thing that failed a whole run after the
    assessments had been paid for.

    Returns:
        str: An empty string on success, or why the login was refused.
    """
    config = current().outbound
    secret = password()
    if not config.user or not secret:
        return "no sending identity or no password"

    try:
        with smtplib.SMTP_SSL(config.smtp_server, config.smtp_port) as smtp:
            smtp.login(login_identity(), secret)
    except smtplib.SMTPAuthenticationError as exc:
        return _refused(exc)
    except (smtplib.SMTPException, OSError) as exc:
        return f"could not reach {config.smtp_server}:{config.smtp_port} — {type(exc).__name__}: {exc}"
    return ""


def _refused(exc: smtplib.SMTPAuthenticationError) -> str:
    """Why a login was refused, and the two things that actually cause it.

    Never contains the password.
    """
    raw = exc.smtp_error
    detail = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or exc.smtp_code)
    identity = login_identity()
    alias = (
        f"\n      {identity} is the From address. If it is an alias, mail.outbound.login_user "
        "has to name the account it belongs to — an alias cannot authenticate."
        if not current().outbound.login_user
        else ""
    )
    return (
        f"{identity} was refused by {current().outbound.smtp_server}: {detail}"
        f"{alias}\n      Otherwise the app password is wrong, revoked, or was minted on another "
        "account. Regenerate it and store it with: talanton secret outbound"
    )
