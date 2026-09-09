"""Getting readable text out of a CV.

Nobody applies with a .txt file. What actually arrives is PDF, sometimes Word,
occasionally a scan, and the formats are handled here so the rest of the system
never has to care.

    .pdf            a text layer, via pypdf. Most CVs.
    .docx, .odt     zipped XML. Read directly, including text inside tables,
                    which is where a designed CV usually keeps half its content.
    .rtf            control words stripped.
    .txt, .md       as they are.
    .doc            refused with an explanation. The legacy binary format needs
                    a converter this project will not carry.

An unreadable CV is not an error and is never a zero. The candidate is still
listed, the reason is recorded, and a person is told — silently scoring someone
badly because their PDF was a scan would be the worst failure this system could
have.

Everything here parses files written by strangers, so it is defensive: there is
a ceiling on the file, a ceiling on the pages, archives are checked against a
decompression bomb, and the XML is parsed by something that refuses a DTD.

The mail path already caps what it will write, but a CV can also be dropped
into the folder by hand or by whatever fills it upstream, and that path has no
mailbox in front of it. The ceilings live here so both are covered.
"""

import io
import itertools
import logging
import re
import xml.etree.ElementTree as ElementTree
import zipfile

import defusedxml.ElementTree
from defusedxml.common import DefusedXmlException

PDF_SUFFIXES = (".pdf",)
TEXT_SUFFIXES = (".txt", ".md", ".markdown")
DOCX_SUFFIXES = (".docx",)
ODT_SUFFIXES = (".odt",)
RTF_SUFFIXES = (".rtf",)
LEGACY_SUFFIXES = (".doc",)

READABLE_SUFFIXES = PDF_SUFFIXES + TEXT_SUFFIXES + DOCX_SUFFIXES + ODT_SUFFIXES + RTF_SUFFIXES

# Anything shorter than this is not a CV; it is a failed extraction.
MIN_USEFUL_CHARS = 120
# A CV is a few hundred kilobytes. An archive claiming to expand to more than
# this is a decompression bomb, not an application.
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
# The same ceiling the mailbox applies, applied again here. A file dropped into
# the CVs folder by hand never went past the mailbox at all.
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
# Nobody's CV is longer than this, and pypdf has had more than one CPU
# exhaustion report on crafted files. Reading twenty pages costs a bounded
# amount whatever the file claims about itself.
MAX_PDF_PAGES = 20

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ODF_TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"

RTF_CONTROL = re.compile(r"\\'[0-9a-fA-F]{2}|\\[a-zA-Z]+-?\d* ?|[{}]")
BLANK_RUN = re.compile(r"\n{3,}")


class UnreadableError(Exception):
    """Raised when a document yields no usable text."""


def extract(filename: str, payload: bytes) -> str:
    """Pulls text out of one document.

    Args:
        filename: Used only to pick a reader.
        payload: The file bytes.

    Returns:
        str: The extracted text.

    Raises:
        UnreadableError: If the format is unsupported, the file is malformed,
            or it yields too little text to assess.
    """
    lowered = filename.lower()

    if len(payload) > MAX_DOCUMENT_BYTES:
        raise UnreadableError(
            f"{filename}: {len(payload) / 1024 / 1024:.1f} MB is larger than any CV needs to be "
            f"(the ceiling is {MAX_DOCUMENT_BYTES // 1024 // 1024} MB). Nothing was read from it. "
            "Ask for a smaller file."
        )
    if lowered.endswith(LEGACY_SUFFIXES):
        raise UnreadableError(
            f"{filename}: .doc is the legacy binary Word format and cannot be read here. "
            "Ask for a PDF, which is what most people have anyway."
        )
    if lowered.endswith(TEXT_SUFFIXES):
        text = payload.decode("utf-8", errors="replace")
    elif lowered.endswith(PDF_SUFFIXES):
        text = _pdf(filename, payload)
    elif lowered.endswith(DOCX_SUFFIXES):
        text = _docx(filename, payload)
    elif lowered.endswith(ODT_SUFFIXES):
        text = _odt(filename, payload)
    elif lowered.endswith(RTF_SUFFIXES):
        text = _rtf(payload)
    else:
        raise UnreadableError(
            f"{filename}: no reader for this format. Readable: {', '.join(READABLE_SUFFIXES)}. Ask for a PDF."
        )

    return _checked(filename, text)


