"""Mailbox passwords out of Google Secret Manager, as whoever is running.

The point is that access is decided by IAM rather than by who happens to have a
`.env`. Someone with `roles/secretmanager.secretAccessor` on the secret runs the
pipeline; someone without it gets a permission error from Google and goes no
further. Nobody has to hand a password to anybody, and revoking access is one
IAM change rather than a rotation.

Credentials are application default credentials — the caller's own `gcloud`
login. There is no service-account key file, and there must never be one.

Nothing here logs a secret, and no error message contains one.
"""

import logging
import os
import re

SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
# Accepts a bare name, or a full resource path for a secret in another project.
FULL_PATH = re.compile(r"^projects/[^/]+/secrets/[^/]+(/versions/[^/]+)?$")
DEFAULT_VERSION = "latest"
# Where a mailbox password is replicated. Automatic replication spreads it
# wherever Google likes, which sits badly beside a bucket pinned to Zurich and
# called a residency requirement. These are user-managed replicas, so the value
# stays in Europe. Screening still runs in `global` — that is a separate
# decision about CV text, and it is not this one.
REPLICA_LOCATIONS = ("europe-west1", "europe-west4")


class SecretError(RuntimeError):
    """Raised when a secret cannot be read. Never contains the secret."""


def resource_name(reference: str, project: str) -> str:
    """Turns a bare secret name into a full resource path.

    Args:
        reference: A bare name, or an already-complete resource path.
        project: The project the bare name lives in.

    Raises:
        SecretError: If a bare name is given with no project to look it up in.
    """
    if FULL_PATH.match(reference):
        return reference if "/versions/" in reference else f"{reference}/versions/{DEFAULT_VERSION}"
    if not project:
        raise SecretError(
            f"{reference!r} is a bare secret name, so it needs a project. Set [screening] project, "
            "or write the full path: projects/<project>/secrets/<name>/versions/latest"
        )
    return f"projects/{project}/secrets/{reference}/versions/{DEFAULT_VERSION}"


def read(reference: str, project: str = "") -> str:
    """Reads one secret as the current user.

    Whitespace is stripped, because a Google app password pasted into a secret
    carries the display spaces it was shown with.

    Raises:
        SecretError: If the library is missing, the caller is not permitted, or
            the secret does not exist. The message says which, and never
            includes the value.
    """
    name = resource_name(reference, project)

    try:
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise SecretError(
            "reading secrets needs the [secrets] extra: "
            'uv add "talanton[secrets] @ git+https://github.com/danielvogler/talanton"'
        ) from exc

    try:
        client = secretmanager.SecretManagerServiceClient()
        response = client.access_secret_version(request={"name": name})
    except Exception as exc:
        raise SecretError(_explain(name, exc)) from exc

    logging.info("Read %s from Secret Manager", name)
    return "".join(response.payload.data.decode("utf-8").split())


def _explain(name: str, exc: Exception) -> str:
    """Turns a Google error into something the reader can act on."""
    text = f"{type(exc).__name__}: {exc}"

    if "PermissionDenied" in text or "403" in text:
        return (
            f"you are not permitted to read {name}. That is the access control working: ask a "
            "partner to grant you roles/secretmanager.secretAccessor on that secret. Do not ask "
            "anyone to send you the password instead."
        )
    if "NotFound" in text or "404" in text:
        return f"no secret at {name}. Check the name, the project, and that a version exists."
    if "DefaultCredentialsError" in text or "could not automatically determine" in text.lower():
        return f"no credentials to read {name} with. Run: gcloud auth application-default login"
    return f"could not read {name}. {text}"


def create(name: str, project: str, value: str) -> str:
    """Creates a secret if it is absent and adds this value as a new version.

    Adding a version rather than replacing one is what makes rotation safe: the
    old version stays readable until you disable it, so nothing breaks the
    moment a new app password is minted.

    Returns:
        str: The resource name of the version that was added.

    Raises:
        SecretError: If the library is missing or the caller is not permitted.
    """
    try:
        from google.api_core import exceptions
        from google.cloud import secretmanager
    except ImportError as exc:  # pragma: no cover - depends on an optional extra
        raise SecretError(
            "creating secrets needs the [secrets] extra: "
            'uv add "talanton[secrets] @ git+https://github.com/danielvogler/talanton"'
        ) from exc

    if not project:
        raise SecretError("creating a secret needs a project. Set [screening] project.")

    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project}"

    try:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": name,
                "secret": {
                    "replication": {
                        "user_managed": {"replicas": [{"location": where} for where in REPLICA_LOCATIONS]}
                    }
                },
            }
        )
        logging.info("Created secret %s/secrets/%s", parent, name)
    except exceptions.AlreadyExists:
        logging.info("Secret %s/secrets/%s exists; adding a version", parent, name)
    except Exception as exc:
        raise SecretError(_explain(f"{parent}/secrets/{name}", exc)) from exc

    try:
        version = client.add_secret_version(
            request={
                "parent": f"{parent}/secrets/{name}",
                "payload": {"data": "".join(value.split()).encode("utf-8")},
            }
        )
    except Exception as exc:
        raise SecretError(_explain(f"{parent}/secrets/{name}", exc)) from exc

    return version.name


def grant_command(name: str, project: str) -> str:
    """The one command that lets a colleague run the pipeline.

    Access is granted per secret, so the person who screens candidates can be a
    different person from the one who reads the mailbox.
    """
    return (
        f"gcloud secrets add-iam-policy-binding {name} --project={project} \\\n"
        "  --member='user:colleague@example.com' \\\n"
        "  --role='roles/secretmanager.secretAccessor'"
    )


def password(env_names: tuple[str, ...], reference: str, project: str) -> str:
    """The password for one mailbox: the environment first, then Secret Manager.

    An explicit environment variable always wins, so a local override and CI
    both keep working. With neither, this returns "" and the caller reports
    that the mailbox is unconfigured rather than failing here.
    """
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return "".join(value.split())
    return read(reference, project) if reference else ""
