"""Reading a CV. An unreadable one is reported, never scored."""

import pathlib
import re

import pytest

from talanton import documents

LONG = "Ten years of production Python and distributed systems work. " * 4


def test_plain_text_is_read():
    assert "production Python" in documents.extract("cv.txt", LONG.encode())


def test_markdown_is_read():
    assert documents.extract("cv.md", LONG.encode())


def test_an_unknown_format_says_what_it_can_read():
    with pytest.raises(documents.UnreadableError, match=re.escape(".pdf")):
        documents.extract("portfolio.pages", b"whatever")


def test_a_malformed_pdf_is_unreadable_not_empty():
    with pytest.raises(documents.UnreadableError):
        documents.extract("cv.pdf", b"not really a pdf")


def test_too_little_text_is_unreadable_rather_than_a_bad_cv():
    """A scan that yields nothing must never be scored as a weak candidate."""
    with pytest.raises(documents.UnreadableError, match=r"too\s+little"):
        documents.extract("cv.txt", b"Please find my CV attached.")


def test_the_scanned_example_is_reported_as_unreadable():
    scan = EXAMPLES / "scanned-cv.pdf"
    with pytest.raises(documents.UnreadableError, match="no text layer"):
        documents.extract(scan.name, scan.read_bytes())


EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "example" / "cvs" / "101-ai-engineer"


def _example(name: str) -> str:
    path = EXAMPLES / name
    return documents.extract(path.name, path.read_bytes())


def test_a_real_pdf_with_a_text_layer_reads():
    """What most applicants actually send."""
    text = _example("keller-nadia.pdf")
    assert "NADIA KELLER" in text and "nadia.keller@example.test" in text


def test_a_two_column_pdf_keeps_both_columns():
    """A sidebar layout is where naive extraction loses the contact details."""
    text = _example("andersson-lars.pdf")
    assert "lars.andersson@example.test" in text  # sidebar
    assert "Principal Engineer" in text  # main column
    assert "No Swiss permit" in text  # the knockout evidence


def test_a_pdf_with_a_date_rail_keeps_the_dates_with_the_roles():
    text = _example("keller-nadia.pdf")
    assert "Mar 2020" in text and "Senior ML Engineer" in text


def test_word_content_inside_a_table_is_not_lost():
    """A designed CV keeps half its content in a table. Missing it would score
    an experienced candidate as though they had no experience."""
    text = documents.extract("cv.docx", _docx_with_a_table())
    assert "Senior ML Engineer" in text
    assert "two incidents that were mine" in text


def test_opendocument_reads():
    text = documents.extract("cv.odt", _odt())
    assert "CAMILLE DUBOIS" in text and "research code" in text


def _docx_with_a_table() -> bytes:
    """A .docx whose experience sits in a table, as most designed CVs do."""
    import io
    import zipfile

    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'

    def para(text):
        return f'<w:p><w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'

    body = (
        para("ANNA MUELLER")
        + "<w:tbl><w:tr>"
        + f"<w:tc>{para('2020-2026')}</w:tc>"
        + f"<w:tc>{para('Senior ML Engineer. Six years in production, two incidents that were mine.')}</w:tc>"
        + "</w:tr></w:tbl>"
        + para("Skills: Python, PyTorch, GCP. German native, English fluent. Notice: two months.")
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "word/document.xml", f'<?xml version="1.0"?><w:document {ns}><w:body>{body}</w:body></w:document>'
        )
    return buffer.getvalue()


