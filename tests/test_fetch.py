"""The inbound mail adapter. It moves files. It cannot send."""

import inspect
from email.message import EmailMessage

from talanton import inbound, store

LONG = "Ten years of production Python and distributed systems. " * 5


def message(sender="anna@example.test", body="Please see attached.", attachment=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "apply@example.com", "Application"
    msg.set_content(body)
    if attachment:
        name, content = attachment
        msg.add_attachment(content.encode(), maintype="text", subtype="plain", filename=name)
    return msg


def test_the_fetch_stage_makes_no_model_call():
    assert "ask(" not in inspect.getsource(inbound.fetch)


def test_an_attachment_becomes_a_cv(position):
    parts = inbound.attachments(message(attachment=("cv.txt", LONG)))
    assert parts[0][0] == "cv.txt"


def test_two_people_with_the_same_filename_do_not_collide():
    """Both must survive; one silently overwriting the other loses an applicant."""
    first = inbound.cv_filename("anna@example.test", "cv.pdf")
    second = inbound.cv_filename("bob@example.test", "cv.pdf")
    assert first != second
    assert first == "anna-cv.pdf"


def test_a_sender_without_an_address_still_gets_a_name():
    assert inbound.cv_filename("", "cv.pdf") == "unknown-cv.pdf"


def test_a_fetched_cv_lands_in_the_cvs_location(position):
    store.cvs().write(inbound.cv_filename("anna@example.test", "cv.txt"), LONG.encode())
    assert [i.name for i in store.list_cvs()] == ["anna-cv.txt"]


def test_a_flood_is_capped_and_the_rest_left_for_the_next_run(configure, position, monkeypatch):
    """A mailbox full of applications should be a bounded run, not a bill."""
    from talanton import config, inbound

    configure(inbound=config.Inbound(user="apply@example.com", password="x", max_emails_per_run=2))

    made = [_message(f"a{i}@example.test", f"cv{i}.txt", b"x" * 200) for i in range(5)]
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession(made))
    assert len(inbound.fetch()) == 2


def test_an_oversized_attachment_is_skipped_not_written(configure, position, monkeypatch, caplog):
    """Writing it would cost storage and a screening; ignoring it silently
    would lose a person. It is skipped, and the log says which file."""
    import logging

    from talanton import config, inbound

    configure(inbound=config.Inbound(user="apply@example.com", password="x", max_attachment_mb=1))

    big = _message("huge@example.test", "cv.txt", b"x" * (2 * 1024 * 1024))
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([big]))
    with caplog.at_level(logging.WARNING):
        written = inbound.fetch()
    assert written == []
    assert "over the 1 MB ceiling" in caplog.text
    assert "cv.txt" in caplog.text


def _message(sender: str, filename: str, payload: bytes) -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "ai-engineer@example.com"
    msg["Subject"] = "Application"
    msg.set_content("Please find my CV attached.")
    msg.add_attachment(payload, maintype="text", subtype="plain", filename=filename)
    return msg.as_bytes()


class _FakeSession:
    """Just enough IMAPClient for fetch()."""

    def __init__(self, raws):
        self._raws = {i + 1: r for i, r in enumerate(raws)}

    def select_folder(self, name):
        pass

    def search(self, criteria):
        return list(self._raws)

    def fetch(self, ids, parts):
        return {i: {b"BODY[]": self._raws[i]} for i in ids}

    def add_flags(self, msg_id, flags):
        pass

    def logout(self):
        pass
