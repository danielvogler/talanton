"""Google Cloud Storage, as one location backend.

Auth is application default credentials. There is no service-account key file
and there must never be one.

The bucket is made by a person, with its region pinned — GEG uses
`europe-west6` (Zurich), which is a data-residency requirement rather than a
preference. This code never creates a bucket and never changes an IAM policy,
so it cannot widen access to anything. Retention belongs on the bucket, as a
lifecycle rule, so deletion is enforced by infrastructure rather than by
someone remembering.
"""

import logging

from .locations import Item, LocationError

CONSOLE = "https://console.cloud.google.com/storage/browser/_details"


def bucket(name: str):
    """The bucket handle.

    Raises:
        LocationError: If the optional GCS library is not installed.
    """
    try:
        from google.cloud import storage
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise LocationError(
            "a gcs location needs the [gcs] extra: "
            'uv add "talanton[gcs] @ git+https://github.com/danielvogler/talanton"'
        ) from exc

    return storage.Client().bucket(name)


class GCSLocation:
    """A prefix inside a bucket."""

    backend = "gcs"

    def __init__(self, bucket_name: str, prefix: str = "") -> None:
        if not bucket_name:
            raise LocationError('a gcs location needs a bucket, e.g. bucket = "geg-hiring"')
        self.bucket_name = bucket_name
        self.prefix = prefix.strip("/")

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def _item(self, blob) -> Item:
        name = blob.name.removeprefix(f"{self.prefix}/") if self.prefix else blob.name
        return Item(id=blob.name, name=name, uri=f"{CONSOLE}/{self.bucket_name}/{blob.name}")

    def list(self) -> list[Item]:
        handle = bucket(self.bucket_name)
        blobs = handle.list_blobs(prefix=f"{self.prefix}/" if self.prefix else None)
        # A "directory placeholder" is a zero-byte object ending in /, not a file.
        return sorted(
            (self._item(b) for b in blobs if not b.name.endswith("/")),
            key=lambda i: i.name,
        )

    def read(self, item: Item) -> bytes:
        blob = bucket(self.bucket_name).blob(item.id)
        if not blob.exists():
            raise LocationError(f"no such object in gs://{self.bucket_name}: {item.name}")
        return blob.download_as_bytes()

    def write(self, filename: str, payload: bytes) -> Item:
        from .locations import safe_filename

        blob = bucket(self.bucket_name).blob(self._key(safe_filename(filename)))
        blob.upload_from_string(payload)
        logging.info("Wrote gs://%s/%s", self.bucket_name, blob.name)
        return self._item(blob)

    def child(self, name: str) -> "GCSLocation":
        from .locations import safe_filename

        return GCSLocation(self.bucket_name, self._key(safe_filename(name)))

    def verify(self) -> None:
        """Checks the bucket exists and these credentials can reach it."""
        from google.api_core.exceptions import GoogleAPICallError
        from google.auth.exceptions import GoogleAuthError

        from .locations import LocationError

        try:
            bucket(self.bucket_name).reload()
        except (GoogleAPICallError, GoogleAuthError) as exc:
            raise LocationError(f"cannot reach gs://{self.bucket_name}: {exc}") from exc

    def __repr__(self) -> str:
        return f"gcs:{self.bucket_name}/{self.prefix}" if self.prefix else f"gcs:{self.bucket_name}"
