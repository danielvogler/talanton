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
from datetime import UTC, datetime
from typing import Any

from imapclient import IMAPClient

from . import documents, positions, secrets, store
from .config import current

DOCUMENT_SUFFIXES = (".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md")
UNKNOWN_SENDER = "unknown"
# A message with no Message-ID header. Rare, and not a reason to merge it
# with the next one.
UNKNOWN_MESSAGE = "message"
# How an application that came through the mailbox is recorded, against the
# `import` that `talanton.intake` writes for one that did not.
VIA = "mailbox"
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
                # The application's identity. Globally unique and written
                # by the sending client, so two applications forwarded from
                # one agency address stay two applications.
                "message_id": str(msg.get("Message-ID", "")).strip(),
                # Two lists, and the difference is the routing decision. One is
                # what the receiving server recorded, the other is what the
                # message claims. Only the first sorts anything.
                "delivered_to": ",".join(delivered_to(msg)),
                "recipients": ",".join(recipients(msg)),
                "subject": str(msg.get("Subject", "")),
                "body": body(msg),
            }
        )
    return out


def delivered_to(msg: email.message.Message) -> list[str]:
    """The addresses this mailbox was actually delivered at. Routing reads this.

    `Delivered-To` is added by the receiving server. `To`, `Cc` and usually
    `X-Original-To` are written by whoever sent the message, so routing on them
    lets a sender pick their own drawer: Cc the address of the opening they
    want, mail the one they qualify for, and land in the first.

    Only the first one, and that is the whole point of the header. A sender can
    put a Delivered-To of their own in the message they compose; the delivering
    server prepends the real one above it. Reading them all would take the
    forgery back.
    """
    return _addresses([str(msg.get("Delivered-To", ""))])


def recipients(msg: email.message.Message) -> list[str]:
    """Every address the message names, delivery and claim alike.

    Shown to a person by `peek`, and used for nothing else. Anything here that
    is not also in `delivered_to` is the sender's word for it.
    """
    headers = [str(msg.get(h, "")) for h in ("Delivered-To", "To", "Cc", "X-Original-To")]
    return _addresses(headers)


def _addresses(headers: list[str]) -> list[str]:
    return [address.lower() for _, address in email.utils.getaddresses([h for h in headers if h]) if address]


def opening_for(message: dict[str, str]) -> str:
    """Which opening an application is for, from where it was delivered.

    Each position carries its own `apply_to`, so give every opening an address
    — or one address with a plus tag — and applications sort themselves. Mail
    that matches nothing is filed under `unsorted` for a person to look at,
    never guessed into an opening.

    Only `Delivered-To` sorts. A message without one is a message nobody can
    vouch for the destination of, so it goes to `unsorted` rather than to
    whichever opening its own headers ask for.
    """
    routes = {}
    for position in positions.every():
        routes[str(position["apply_to"]).strip().lower()] = positions.slug(position)

    delivered = message.get("delivered_to", "")
    if not delivered.strip():
        logging.warning(
            "No Delivered-To on the message from %s; filed under %s. If your provider does not "
            "add that header, applications will not sort themselves and a person must file them.",
            message.get("sender", UNKNOWN_SENDER),
            UNSORTED,
        )
        return UNSORTED

    for address in delivered.split(","):
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


def application_id(message_id: str, uid: str = "") -> str:
    """The candidate one message's documents belong to.

    Keyed on the message. One message is one application, and that is the only
    unit here that holds: a sender is not an applicant.

    Keying on the filename cannot join one person's three attachments, so they
    become three candidates — two of them phantoms. Keying on the sender joins
    them, and then joins four different people who reached the mailbox through
    one agency, one HR inbox or one colleague forwarding, and writes them over
    each other. That is the same error with the sign flipped and it is the
    worse of the two: a phantom candidate can be seen in a listing and
    discarded, a destroyed one leaves nothing behind to notice.

    The cost is that somebody who sends a second mail with a document they
    forgot becomes a second candidate. That is a duplicate — visible, and
    mergeable by a person who can see both. A duplicate is a nuisance; a merge
    is a decision taken on somebody's behalf without telling them.

    `Message-ID` is written by the sending client and is globally unique. A
    message without one falls back to the mailbox's own id for it, which is
    enough to keep two messages apart within a run.
    """
    token = (message_id or "").strip() or f"{UNKNOWN_MESSAGE}-{uid}"
    return store.candidate_id(token)


def sent_on(msg: email.message.Message) -> str:
    """The date the message says it was sent, or empty if it does not parse.

    Written by the sender's mail client, so it is a claim rather than something
    this can vouch for — which is why the provenance record carries it beside
    the date talanton actually read the mailbox, instead of instead of it.
    """
    try:
        parsed = email.utils.parsedate_to_datetime(str(msg.get("Date", "")))
    except (TypeError, ValueError):
        return ""
    return parsed.date().isoformat() if parsed else ""


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
    written: list[str] = []

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
            candidate = application_id(message.get("message_id", ""), message["id"])
            enclosed: list[tuple[str, bytes]] = []
            oversize = False

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
                    oversize = True
                    continue
                enclosed.append((filename, payload))

            found = bool(enclosed)
            if not found and oversize:
                # The body fallback exists for an application written in the
                # mail itself. Reaching it here would file a covering note as
                # the CV and mark the message read, and the actual CV — the one
                # thing this person sent — would be gone without anyone seeing
                # it. Left unread instead, for a person to ask for a smaller file.
                logging.warning(
                    "Nothing written for %s: their CV was over the ceiling and the mail is left unread",
                    message["sender"],
                )
                continue

            if not found:
                # A body-only application is still an application.
                text = message["body"].strip()
                if len(text) < documents.MIN_USEFUL_CHARS:
                    logging.warning("Nothing usable from %s; left unread for a person", message["sender"])
                    continue
                enclosed = [("application.txt", text.encode("utf-8"))]

            # One message is one application, however many documents it
            # carries, and the record says so before the mail is marked read.
            stored = store.write_documents(candidate, enclosed, opening)
            written.extend(item.name for item in stored)
            store.write_provenance(
                candidate,
                {
                    "arrived": datetime.now(UTC).date().isoformat(),
                    "via": VIA,
                    "source": message["sender"] or UNKNOWN_SENDER,
                    "by": current().inbound.user,
                    "sent": sent_on(msg),
                    "documents": [item.name for item in stored],
                },
                opening,
            )

            session.add_flags(int(message["id"]), [b"\\Seen"])
    finally:
        session.logout()

    logging.info("Fetched %d CV(s)", len(written))
    return written
