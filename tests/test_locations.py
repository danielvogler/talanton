"""The storage interface. Three methods, and a new backend implements them."""

import pytest

from talanton import config, locations, store
from tests.conftest import OPENING


def test_a_local_location_round_trips(tmp_path):
    place = locations.LocalLocation(tmp_path / "cvs")
    item = place.write("anna.txt", b"hello")
    assert place.read(item) == b"hello"
    assert [i.name for i in place.list()] == ["anna.txt"]


def test_an_empty_location_lists_nothing(tmp_path):
    assert locations.LocalLocation(tmp_path / "nothing-here").list() == []


def test_writing_creates_the_directory(tmp_path):
    locations.LocalLocation(tmp_path / "deep" / "cvs").write("a.txt", b"x")
    assert (tmp_path / "deep" / "cvs" / "a.txt").exists()


def test_a_local_item_carries_an_openable_uri(tmp_path):
    item = locations.LocalLocation(tmp_path).write("a.txt", b"x")
    assert item.uri.startswith("file://")


def test_a_hostile_filename_cannot_escape_the_location(tmp_path):
    place = locations.LocalLocation(tmp_path / "cvs")
    item = place.write("../../../etc/passwd", b"root:x:0:0")
    assert (tmp_path / "cvs").resolve() == (tmp_path / "cvs" / item.name).parent.resolve()
    assert ".." not in item.name


def test_reading_something_absent_says_so(tmp_path):
    place = locations.LocalLocation(tmp_path)
    with pytest.raises(locations.LocationError, match="no such file"):
        place.read(locations.Item(id="ghost.txt", name="ghost.txt", uri=""))


def test_dotfiles_are_not_listed(tmp_path):
    (tmp_path).mkdir(exist_ok=True)
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    assert locations.LocalLocation(tmp_path).list() == []


def test_an_unknown_backend_names_the_ones_that_exist(tmp_path):
    with pytest.raises(locations.LocationError, match="gdrive"):
        locations.build(config.LocationSpec(backend="dropbox"), tmp_path)


def test_a_gdrive_location_needs_a_folder(tmp_path):
    with pytest.raises(locations.LocationError, match="folder"):
        locations.build(config.LocationSpec(backend="gdrive"), tmp_path)


def test_the_two_locations_can_use_different_backends(tmp_path, configure):
    configure(
        cvs=config.LocationSpec(backend="gdrive", folder_id="f1"),
        assessments=config.LocationSpec(backend="local", path="out"),
    )
    assert store.cvs().backend == "gdrive"
    assert store.assessments().backend == "local"


def test_only_documents_count_as_cvs(cv, tmp_path):
    """A stray file in the folder must not become a phantom candidate."""
    cv("anna.txt")
    store.cvs(OPENING).write("notes.json", b"{}")
    # Dropped in by hand rather than written through the location, so the
    # underscore survives — which is exactly the case the prefix guard is for.
    (tmp_path / "cvs" / "_scratch.txt").write_text("x" * 200, encoding="utf-8")
    assert [i.name for i in store.list_cvs(OPENING)] == ["anna.txt"]


def test_a_drive_path_can_be_resolved_inside_a_shared_drive(monkeypatch):
    """Candidate data belongs on a shared drive: the organisation owns it, so
    it survives any one account being deleted."""
    from talanton import drive

    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: True)

    class Files:
        def __init__(self):
            self.created = []

        def list(self, q, **kwargs):
            return type("R", (), {"execute": lambda _, **kw: {"files": []}})()

        def create(self, body, **kwargs):
            self.created.append((body["name"], body["parents"][0]))
            return type("R", (), {"execute": lambda _, **kw: {"id": f"id-{body['name']}"}})()

    class Service:
        def __init__(self):
            self._files = Files()

        def files(self):
            return self._files

    service = Service()
    drive.resolve_folder(service, "recruiting/cvs", create=True, root="0AShared")
    assert service.files().created == [("recruiting", "0AShared"), ("cvs", "id-recruiting")]


def test_my_drive_is_the_default_root():
    assert __import__("talanton.drive", fromlist=["ROOT"]).ROOT == "root"


class FakeFiles:
    """A Drive `files()` that can be told which folders it is able to see."""

    def __init__(self, visible=()):
        self.visible = dict(visible)
        self.created = []

    def list(self, q, **kwargs):
        name = q.split("name = '")[1].split("'")[0] if "name = '" in q else ""
        hit = [{"id": self.visible[name], "name": name}] if name in self.visible else []
        return type("R", (), {"execute": lambda _, **kw: {"files": hit}})()

    def create(self, body, **kwargs):
        self.created.append((body["name"], body["parents"][0]))
        return type("R", (), {"execute": lambda _, **kw: {"id": f"id-{body['name']}"}})()


class FakeService:
    def __init__(self, visible=()):
        self._files = FakeFiles(visible)

    def files(self):
        return self._files


