"""Google Drive, as one location backend.

Auth is application default credentials, and there is never a service-account
key file. What ADC resolves to decides what Drive this code can see, and the
two cases behave differently enough that it is worth being blunt about which
one you are in.

**An attached service account** — Cloud Run, a GCE VM, GKE — mints its own
token with the scopes it asks for, so it gets `drive` and sees everything the
service account is a member of. Add it to the shared drive the way you would
add a colleague; that membership is the access control. This is the deployed
mode, it needs no key file and no domain-wide delegation, and it is the only
mode that runs unattended.

**A human's `gcloud auth application-default login`** gets `drive.file` and
only `drive.file`, whatever it asked for. Google refuses restricted Drive
scopes such as `drive.metadata.readonly` to the gcloud OAuth client, so asking
for them at login fails at the consent screen with "This app is blocked" —
do not go looking in the Workspace admin console, there is nothing there to
change. `drive.file` reaches only files this code created, which means a folder
somebody made in the browser is invisible rather than absent. `resolve_folder`
knows the difference and refuses to create over it.
"""

import functools
import io
import logging

from .config import current
from .locations import Item, LocationError

# Asked for unconditionally. A service account is granted it; a user credential
# silently keeps whatever it was granted at login, so this costs them nothing.
SCOPES = ("https://www.googleapis.com/auth/drive",)
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT = "root"
FILE_FIELDS = "id,name,webViewLink,mimeType"
# A socket with no timeout hangs a scheduled run until somebody notices. A
# socket with a timeout and no retry turns one slow response into a failed
# stage. Observed both while screening a dozen CVs: three runs died on a Drive
# read that would have succeeded a second later.
TIMEOUT_SECONDS = 120
RETRIES = 4


def service():
    """An authenticated Drive v3 service.

    Raises:
        LocationError: If the optional Drive libraries are not installed.
    """
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise LocationError(
            "a gdrive location needs the [gdrive] extra: "
            'uv add "talanton[gdrive] @ git+https://github.com/danielvogler/talanton"'
        ) from exc

    import google_auth_httplib2
    import httplib2

    authorised = google_auth_httplib2.AuthorizedHttp(credentials(), http=httplib2.Http(timeout=TIMEOUT_SECONDS))
    return build("drive", "v3", http=authorised, cache_discovery=False)


def credentials():
    """Credentials that can actually hold the Drive scope.

    `google.auth.default(scopes=...)` only widens a credential that is allowed
    to be widened. On a laptop impersonating the service account it already is,
    and on a GCE VM the instance's own access scopes decide. On Cloud Run the
    metadata server hands back a `cloud-platform` token whatever is asked for,
    and the Drive API rejects `cloud-platform` — which surfaces as a 403 that
    reads like a permissions problem and sends somebody hunting through
    shared-drive membership for a fault that is not there.

    So when `[screening] service_account` names an account, the ambient
    credentials are exchanged for one through the IAM Credentials API, which
    does honour the scopes asked of it. That needs
    `roles/iam.serviceAccountTokenCreator` on the account, held by the account
    itself when a deployment runs as it. Still no key file, anywhere.
    """
    import google.auth

    source, _ = google.auth.default(scopes=list(SCOPES))
    target = current().screening.service_account
    if not target:
        return source

    from google.auth import impersonated_credentials

    return impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=target,
        target_scopes=list(SCOPES),
    )


def explain_credentials(exc: Exception) -> str:
    """What to do about credentials that will not work, naming the account.

    An expired token is the commonest failure this system has, and it used to
    arrive as a stack trace ending in RefreshError. The configuration already
    names the identity to act as, so the message can say exactly what to run
    rather than leaving somebody to remember it.
    """
    target = current().screening.service_account
    if target:
        return (
            f"the credentials could not be used ({exc}).\n"
            "      Run this, then try again:\n"
            "        gcloud auth application-default login \\\n"
            f"          --impersonate-service-account={target}"
        )
    return (
        f"the credentials could not be used ({exc}).\n"
        "      Run: gcloud auth application-default login\n"
        "      If this deployment has a service account, name it as [screening] "
        "service_account and impersonate it, so everyone sees the same drive."
    )