def _checked(filename: str, text: str) -> str:
    """Tidies the text and refuses anything too thin to assess."""
    cleaned = BLANK_RUN.sub("\n\n", "\n".join(line.rstrip() for line in text.splitlines())).strip()
    if len(cleaned) < MIN_USEFUL_CHARS:
        raise UnreadableError(
            f"{filename}: only {len(cleaned)} characters of text came out, which is too little to "
            "assess. It is most likely a scan or an image-only PDF — the file itself is fine, it "
            "just has no text layer. Read it yourself, or ask for one that does."
        )
    return cleaned


def _pdf(filename: str, payload: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(payload))
        pages = list(itertools.islice(reader.pages, MAX_PDF_PAGES))
        if len(reader.pages) > MAX_PDF_PAGES:
            logging.warning("%s has %d pages; read the first %d", filename, len(reader.pages), MAX_PDF_PAGES)
        return "\n".join(page.extract_text() or "" for page in pages)
    except Exception as exc:
        logging.warning("Could not read %s: %s", filename, exc)
        raise UnreadableError(f"{filename}: the PDF could not be parsed ({exc})") from exc


def _open_archive(filename: str, payload: bytes, member: str) -> bytes:
    """Reads one member of a zipped document, refusing a decompression bomb.

    Two guards, because the first one trusts the file. `file_size` comes from
    the archive's own central directory, so it catches an archive that is
    honest about being enormous and nothing else.

    The second bounds the read itself. CPython's zipfile already stops at the
    declared size and fails the CRC, so an understating header does not
    actually expand — but that is an implementation detail of the standard
    library, not a promise, and this is the one place where a stranger's file
    is decompressed.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            if sum(i.file_size for i in archive.infolist()) > MAX_UNCOMPRESSED_BYTES:
                raise UnreadableError(f"{filename}: this archive expands to far more than a CV should.")
            with archive.open(member) as handle:
                data = handle.read(MAX_UNCOMPRESSED_BYTES + 1)
            if len(data) > MAX_UNCOMPRESSED_BYTES:
                raise UnreadableError(f"{filename}: this archive expands to far more than a CV should.")
            return data
    except (zipfile.BadZipFile, KeyError) as exc:
        raise UnreadableError(
            f"{filename}: not a readable {member.split('/')[0]} document. The file is damaged, or "
            f"its contents do not match what it declares ({exc})."
        ) from exc


def _docx(filename: str, payload: bytes) -> str:
    """Text from a .docx, in document order.

    Walks paragraphs rather than using a library's `paragraphs` list, because a
    designed CV usually lays itself out in a table and that list skips them.
    """
    root = _parse(filename, _open_archive(filename, payload, "word/document.xml"))
    lines = []
    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        runs = [node.text or "" for node in paragraph.iter(f"{{{WORD_NS}}}t")]
        lines.append("".join(runs))
    return "\n".join(lines)


def _odt(filename: str, payload: bytes) -> str:
    """Text from an .odt, paragraph and heading order preserved."""
    root = _parse(filename, _open_archive(filename, payload, "content.xml"))
    wanted = {f"{{{ODF_TEXT_NS}}}p", f"{{{ODF_TEXT_NS}}}h"}
    return "\n".join("".join(node.itertext()) for node in root.iter() if node.tag in wanted)


def _parse(filename: str, xml: bytes) -> ElementTree.Element:
    """Parses one document's XML, refusing anything that declares entities.

    `xml.etree` expands internal entities, so ten nested ones expand a
    kilobyte into a gigabyte inside the parser, where the archive ceiling above
    cannot see it. A .docx or .odt written by a word processor has no DTD at
    all, so refusing one costs a real applicant nothing.
    """
    try:
        return defusedxml.ElementTree.fromstring(xml)
    except DefusedXmlException as exc:
        raise UnreadableError(
            f"{filename}: this document declares XML entities, which a CV has no use for and "
            f"which cost more to expand than to write ({exc})."
        ) from exc
    except ElementTree.ParseError as exc:
        raise UnreadableError(f"{filename}: the document's XML is malformed ({exc})") from exc


def _rtf(payload: bytes) -> str:
    """Text from an .rtf, with control words stripped.

    Deliberately crude. RTF from a word processor is mostly markup around plain
    runs of text, and a CV does not need more than that.
    """
    return RTF_CONTROL.sub("", payload.decode("utf-8", errors="replace"))