def test_blind_credentials_refuse_to_create_a_folder_that_may_already_exist(monkeypatch):
    """Under drive.file a folder someone made in the browser is invisible, so
    `create` would silently make a second one and the clash would surface on a
    later run somewhere else."""
    from talanton import drive, locations

    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: False)
    service = FakeService()

    with pytest.raises(locations.LocationError, match="may exist and be invisible"):
        drive.resolve_folder(service, "recruiting", create=True, root="0AShared")
    assert service.files().created == [], "a folder was created despite the refusal"


def test_force_creates_anyway(monkeypatch):
    """The operator who has checked in the browser can say so."""
    from talanton import drive

    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: False)
    service = FakeService()
    drive.resolve_folder(service, "recruiting", create=True, root="0AShared", force=True)
    assert service.files().created == [("recruiting", "0AShared")]


def test_credentials_that_see_everything_create_without_ceremony(monkeypatch):
    """An attached service account sees the whole drive, so a folder that is
    not found is genuinely absent."""
    from talanton import drive

    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: True)
    service = FakeService()
    drive.resolve_folder(service, "recruiting/cvs", create=True, root="0AShared")
    assert service.files().created == [("recruiting", "0AShared"), ("cvs", "id-recruiting")]


def test_an_existing_folder_is_never_duplicated(monkeypatch):
    """Visible folders are walked into, whatever the credentials can see."""
    from talanton import drive

    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: False)
    service = FakeService(visible={"recruiting": "existing-id"})
    assert drive.resolve_folder(service, "recruiting", create=True, root="0AShared") == "existing-id"
    assert service.files().created == []


def test_a_human_login_is_treated_as_blind_and_a_service_account_is_not():
    """The rule that decides it: Google refuses restricted Drive scopes to the
    gcloud OAuth client, so an ADC user only ever holds drive.file."""
    from google.oauth2.credentials import Credentials as UserCredentials

    from talanton import drive

    assert drive._sees_everything(UserCredentials(token="x")) is False
    assert drive._sees_everything(object()) is True


def test_a_local_location_verifies_by_existing(tmp_path):
    from talanton import locations

    place = locations.LocalLocation(tmp_path / "cvs")
    place.verify()
    assert (tmp_path / "cvs").is_dir()


def test_a_drive_folder_you_cannot_see_is_reported_not_silently_empty(monkeypatch):
    """The failure that matters most: running as the wrong identity, every
    folder is invisible, so every listing is empty and nothing says why."""
    from talanton import drive, locations

    monkeypatch.setattr(drive, "service", lambda: object())
    monkeypatch.setattr(drive, "folder_is_visible", lambda svc, folder_id: False)

    place = locations.DriveLocation(folder_id="1G750")
    with pytest.raises(locations.LocationError, match="cannot see"):
        place.verify()


def test_a_visible_drive_folder_verifies(monkeypatch):
    from talanton import drive, locations

    monkeypatch.setattr(drive, "service", lambda: object())
    monkeypatch.setattr(drive, "folder_is_visible", lambda svc, folder_id: True)
    locations.DriveLocation(folder_id="1G750").verify()


def test_check_fails_when_a_drive_folder_is_invisible(configure, monkeypatch, capsys):
    """`talanton check` is the command everyone runs first. It has to be the
    thing that catches this, not an empty `status` an hour later."""
    from talanton import cli, config, drive

    monkeypatch.setattr(drive, "service", lambda: object())
    monkeypatch.setattr(drive, "folder_is_visible", lambda svc, folder_id: False)
    configure(
        cvs=config.LocationSpec(backend="gdrive", folder_id="1G750"),
        assessments=config.LocationSpec(backend="gdrive", folder_id="1QzH"),
    )

    assert cli.check_locations() is False
    assert "cannot see" in capsys.readouterr().out


class FakeHttpError(Exception):
    """Stands in for googleapiclient.errors.HttpError, which needs a response."""

    def __init__(self, status):
        self.resp = type("R", (), {"status": status})()
        super().__init__(f"HTTP {status}")


def _service_raising(status):
    class Files:
        def get(self, **kwargs):
            raise FakeHttpError(status)

    return type("S", (), {"files": lambda self: Files()})()


def test_a_404_means_the_folder_is_invisible(monkeypatch):
    """Under drive.file Drive will not admit a file exists, so 404 is the
    signal that the identity is wrong."""
    import googleapiclient.errors

    from talanton import drive

    monkeypatch.setattr(googleapiclient.errors, "HttpError", FakeHttpError)
    assert drive.folder_is_visible(_service_raising(404), "1G750") is False


def test_a_403_is_not_answered_as_invisible(monkeypatch):
    """A missing quota project answers 403. Calling that "you cannot see it"
    sends somebody hunting for a permission problem they do not have."""
    import googleapiclient.errors

    from talanton import drive

    monkeypatch.setattr(googleapiclient.errors, "HttpError", FakeHttpError)
    with pytest.raises(FakeHttpError):
        drive.folder_is_visible(_service_raising(403), "1G750")


