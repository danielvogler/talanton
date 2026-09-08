"""The apply mailbox, read-only.

THIS MODULE CANNOT SEND. It opens IMAP and nothing else: it does not import
`smtplib`, and it does not import `talanton.outbound`. That is not a promise
in a docstring — `tests/test_isolation.py` walks the import graph from here and
fails if any path reaches either.

It matters because this is the one component that reads text written by
strangers in bulk. Whatever a candidate puts in an email, there is no code
path from here to a reply.
"""

import email
import email.utils
import logging
from typing import Any

from imapclient import IMAPClient

from . import documents, positions, secrets, store
from .config import current

DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md")
UNKNOWN_SENDER = "unknown"
# Applications that match no opening. A person sorts these; nothing guesses.
UNSORTED = "unsorted"


def password() -> str:
    """The apply mailbox password: the config, then the environment, then
    Secret Manager. Resolved here rather than at load time, so merely reading
    the config never needs credentials."""
    active = current()
    return active.inbound.password or secrets.password(
        ("TALANTON_INBOUND_PASSWORD", "EMAIL_PASSWORD"),
        active.inbound.password_secret,
        active.screening.project,
    )


def client() -> IMAPClient:
    """Authenticates and returns the IMAP client.

    Raises:
        ValueError: If the inbound mailbox is not configured.
        SecretError: If the password is in Secret Manager and you cannot read it.
    """
    config = current().inbound
    secret = password()
    if not config.user or not secret:
        raise ValueError(
            "the inbound mailbox needs mail.inbound.user, and a password from "
            "$TALANTON_INBOUND_PASSWORD or mail.inbound.password_secret. Leave them unset to "
            "run without a mailbox — CVs can be put in the CVs location by hand."
        )
    session = IMAPClient(config.imap_server, port=config.imap_port, ssl=True)
    session.login(config.user, secret)
    return session


def unread(session: IMAPClient) -> list[dict[str, Any]]:
    """Unread messages in the selected folder, as plain dicts."""
    out = []
    for msg_id, data in session.fetch(session.search("UNSEEN"), [b"BODY.PEEK[]"]).items():
        raw = data[b"BODY[]"]
        msg = email.message_from_bytes(raw)
        out.append(
            {
                "id": str(msg_id),
                # Carried so `fetch` need not ask the server for all of this a
                # second time.
                "raw": raw,
                "sender": email.utils.parseaddr(str(msg.get("From", "")))[1].lower(),
                "recipients": ",".join(recipients(msg)),
                "subject": str(msg.get("Subject", "")),
                "body": body(msg),
            }
        )
    return out


def recipients(msg: email.message.Message) -> list[str]:
    """Every address a message was delivered to, for routing to an opening.

    Delivered-To is checked first: it survives plus-addressing and forwarding,
    where the To header often does not.
    """
    headers = [str(msg.get(h, "")) for h in ("Delivered-To", "To", "Cc", "X-Original-To")]
    return [address.lower() for _, address in email.utils.getaddresses([h for h in headers if h]) if address]


def opening_for(message: dict[str, str]) -> str:
    """Which opening an application is for, from the address it was sent to.

    Each position carries its own `apply_to`, so give every opening an address
    — or one address with a plus tag — and applications sort themselves. Mail
    that matches nothing is filed under `unsorted` for a person to look at,
    never guessed into an opening.
    """
    routes = {}
    for position in positions.every():
        routes[str(position["apply_to"]).strip().lower()] = positions.slug(position)

    for address in message.get("recipients", "").split(","):
        found = routes.get(address.strip().lower())
        if found:
            return found
    return UNSORTED


def body(msg: email.message.Message) -> str:
    """The plain-text body, preferring text/plain over any HTML part."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    return ""


def attachments(msg: email.message.Message) -> list[tuple[str, bytes]]:
    """Every named attachment, as (filename, bytes).

    `get_payload(decode=True)` is only bytes for a leaf part with a transfer
    encoding; on a malformed message it can hand back a string or a nested
    Message. Anything that is not bytes is not a file, so it is skipped rather
    than written out as one.
    """
    out: list[tuple[str, bytes]] = []
    for part in msg.walk():
        name = part.get_filename()
        payload = part.get_payload(decode=True)
        if name and isinstance(payload, bytes) and payload:
            out.append((name, payload))
    return out


def cv_filename(sender: str, filename: str) -> str:
    """Namespaces an attachment by sender, so two people's `cv.pdf` do not
    collide in the CVs location and one silently overwrite the other."""
    stem = sender.split("@")[0] if "@" in sender else UNKNOWN_SENDER
    return f"{stem or UNKNOWN_SENDER}-{filename}"


def peek() -> list[dict[str, Any]]:
    """What is unread, marking nothing. The safe first look."""
    session = client()
    try:
        session.select_folder("INBOX")
        return unread(session)
    finally:
        session.logout()


def fetch() -> list[str]:
    """Pull CVs out of the mailbox and into the CVs location.

    Moves files. No model call, and no way to reply.

    Returns:
        list[str]: The CV filenames written.
    """
    session = client()
    written = []

    limits = current().inbound
    max_attachment_bytes = limits.max_attachment_mb * 1024 * 1024

    try:
        session.select_folder("INBOX")
        # One fetch, not two. `unread` used to pull every body, and this pulled
        # them all again, which doubled the memory a flooded mailbox costs.
        everything = unread(session)
        held_back = max(len(everything) - limits.max_emails_per_run, 0)
        messages = everything[: limits.max_emails_per_run]
        if held_back:
            logging.info(
                "%d message(s) left for the next run; this one is capped at %d",
                held_back,
                limits.max_emails_per_run,
            )

        for message in messages:
            msg = email.message_from_bytes(message["raw"])
            opening = opening_for(message)
            found = False

            for filename, payload in attachments(msg):
                if not filename.lower().endswith(DOCUMENT_SUFFIXES):
                    continue
                if len(payload) > max_attachment_bytes:
                    # Say which file and why. A candidate whose CV is too large
                    # deserves to be asked for a smaller one, not ignored.
                    logging.warning(
                        "%s from %s is %.1f MB, over the %d MB ceiling; not written",
                        filename,
                        message["sender"],
                        len(payload) / 1024 / 1024,
                        limits.max_attachment_mb,
                    )
                    continue
                written.append(store.write_cv(cv_filename(message["sender"], filename), payload, opening).name)
                found = True

            if not found:
                # A body-only application is still an application.
                text = message["body"].strip()
                if len(text) < documents.MIN_USEFUL_CHARS:
                    logging.warning("Nothing usable from %s; left unread for a person", message["sender"])
                    continue
                written.append(
                    store.write_cv(
                        cv_filename(message["sender"], "application.txt"), text.encode("utf-8"), opening
                    ).name
                )

            session.add_flags(int(message["id"]), [b"\\Seen"])
    finally:
        session.logout()

    logging.info("Fetched %d CV(s)", len(written))
    return written
