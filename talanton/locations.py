"""Where things live, behind one small interface.

The core of this system is not a mailbox. It is two locations: somewhere CVs
are, and somewhere assessments go. Everything else — fetching mail, sending a
shortlist — is an adapter bolted onto that, and can be absent.

    list()   what is here
    read()   the bytes of one item
    write()  put one item here, and say how a human opens it

Three lines is the whole contract, so adding a backend is a small job. `local`
is the default and needs nothing configured; `gdrive` needs a folder someone
made. Anything else — GCS, S3 — implements the same three methods.

Access control belongs to the location, not to this code. A colleague who
cannot open the CV folder cannot read a CV, whatever any agent decides.
"""

import hashlib
import logging
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
MAX_NAME_LENGTH = 96
FALLBACK_NAME = "file"
DEFAULT_MIME = "application/octet-stream"


class LocationError(RuntimeError):
    """Raised when a location is misconfigured or unreachable."""


@dataclass(frozen=True)
class Item:
    """One file in a location.

    `id` is stable for the same file in the same place, so "have I already
    assessed this?" is answerable without a database.
    """

    id: str
    name: str
    uri: str


def safe_filename(name: str) -> str:
    """Reduces a filename to something safe to write.

    Filenames arrive from email attachments and from whoever dropped a file in
    a folder, so they are untrusted: strip any directory part and refuse
    anything that could climb out of the location.
    """
    stem = SAFE_NAME.sub("_", Path(name).name).strip("._") or FALLBACK_NAME
    if len(stem) <= MAX_NAME_LENGTH:
        return stem
    # Two long names that agree for their first 96 characters would otherwise
    # become the same file, and writing a CV replaces one of the same name by
    # design. The suffix is of the whole original, so it distinguishes them.
    tail = hashlib.sha256(stem.encode()).hexdigest()[:8]
    return f"{stem[: MAX_NAME_LENGTH - len(tail) - 1]}-{tail}"


class Location(Protocol):
    """Somewhere files live."""

    backend: str

    def list(self) -> list[Item]:
        """Every file here, oldest name first."""
        ...

    def read(self, item: Item) -> bytes:
        """The bytes of one item."""
        ...

    def write(self, filename: str, payload: bytes) -> Item:
        """Puts one file here and returns it, with a URI a human can open."""
        ...

    def child(self, name: str) -> "Location":
        """The same location, narrowed to one subfolder.

        This is how an opening gets its own drawer: five AI engineer postings
        do not share a pile of CVs.
        """
        ...

    def verify(self) -> None:
        """Raises LocationError if this place cannot actually be reached.

        `talanton check` calls this. A location that reads as empty when it is
        really unreachable is the worst failure this system has: nothing is
        wrong on screen, and every applicant in it goes unseen.
        """
        ...


class LocalLocation:
    """A directory. The default, and the one that needs no credentials."""

    backend = "local"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _ensure(self) -> Path:
        self.path.mkdir(parents=True, exist_ok=True)
        return self.path

    def list(self) -> list[Item]:
        if not self.path.exists():
            return []
        return [
            self._item(p) for p in sorted(self.path.iterdir()) if p.is_file() and not p.name.startswith(".")
        ]

    def _item(self, path: Path) -> Item:
        return Item(id=path.name, name=path.name, uri=path.resolve().as_uri())

    def read(self, item: Item) -> bytes:
        target = self.path / safe_filename(item.id)
        if not target.exists():
            raise LocationError(f"no such file in {self.path}: {item.name}")
        return target.read_bytes()

    def write(self, filename: str, payload: bytes) -> Item:
        target = self._ensure() / safe_filename(filename)
        target.write_bytes(payload)
        return self._item(target)

    def child(self, name: str) -> "LocalLocation":
        return LocalLocation(self.path / safe_filename(name))

    def verify(self) -> None:
        """Creates the directory. A local location is reachable by existing."""
        self._ensure()

    def __repr__(self) -> str:
        return f"local:{self.path}"


class DriveLocation:
    """A Google Drive folder.

    The folder is made by a person and named in the config. This code never
    creates a top-level folder and never changes sharing, so it cannot widen
    access to anything.
    """

    backend = "gdrive"

    def __init__(self, folder_id: str = "", folder_path: str = "") -> None:
        if not folder_id and not folder_path:
            raise LocationError('a gdrive location needs a folder_id, or a folder path like "hr/recruiting"')
        self._folder_id = folder_id
        self.folder_path = folder_path

    @property
    def folder_id(self) -> str:
        """Resolves the configured path once, if that is how it was given."""
        if not self._folder_id:
            from .drive import resolve_folder, service

            self._folder_id = resolve_folder(service(), self.folder_path)
        return self._folder_id

    def _service(self):
        from .drive import service

        return service()

    def list(self) -> list[Item]:
        from .drive import list_files

        return list_files(self._service(), self.folder_id)

    def read(self, item: Item) -> bytes:
        from .drive import download

        return download(self._service(), item.id)

    def write(self, filename: str, payload: bytes) -> Item:
        from .drive import upload

        item = upload(self._service(), self.folder_id, safe_filename(filename), payload, _mime(filename))
        logging.info("Wrote %s to Drive folder %s", item.name, self.folder_id)
        return item

    def child(self, name: str) -> "DriveLocation":
        """A subfolder, created if it is genuinely not there yet.

        Creating it inherits the parent's sharing, so this cannot widen access.
        It can, however, duplicate: credentials that cannot see a folder report
        it missing, and this runs on every command rather than only at setup.
        `drive.child_folder` is where that is decided, for this and for
        `resolve_folder` alike.
        """
        from .drive import child_folder, service

        return DriveLocation(folder_id=child_folder(service(), self.folder_id, safe_filename(name)))

    def verify(self) -> None:
        """Checks these credentials can see the configured folder.

        Not a permission check on paper — an actual read. Running as a person
        rather than the service account, every folder somebody else made is
        invisible, so `list` returns nothing and says nothing. This turns that
        into a failure at `check`, before anyone concludes the inbox is quiet.
        """
        from googleapiclient.errors import HttpError

        from .drive import folder_is_visible, service

        try:
            visible = folder_is_visible(service(), self.folder_id)
        except HttpError as exc:
            # Not a visibility answer. Whatever Google said is the useful part.
            raise LocationError(f"Drive refused folder {self.folder_id}: {exc}") from exc

        if not visible:
            raise LocationError(
                f"the credentials in use cannot see Drive folder {self.folder_id}. Either they lack "
                "access, or they are a human gcloud login, which only ever sees files talanton "
                "itself created for that person. Run as the service account: "
                "gcloud auth application-default login --impersonate-service-account=<sa>"
            )

    def __repr__(self) -> str:
        return f"gdrive:{self._folder_id or self.folder_path}"


def _mime(filename: str) -> str:
    return mimetypes.guess_type(filename)[0] or DEFAULT_MIME


BACKENDS = ("local", "gdrive", "gcs")


def build(spec, base: Path) -> Location:
    """Builds the location one config section describes.

    Args:
        spec: A LocationSpec from the config.
        base: Directory a relative local path resolves against.

    Raises:
        LocationError: If the backend is not one that exists.
    """
    if spec.backend == "local":
        return LocalLocation(base / Path(spec.path or "."))
    if spec.backend == "gdrive":
        return DriveLocation(spec.folder_id, spec.folder)
    if spec.backend == "gcs":
        from .gcs import GCSLocation

        return GCSLocation(spec.bucket, spec.prefix)
    raise LocationError(f"unknown backend {spec.backend!r}. Available: {', '.join(BACKENDS)}")