def _odt() -> bytes:
    import io
    import zipfile

    text_ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office_ns = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    content = (
        f'<?xml version="1.0"?><office:document-content xmlns:office="{office_ns}" xmlns:text="{text_ns}">'
        "<office:body><office:text>"
        "<text:h>CAMILLE DUBOIS</text:h>"
        "<text:p>Postdoctoral researcher, Lausanne. camille.dubois@example.test</text:p>"
        "<text:p>All work was research code; nothing was deployed to external users.</text:p>"
        "<text:p>PyTorch, JAX, distributed training. French native, English fluent.</text:p>"
        "</office:text></office:body></office:document-content>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr("content.xml", content)
    return buffer.getvalue()


def test_the_legacy_doc_format_is_refused_with_advice():
    """Vanishing silently would be worse than saying "send a PDF"."""
    with pytest.raises(documents.UnreadableError, match="Ask for a PDF"):
        documents.extract("cv.doc", b"\\xd0\\xcf\\x11\\xe0legacy binary")


def test_rtf_control_words_are_stripped():
    rtf = (
        rb"{\rtf1\ansi\deff0 {\fonttbl{\f0 Times;}}\f0\fs24 "
        + (b"Ten years of production Python work. " * 5)
        + rb"}"
    )
    assert "Ten years of production Python work." in documents.extract("cv.rtf", rtf)


def test_a_zip_bomb_is_refused_rather_than_expanded():
    """These arrive from strangers, so an archive is checked before it is read."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"\\0" * (documents.MAX_UNCOMPRESSED_BYTES + 1))
    with pytest.raises(documents.UnreadableError, match="expands to far more"):
        documents.extract("bomb.docx", buffer.getvalue())


def test_a_docx_that_is_not_a_zip_says_so():
    with pytest.raises(documents.UnreadableError, match="not a readable"):
        documents.extract("cv.docx", b"this is not a zip file at all")


def test_every_accepted_format_has_a_reader():
    """The inconsistency this suite exists to prevent: a format the store
    accepts as a CV but extraction cannot read."""
    from talanton import store

    unhandled = set(store.CV_SUFFIXES) - set(documents.READABLE_SUFFIXES) - set(documents.LEGACY_SUFFIXES)
    assert unhandled == set()


def _zip_with_lying_header(member: str, real_size: int) -> bytes:
    """A zip whose central directory understates how much a member expands to.

    Exactly the shape a decompression bomb takes: highly compressible bytes,
    and a declared `file_size` the reader is invited to trust.
    """
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member, b"A" * real_size)
    raw = bytearray(buffer.getvalue())

    # Rewrite only the declared *uncompressed* size, which is what infolist()
    # reports: offset 22 in a local header, 24 in a central directory entry.
    # The compressed sizes are left alone so the member still extracts.
    for marker, field in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        start = raw.find(marker)
        while start != -1:
            raw[start + field : start + field + 4] = (1024).to_bytes(4, "little")
            start = raw.find(marker, start + 1)
    return bytes(raw)


def test_a_zip_that_lies_about_its_size_is_refused():
    """The size guard reads `file_size` out of the archive's own directory, so
    a crafted file can understate it.

    What saves us is not that guard: CPython's zipfile stops reading at the
    declared size and then fails the CRC. So the refusal is real, but it comes
    from the standard library rather than from us, and the message says the
    contents do not match what the file declares. Recorded here so that if a
    future zipfile stops doing it, this test says so."""
    from talanton import documents

    payload = _zip_with_lying_header("word/document.xml", documents.MAX_UNCOMPRESSED_BYTES + 5_000)
    with pytest.raises(documents.UnreadableError, match=r"declares|expands"):
        documents._open_archive("bomb.docx", payload, "word/document.xml")


def test_an_archive_honest_about_being_enormous_is_refused():
    """The guard we do own."""
    import io
    import zipfile

    from talanton import documents

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"A" * (documents.MAX_UNCOMPRESSED_BYTES + 5_000))
    with pytest.raises(documents.UnreadableError, match="expands"):
        documents._open_archive("big.docx", buffer.getvalue(), "word/document.xml")


def test_an_ordinary_document_still_opens():
    import io
    import zipfile

    from talanton import documents

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", b"<w:document>hello</w:document>")
    assert b"hello" in documents._open_archive("cv.docx", buffer.getvalue(), "word/document.xml")


def test_a_file_larger_than_any_cv_is_refused_before_it_is_parsed():
    """`max_attachment_mb` guards the mailbox. A file dropped into the CVs
    folder by hand never went past a mailbox, so the ceiling is here too."""
    with pytest.raises(documents.UnreadableError, match="larger than any CV"):
        documents.extract("cv.pdf", b"x" * (documents.MAX_DOCUMENT_BYTES + 1))


def test_only_the_first_pages_of_a_pdf_are_read(caplog):
    """pypdf on a crafted file is where the CPU goes. A CV is not 500 pages."""
    import io
    import logging

    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(documents.MAX_PDF_PAGES + 5):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)

    with caplog.at_level(logging.WARNING), pytest.raises(documents.UnreadableError):
        documents.extract("long.pdf", buffer.getvalue())
    assert f"read the first {documents.MAX_PDF_PAGES}" in caplog.text


def _docx_with(document_xml: bytes) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", document_xml)
    return buffer.getvalue()


def test_a_document_that_declares_entities_is_refused():
    """`xml.etree` expands them, so ten nested entities expand a kilobyte into
    a gigabyte inside the parser, where the archive ceiling cannot see it."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        b'<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><d>&c;</d>'
    )
    with pytest.raises(documents.UnreadableError, match="declares XML entities"):
        documents.extract("cv.docx", _docx_with(bomb))


def test_a_document_with_no_dtd_still_reads():
    """The refusal above must cost a real applicant nothing."""
    assert "production Python" in documents.extract("cv.docx", _docx_with(_document_xml()))


def _document_xml() -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    para = f'<w:p><w:r><w:t xml:space="preserve">{LONG} production Python.</w:t></w:r></w:p>'
    return f'<?xml version="1.0"?><w:document {ns}><w:body>{para}</w:body></w:document>'.encode()