def test_child_refuses_to_shadow_a_subfolder_it_cannot_see(monkeypatch):
    """The path that runs on every command. An opening's drawer is resolved by
    DriveLocation.child, so this is where a duplicate would really be made."""
    from talanton import drive, locations

    monkeypatch.setattr(drive, "service", lambda: FakeService())
    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: False)

    place = locations.DriveLocation(folder_id="1G750")
    with pytest.raises(locations.LocationError, match="may exist and be invisible"):
        place.child("101-ai-engineer")


def test_child_creates_the_drawer_when_the_identity_can_see_the_whole_drive(monkeypatch):
    from talanton import drive, locations

    service = FakeService()
    monkeypatch.setattr(drive, "service", lambda: service)
    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: True)

    child = locations.DriveLocation(folder_id="1G750").child("101-ai-engineer")
    assert service.files().created == [("101-ai-engineer", "1G750")]
    assert child.folder_id == "id-101-ai-engineer"


def test_child_reuses_a_drawer_that_is_already_there(monkeypatch):
    """Whatever the credentials are, a visible folder is walked into."""
    from talanton import drive, locations

    service = FakeService(visible={"101-ai-engineer": "existing"})
    monkeypatch.setattr(drive, "service", lambda: service)
    monkeypatch.setattr(drive, "sees_pre_existing_files", lambda: False)

    assert locations.DriveLocation(folder_id="1G750").child("101-ai-engineer").folder_id == "existing"
    assert service.files().created == []


def test_drive_uses_ambient_credentials_when_no_account_is_named(configure, monkeypatch):
    """On a laptop already impersonating the account, wrapping again would
    only add a hop and another IAM grant to hold."""
    import google.auth

    from talanton import drive

    sentinel = object()
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (sentinel, "p"))
    assert drive.credentials() is sentinel


def test_drive_impersonates_when_an_account_is_named(configure, monkeypatch):
    """Cloud Run's metadata server returns a cloud-platform token whatever is
    asked of it, and Drive rejects cloud-platform. Exchanging it through the
    IAM Credentials API is what gets a token that carries the Drive scope."""
    import google.auth
    from google.auth import impersonated_credentials
    from google.oauth2.credentials import Credentials as UserCredentials

    from talanton import config, drive

    configure(screening=config.Screening(service_account="talanton@example.iam.gserviceaccount.com"))
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (UserCredentials(token="x"), "p"))

    got = drive.credentials()
    assert isinstance(got, impersonated_credentials.Credentials)
    assert list(drive.SCOPES) == ["https://www.googleapis.com/auth/drive"]


def test_an_impersonated_identity_is_treated_as_seeing_everything(configure, monkeypatch):
    import google.auth
    from google.oauth2.credentials import Credentials as UserCredentials

    from talanton import config, drive

    configure(screening=config.Screening(service_account="talanton@example.iam.gserviceaccount.com"))
    monkeypatch.setattr(google.auth, "default", lambda scopes=None: (UserCredentials(token="x"), "p"))
    # The source is a human login, which alone sees only what it created. What
    # it is exchanged for is not, and that is the identity that reaches Drive.
    assert drive.sees_pre_existing_files() is True


class _ExpiredTokenError(Exception):
    """Stands in for google.auth.exceptions.RefreshError."""


def _service_whose_token_expired():
    class Files:
        def get(self, **kwargs):
            raise _ExpiredTokenError("Reauthentication is needed.")

        def list(self, **kwargs):
            raise _ExpiredTokenError("Reauthentication is needed.")

    return type("S", (), {"files": lambda self: Files()})()


def test_an_expired_credential_says_what_to_run(configure, monkeypatch):
    """The commonest failure in this system, and it used to arrive as fifteen
    frames of traceback. Nobody should have to remember the command."""
    import google.auth.exceptions

    from talanton import config, drive, locations

    monkeypatch.setattr(google.auth.exceptions, "GoogleAuthError", _ExpiredTokenError)
    monkeypatch.setattr(drive, "service", _service_whose_token_expired)
    configure(screening=config.Screening(service_account="talanton@acme.iam.gserviceaccount.com"))

    with pytest.raises(locations.LocationError) as caught:
        locations.DriveLocation(folder_id="1G750").verify()

    message = str(caught.value)
    assert "gcloud auth application-default login" in message
    assert "--impersonate-service-account=talanton@acme.iam.gserviceaccount.com" in message


def test_with_no_service_account_configured_it_still_says_what_to_run(configure, monkeypatch):
    import google.auth.exceptions

    from talanton import drive, locations

    monkeypatch.setattr(google.auth.exceptions, "GoogleAuthError", _ExpiredTokenError)
    monkeypatch.setattr(drive, "service", _service_whose_token_expired)

    with pytest.raises(locations.LocationError) as caught:
        locations.DriveLocation(folder_id="1G750").verify()

    message = str(caught.value)
    assert "gcloud auth application-default login" in message
    assert "service_account" in message, "it should say how to name one"
