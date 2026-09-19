"""The inbound mail adapter. It moves files. It cannot send."""

import inspect
from email.message import EmailMessage

from talanton import inbound, store

LONG = "Ten years of production Python and distributed systems. " * 5


def message(sender="anna@example.test", body="Please see attached.", attachment=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, "apply@example.com", "Application"
    msg["Delivered-To"] = "apply@example.com"
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


def test_two_applications_do_not_collide():
    """Both must survive; one silently overwriting the other loses an applicant."""
    assert inbound.application_id("<one@ex>") != inbound.application_id("<two@ex>")


def test_the_same_message_is_the_same_candidate():
    """So a re-read of one message updates it rather than adding a rival."""
    assert inbound.application_id("<one@ex>") == inbound.application_id(" <one@ex> ")


def test_two_messages_without_a_message_id_are_not_the_same_candidate():
    """Collapsing them into one would lose all but the last, which is worse
    than a candidate whose message carried no header."""
    assert inbound.application_id("", "11") != inbound.application_id("", "12")


def test_a_fetched_cv_lands_in_the_cvs_location(position):
    candidate = inbound.application_id("<anna@ex>")
    store.write_documents(candidate, [("cv.txt", LONG.encode())])
    assert [i.name for i in store.list_cvs()] == [f"{candidate}.txt"]


def test_three_attachments_from_one_person_are_one_candidate(position, monkeypatch):
    """The bug this fixes: the covering letter scored near zero and appeared in
    the shortlist as a weak applicant who does not exist, and the certificates
    came back unreadable."""
    raw = _multipart("anna@example.test", {"cv.txt": LONG, "cover-letter.txt": LONG, "certs.txt": LONG})
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    assert len(store.candidates("101-ai-engineer")) == 1


def test_all_three_documents_are_kept_not_just_the_first(position, monkeypatch):
    raw = _multipart("anna@example.test", {"cv.txt": LONG, "cover-letter.txt": LONG, "certs.txt": LONG})
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    [candidate] = store.candidates("101-ai-engineer")
    assert len(store.documents_for(candidate, "101-ai-engineer")) == 3


def test_fetch_records_how_an_application_arrived(position, monkeypatch):
    """It knows the sender and the date at the point it used to discard them."""
    raw = _multipart("anna@example.test", {"cv.txt": LONG})
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    [candidate] = store.candidates("101-ai-engineer")
    record = store.provenance(candidate, "101-ai-engineer")
    assert record["via"] == "mailbox"
    assert record["source"] == "anna@example.test"
    assert record["arrived"]


def test_a_forwarded_application_is_distinguishable_from_a_direct_one(position, monkeypatch):
    """The whole argument for recording the route: byte for byte these two are
    identical in the store, and the difference only existed in the mailbox."""
    raw = _multipart("operator@example.com", {"cv.txt": LONG})
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    [candidate] = store.candidates("101-ai-engineer")
    assert store.provenance(candidate, "101-ai-engineer")["source"] == "operator@example.com"


def _multipart(sender: str, files: dict[str, str], message_id: str = "") -> bytes:
    """One message carrying several documents, as a real application does."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"] = sender
    if message_id:
        msg["Message-ID"] = message_id
    msg["Delivered-To"] = "ai-engineer@example.com"
    msg["Subject"] = "Application"
    msg.set_content("Please find my application attached.")
    for name, text in files.items():
        msg.add_attachment(text.encode(), maintype="text", subtype="plain", filename=name)
    return msg.as_bytes()


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
    msg["Delivered-To"] = "ai-engineer@example.com"
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


def _application(headers: dict[str, str | list[str]]) -> bytes:
    """One application with whatever headers a test wants to try."""
    msg = EmailMessage()
    msg["From"] = "anna@example.test"
    msg["Subject"] = "Application"
    for name, value in headers.items():
        for one in value if isinstance(value, list) else [value]:
            msg[name] = one
    msg.set_content("Please find my CV attached.")
    msg.add_attachment(LONG.encode(), maintype="text", subtype="plain", filename="cv.txt")
    return msg.as_bytes()


def _filed(raw: bytes, monkeypatch) -> list[str]:
    """Which openings ended up with a CV in them."""
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    return [
        opening
        for opening in ("101-ai-engineer", "102-data-engineer", inbound.UNSORTED)
        if store.list_cvs(opening)
    ]


def test_a_sender_cannot_pick_the_opening_with_a_to_header(position, monkeypatch):
    """The README says nothing a sender writes changes where their application
    lands. `To` and `Cc` are written by the sender; only delivery decides."""
    position(opening=102, id="data-engineer", apply_to="data-engineer@example.com")
    raw = _application(
        {
            "Delivered-To": "data-engineer@example.com",
            "To": "ai-engineer@example.com",
            "Cc": "ai-engineer@example.com",
        }
    )
    assert _filed(raw, monkeypatch) == ["102-data-engineer"]


def test_a_cc_on_its_own_files_under_unsorted(position, monkeypatch):
    """Nothing vouches for where this was delivered, so a person sorts it."""
    raw = _application({"Cc": "ai-engineer@example.com", "To": "someone@example.test"})
    assert _filed(raw, monkeypatch) == [inbound.UNSORTED]


def test_a_forged_delivered_to_below_the_real_one_is_ignored(position, monkeypatch):
    """A sender can put Delivered-To in the message they compose. The
    delivering server prepends the real one above it, so only the first counts."""
    position(opening=102, id="data-engineer", apply_to="data-engineer@example.com")
    raw = _application({"Delivered-To": ["ai-engineer@example.com", "data-engineer@example.com"]})
    assert _filed(raw, monkeypatch) == ["101-ai-engineer"]


def test_no_delivered_to_says_so_in_the_log(position, monkeypatch, caplog):
    """A provider that adds no Delivered-To sorts nothing, and an operator has
    to be told that rather than finding an unsorted folder filling up."""
    import logging

    with caplog.at_level(logging.WARNING):
        _filed(_application({"To": "ai-engineer@example.com"}), monkeypatch)
    assert "No Delivered-To" in caplog.text


def test_an_oversized_cv_does_not_become_its_covering_note(configure, position, monkeypatch, caplog):
    """The body fallback is for an application written in the mail itself.
    Used here it would file the covering note as the CV, mark the message read,
    and lose the one thing this person actually sent."""
    import logging

    from talanton import config

    configure(inbound=config.Inbound(user="apply@example.com", password="x", max_attachment_mb=1))

    msg = EmailMessage()
    msg["From"], msg["Subject"] = "anna@example.test", "Application"
    msg["Delivered-To"] = "ai-engineer@example.com"
    msg.set_content(LONG)  # a full covering letter, long enough to pass as a CV
    msg.add_attachment(b"x" * (2 * 1024 * 1024), maintype="text", subtype="plain", filename="cv.txt")

    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([msg.as_bytes()]))
    with caplog.at_level(logging.WARNING):
        assert inbound.fetch() == []
    assert "left unread" in caplog.text


# --------------------------------------------------------------------------
# One message is one application. The sender is not the applicant: agencies,
# HR mailboxes and an operator forwarding all send for other people.
# --------------------------------------------------------------------------


def test_one_sender_submitting_four_people_is_four_candidates(position, monkeypatch):
    """An agency forwards four CVs from one address. Keying the candidate on
    that address makes them one person, and the later messages overwrite the
    earlier ones — three real applicants destroyed, silently."""
    made = [
        _multipart("agency@example.test", {f"{name}.txt": f"{LONG} {name}"}, message_id=f"<{name}@ex>")
        for name in ("benjamin", "max", "niclas", "peter")
    ]
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession(made))
    inbound.fetch()
    assert len(store.candidates("101-ai-engineer")) == 4


def test_no_applicants_documents_are_overwritten_by_the_next_message(position, monkeypatch):
    """The failure that makes this worse than the bug it replaced: a phantom
    candidate can be spotted and discarded, a destroyed one cannot."""
    made = [
        _multipart("agency@example.test", {"cv.txt": f"{LONG} {name}"}, message_id=f"<{name}@ex>")
        for name in ("benjamin", "niclas")
    ]
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession(made))
    inbound.fetch()
    bodies = [
        store.read_cv(i, "101-ai-engineer").decode()
        for items in store.candidates("101-ai-engineer").values()
        for i in items
    ]
    assert any("benjamin" in b for b in bodies)
    assert any("niclas" in b for b in bodies)


def test_one_message_with_three_attachments_is_still_one_candidate(position, monkeypatch):
    """The grouping this must not lose: three documents, one message, one person."""
    raw = _multipart("anna@example.test", {"cv.txt": LONG, "letter.txt": LONG, "certs.txt": LONG})
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    assert len(store.candidates("101-ai-engineer")) == 1


def test_two_messages_from_one_person_are_two_candidates(position, monkeypatch):
    """The accepted cost. Somebody who forgot a document and sends it again is
    two candidates — visible, and mergeable by a person. A duplicate is a
    nuisance; a merge is a decision made on somebody's behalf."""
    made = [
        _multipart("anna@example.test", {"cv.txt": LONG}, message_id="<one@ex>"),
        _multipart("anna@example.test", {"certs.txt": LONG}, message_id="<two@ex>"),
    ]
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession(made))
    inbound.fetch()
    assert len(store.candidates("101-ai-engineer")) == 2


def test_the_sender_is_still_recorded_even_though_it_is_not_the_identity(position, monkeypatch):
    raw = _multipart("agency@example.test", {"cv.txt": LONG}, message_id="<x@ex>")
    monkeypatch.setattr(inbound, "client", lambda: _FakeSession([raw]))
    inbound.fetch()
    [candidate] = store.candidates("101-ai-engineer")
    assert store.provenance(candidate, "101-ai-engineer")["source"] == "agency@example.test"