def readable_auth_errors(call):
    """Turns a credential failure into a LocationError that says what to run.

    Wrapped around every function here that reaches Drive, because the token is
    refreshed lazily: the failure lands on whichever call happens to be first,
    not where the credentials were built.
    """

    @functools.wraps(call)
    def guarded(*args, **kwargs):
        import google.auth.exceptions

        try:
            return call(*args, **kwargs)
        except google.auth.exceptions.GoogleAuthError as exc:
            raise LocationError(explain_credentials(exc)) from exc

    return guarded


def escape_query(value: str) -> str:
    """Escapes a name for a Drive query. A folder called "Bob's" would
    otherwise close the quote and change the query."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _item(record: dict) -> Item:
    return Item(
        id=record["id"],
        name=record.get("name", record["id"]),
        uri=record.get("webViewLink") or f"https://drive.google.com/file/d/{record['id']}/view",
    )


@readable_auth_errors
def list_files(svc, folder_id: str) -> list[Item]:
    """Every non-folder file directly in one Drive folder."""
    query = f"'{escape_query(folder_id)}' in parents and mimeType != '{FOLDER_MIME}' and trashed = false"
    items, page = [], None
    while True:
        response = (
            svc.files()
            .list(
                q=query,
                fields=f"nextPageToken,files({FILE_FIELDS})",
                pageToken=page,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute(num_retries=RETRIES)
        )
        items += [_item(f) for f in response.get("files", [])]
        page = response.get("nextPageToken")
        if not page:
            return sorted(items, key=lambda i: i.name)


@readable_auth_errors
def download(svc, file_id: str) -> bytes:
    """The bytes of one Drive file."""
    from googleapiclient.http import MediaIoBaseDownload

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, svc.files().get_media(fileId=file_id, supportsAllDrives=True))
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=RETRIES)
    return buffer.getvalue()


@readable_auth_errors
def upload(svc, folder_id: str, filename: str, payload: bytes, mime: str) -> Item:
    """Writes one file into a Drive folder, replacing a file of the same name.

    Replacing matters for assessments: re-running a screen should update the
    assessment, not leave two contradictory ones side by side.
    """
    from googleapiclient.http import MediaIoBaseUpload

    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype=mime, resumable=False)
    existing = _find_file(svc, folder_id, filename)

    if existing:
        record = (
            svc.files()
            .update(fileId=existing, media_body=media, fields=FILE_FIELDS, supportsAllDrives=True)
            .execute(num_retries=RETRIES)
        )
    else:
        record = (
            svc.files()
            .create(
                body={"name": filename, "parents": [folder_id]},
                media_body=media,
                fields=FILE_FIELDS,
                supportsAllDrives=True,
            )
            .execute(num_retries=RETRIES)
        )
    return _item(record)


def _find_file(svc, folder_id: str, filename: str) -> str:
    query = f"'{escape_query(folder_id)}' in parents and name = '{escape_query(filename)}' and trashed = false"
    found = (
        svc.files()
        .list(q=query, fields="files(id)", pageSize=1, supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute(num_retries=RETRIES)
        .get("files", [])
    )
    return found[0]["id"] if found else ""


@readable_auth_errors
def folder_is_visible(svc, folder_id: str) -> bool:
    """Whether these credentials can read the folder at all.

    Under `drive.file` a folder somebody else created is not merely empty, it
    is absent: Drive answers 404 rather than admitting it exists, so every
    listing inside it comes back with nothing and no error. That is the failure
    worth catching early, because it looks exactly like "no applications have
    arrived yet".

    Only 404 means that. A 403 is a different animal — a missing quota project,
    a disabled API, a rate limit — and answering "you cannot see it" would send
    somebody hunting for a permission problem they do not have. Those are left
    to raise, so the caller can report what Google actually said.
    """
    from googleapiclient.errors import HttpError

    try:
        svc.files().get(fileId=folder_id, fields="id", supportsAllDrives=True).execute(num_retries=RETRIES)
    except HttpError as exc:
        if exc.resp.status == 404:
            return False
        raise
    return True


@readable_auth_errors
def find_child_folder(svc, parent: str, name: str) -> str:
    """The id of a folder directly inside `parent`, or "" if there is none."""
    query = (
        f"'{escape_query(parent)}' in parents and name = '{escape_query(name)}'"
        f" and mimeType = '{FOLDER_MIME}' and trashed = false"
    )
    found = (
        svc.files()
        .list(
            q=query, fields="files(id,name)", pageSize=2, supportsAllDrives=True, includeItemsFromAllDrives=True
        )
        .execute(num_retries=RETRIES)
        .get("files", [])
    )
    if len(found) > 1:
        raise LocationError(
            f"{name!r} is ambiguous: {len(found)} folders of that name share a parent. "
            "Use an explicit folder_id and name the one you mean."
        )
    return found[0]["id"] if found else ""


@readable_auth_errors
def create_child_folder(svc, parent: str, name: str) -> str:
    """Creates a folder inside `parent`. Inherits its sharing, so this cannot
    widen access to anything."""
    created = (
        svc.files()
        .create(
            body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent]},
            fields="id",
            supportsAllDrives=True,
        )
        .execute(num_retries=RETRIES)
    )
    logging.info("Created Drive folder %r under %s", name, parent)
    return created["id"]


def _sees_everything(credentials) -> bool:
    """Whether these credentials can see files this code did not create.

    A user credential cannot, ever: Google refuses restricted Drive scopes to
    the gcloud OAuth client, so an ADC login holds `drive.file` however it was
    obtained. Anything else here is a service account, which mints its own
    token with the scopes it asked for.
    """
    from google.oauth2.credentials import Credentials as UserCredentials

    return not isinstance(credentials, UserCredentials)


@readable_auth_errors
def sees_pre_existing_files() -> bool:
    """Whether the ambient credentials can see a folder somebody else made.

    Split from `_sees_everything` so tests can answer the question without
    resolving real credentials, and so `resolve_folder` can ask it only on the
    path where the answer changes what happens.
    """
    return _sees_everything(credentials())


@readable_auth_errors
def child_folder(svc, parent: str, name: str, force: bool = False) -> str:
    """The id of a subfolder, created only when it is genuinely not there.

    Not found is not the same as not there. Under `drive.file` this query
    cannot see a folder somebody else made, so creating one leaves two of the
    same name side by side, and that surfaces on a later run, as "is
    ambiguous", somewhere else entirely.

    Shared by `resolve_folder` and `locations.DriveLocation.child` so the two
    cannot drift apart on when creating is safe. `child` is the one that runs
    on every command, because every opening has its own drawer.
    """
    found = find_child_folder(svc, parent, name)
    if found:
        return found
    if not force and not sees_pre_existing_files():
        raise LocationError(
            f"{name!r} was not found under {parent}, but these credentials only see files "
            "talanton created, so it may exist and be invisible. Creating it would produce a "
            "duplicate, and the clash would surface on a later run. Run as the service account "
            "to see the whole drive."
        )
    return create_child_folder(svc, parent, name)


@readable_auth_errors
def resolve_folder(svc, path: str, create: bool = False, root: str = ROOT, force: bool = False) -> str:
    """Walks a Drive folder path and returns the id of its last segment.

    Args:
        svc: An authenticated Drive service.
        path: A path like "hr/recruiting".
        create: Create segments that do not exist yet.
        root: Where to start. "root" is My Drive; pass a shared drive's id to
            start there instead. A shared drive is the better home for
            candidate data: the organisation owns it, so it survives any one
            account being deleted, and membership is managed in one place.
        force: Create even when the credentials cannot see whether the folder
            is already there. For someone who has checked in the browser.

    Raises:
        LocationError: If a segment is missing and `create` is false, or if it
            cannot be told apart from a segment that is merely invisible.
    """
    segments = [s for s in path.split("/") if s.strip()]
    if not segments:
        raise LocationError("a Drive folder path cannot be empty")

    parent, walked = root, []
    for segment in segments:
        walked.append(segment)
        found = find_child_folder(svc, parent, segment)
        if found:
            parent = found
        elif create:
            try:
                parent = child_folder(svc, parent, segment, force=force)
            except LocationError as exc:
                raise LocationError(f"{'/'.join(walked)!r}: {exc}. Or pass --force.") from exc
        else:
            raise LocationError(
                f"no Drive folder at {'/'.join(walked)!r}. Create it, or pass --create. If it exists "
                "but is not found, these credentials only see files talanton created — an attached "
                "service account sees the whole drive — or it may live in a shared drive rather "
                "than My Drive."
            )
    return parent
