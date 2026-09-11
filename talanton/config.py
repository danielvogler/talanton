"""Everything configurable, in one immutable object.

A company does not fork this repository. It installs it, writes one
`talanton.toml`, and points it at a private store:

    from talanton import config, run
    config.use(config.load("talanton.toml"))
    run.cycle("101")

Settings come from the file. Secrets never do — those are read from the
environment, so a committed config file can never carry one. The EMAIL_* and
IMAP_* variable names match email-assistance-agent, so one .env serves both.
"""

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

CONFIG_ENV = "TALANTON_CONFIG"
DEFAULT_CONFIG_NAME = "talanton.toml"
# A stable Vertex model, deliberately not a preview: a screening standard that
# quietly changes under you between runs is worse than one a little behind.
DEFAULT_MODEL = "gemini-3.8-flash"
DEFAULT_MAX_OUTPUT_TOKENS = 8000
DEFAULT_MAX_EMAILS_PER_RUN = 25
DEFAULT_REPLY_WITHIN_DAYS = 7
DEFAULT_MAX_ATTACHMENT_MB = 20
DEFAULT_IDLE_TIMEOUT_SECONDS = 900
# Where a published opening goes by default. Deliberately not `openings`:
# that is `positions.OPENINGS_DIR`, the source of truth, and a rendered copy
# landing beside the position files would show up in the operator's git status.
PUBLISHED_DIR = "published"


class ConfigError(ValueError):
    """Raised when a configuration file is missing something required."""


@dataclass(frozen=True)
class Company:
    """Who is hiring. Reaches the agent's instructions, so keep it factual."""

    name: str = "the company"
    description: str = "a company"
    locale: str = "en"


@dataclass(frozen=True)
class Inbound:
    """The apply mailbox. Read-only by construction.

    These credentials reach an inbox full of CVs, and nothing that holds them
    can send: `talanton.inbound` has no SMTP path and does not import the
    module that does.
    """

    user: str = ""
    password: str = ""
    # A Secret Manager secret holding the app password, read as whoever is
    # running. Access is then an IAM decision rather than who has a .env.
    password_secret: str = ""
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    # Ceilings, so a flooded mailbox is a bounded run rather than a bill. Both
    # were defined as constants and wired to nothing for several versions.
    max_emails_per_run: int = DEFAULT_MAX_EMAILS_PER_RUN
    max_attachment_mb: int = DEFAULT_MAX_ATTACHMENT_MB


@dataclass(frozen=True)
class Outbound:
    """The sending identity. A different account, on purpose.

    It sends the shortlist and nothing else, so it needs no access to the apply
    mailbox — and having none is the point. If this identity were ever misused,
    it could not read a single CV.

    `reply_to` points a human's reply back at the apply mailbox, which is
    otherwise unread by anybody.
    """

    user: str = ""
    # The account SMTP authenticates as, when that is not the address in From.
    # An alias cannot log in: Google accepts the account it belongs to, and
    # refuses the alias with the same 535 it gives a wrong password. Empty
    # means the two are the same address, which is the ordinary case.
    login_user: str = ""
    password: str = ""
    password_secret: str = ""
    smtp_server: str = "smtp.gmail.com"
    smtp_port: int = 465
    reply_to: str = ""
    dry_run: bool = True
    # Addresses the shortlist may reach. Nothing else is ever a recipient.
    operators: tuple[str, ...] = ()
    # The only domains any outbound mail may reach.
    allow_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class Screening:
    """The model, where it is served, and the numbers the loop needs.

    `project` and `location` are written down rather than left to an ambient
    `gcloud config` default — running a screening against the wrong project is
    exactly the mistake that ambient defaults cause.
    """

    model: str = DEFAULT_MODEL
    project: str = ""
    location: str = ""
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    reply_within_days: int = DEFAULT_REPLY_WITHIN_DAYS
    # The identity to act as, when the ambient one cannot hold Drive scopes.
    # Empty means use application default credentials exactly as found, which
    # is right on a laptop impersonating the account already. See drive.service.
    service_account: str = ""
    # Applications that match no position's apply address are filed here.
    default_role: str = ""


@dataclass(frozen=True)
class LocationSpec:
    """One configured place. `local` needs only a path; `gdrive` a folder."""

    backend: str = "local"
    path: str = ""  # local
    folder_id: str = ""  # gdrive, explicit
    folder: str = ""  # gdrive, as a path like "hr/recruiting"
    bucket: str = ""  # gcs
    prefix: str = ""  # gcs, a prefix inside the bucket
    # Whether the config file actually asked for this location. Every field
    # above has a usable default, so without this a section nobody wrote is
    # indistinguishable from one written out in full — and an optional
    # location has no way to stay quiet.
    configured: bool = False


@dataclass(frozen=True)
class Schedule:
    """How often the sweep runs. How often is a deployment's decision.

    `cron` is not executed by anything here — the scheduler that fires
    `talanton cycle` owns that. It lives in the config so the cadence is
    written down in one place with everything else, and `talanton check`
    can tell an operator what their deployment is set to.
    """

    cron: str = ""
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class Config:
    """The whole configuration. Frozen: build a new one, never mutate this."""

    # The working area: positions live here, and it is the base that relative
    # location paths resolve against.
    store: Path = Path()
    # The two locations the core runs on. Everything else is an adapter.
    cvs: LocationSpec = field(default_factory=lambda: LocationSpec(path="cvs"))
    assessments: LocationSpec = field(default_factory=lambda: LocationSpec(path="assessments"))
    # Optional, and write-only: where `publish` puts a rendered opening. Not
    # `openings`, which is where the position files themselves live.
    openings: LocationSpec = field(default_factory=lambda: LocationSpec(path=PUBLISHED_DIR))
    company: Company = field(default_factory=Company)
    inbound: Inbound = field(default_factory=Inbound)
    outbound: Outbound = field(default_factory=Outbound)
    screening: Screening = field(default_factory=Screening)
    schedule: Schedule = field(default_factory=Schedule)


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    section = data.get(name) or {}
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] must be a table")
    return section


def _addresses(values: Any, where: str) -> tuple[str, ...]:
    """Normalises an address list. Matching is exact and lowercase."""
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ConfigError(f"{where} must be a list of addresses")
    return tuple(str(v).strip().lower() for v in values if str(v).strip())


def _password(*names: str) -> str:
    """Reads an app password from the first environment variable that has one,
    with all whitespace removed.

    Google shows an app password as four groups of four — `abcd efgh ijkl mnop`
    — and people paste what they are shown. The spaces are display only, and
    leaving them in fails the login with an authentication error that says
    nothing about spaces. Stripping them costs nothing: an app password never
    contains meaningful whitespace.
    """
    for name in names:
        value = os.environ.get(name)
        if value:
            return "".join(value.split())
    return ""


def _from_env_list(name: str) -> tuple[str, ...] | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return tuple(v.strip().lower() for v in raw.split(",") if v.strip())


def _company(data: dict[str, Any]) -> Company:
    section = _section(data, "company")
    return Company(
        name=str(section.get("name", Company.name)),
        description=str(section.get("description", Company.description)),
        locale=str(section.get("locale", Company.locale)),
    )


def _inbound(data: dict[str, Any]) -> Inbound:
    """[mail.inbound] — IMAP only. The password never comes from the file."""
    section = _section(_section(data, "mail"), "inbound")
    return Inbound(
        user=os.environ.get("TALANTON_INBOUND_USER")
        or os.environ.get("EMAIL_USER")
        or str(section.get("user", "")),
        password=_password("TALANTON_INBOUND_PASSWORD", "EMAIL_PASSWORD"),
        password_secret=str(os.environ.get("TALANTON_INBOUND_SECRET") or section.get("password_secret", "")),
        imap_server=os.environ.get("IMAP_SERVER") or str(section.get("imap_server", Inbound.imap_server)),
        imap_port=int(os.environ.get("IMAP_PORT") or section.get("imap_port", Inbound.imap_port)),
        max_emails_per_run=int(section.get("max_emails_per_run", Inbound.max_emails_per_run)),
        max_attachment_mb=int(section.get("max_attachment_mb", Inbound.max_attachment_mb)),
    )


def _outbound(data: dict[str, Any], inbound: Inbound) -> Outbound:
    """[mail.outbound] — SMTP only, and a separate account from the inbox."""
    section = _section(_section(data, "mail"), "outbound")
    return Outbound(
        user=os.environ.get("TALANTON_OUTBOUND_USER") or str(section.get("user", "")),
        login_user=os.environ.get("TALANTON_OUTBOUND_LOGIN") or str(section.get("login_user", "")),
        password=_password("TALANTON_OUTBOUND_PASSWORD"),
        password_secret=str(os.environ.get("TALANTON_OUTBOUND_SECRET") or section.get("password_secret", "")),
        smtp_server=os.environ.get("SMTP_SERVER") or str(section.get("smtp_server", Outbound.smtp_server)),
        smtp_port=int(os.environ.get("SMTP_PORT") or section.get("smtp_port", Outbound.smtp_port)),
        # A reply to the shortlist should reach the apply mailbox, not an
        # unread bot account.
        reply_to=str(section.get("reply_to", "") or inbound.user),
        dry_run=_dry_run(section),
        operators=_from_env_list("TALANTON_OPERATORS")
        or _addresses(section.get("operators"), "mail.outbound.operators"),
        allow_domains=(
            _from_env_list("TALANTON_ALLOW_DOMAINS")
            or _addresses(section.get("allow_domains"), "mail.outbound.allow_domains")
        ),
    )


def _dry_run(section: dict[str, Any]) -> bool:
    """Dry run defaults to on. Turning it off is a deliberate act, in one place."""
    override = os.environ.get("TALANTON_DRY_RUN")
    # An empty or blank variable is not somebody asking for live mail. Every
    # other secret in .env.example is written as an empty placeholder, so
    # `TALANTON_DRY_RUN=` is a plausible thing to end up with by accident, and
    # it used to be the line that started sending for real.
    if override is not None and override.strip():
        return override.strip().lower() not in ("0", "false", "no", "off")
    return bool(section.get("dry_run", Outbound.dry_run))


def _screening(data: dict[str, Any]) -> Screening:
    section = _section(data, "screening")
    return Screening(
        model=os.environ.get("TALANTON_MODEL") or str(section.get("model", Screening.model)),
        project=str(section.get("project", "")),
        location=str(section.get("location", "")),
        max_output_tokens=int(section.get("max_output_tokens", Screening.max_output_tokens)),
        service_account=str(os.environ.get("TALANTON_SERVICE_ACCOUNT") or section.get("service_account", "")),
        reply_within_days=int(section.get("reply_within_days", Screening.reply_within_days)),
        default_role=str(section.get("default_role", "")),
    )


def _location(data: dict[str, Any], name: str, default_path: str) -> LocationSpec:
    """Reads one [storage.<name>] section."""
    storage = _section(data, "storage")
    section = storage.get(name) or {}
    if not isinstance(section, dict):
        raise ConfigError(f"[storage.{name}] must be a table")

    backend_env = os.environ.get(f"TALANTON_{name.upper()}_BACKEND")
    path_env = os.environ.get(f"TALANTON_{name.upper()}_PATH")
    backend = str(backend_env or section.get("backend", "local"))
    return LocationSpec(
        configured=bool(name in storage or backend_env or path_env),
        backend=backend,
        path=str(path_env or section.get("path", default_path)),
        folder_id=str(section.get("folder_id", "")),
        folder=str(section.get("folder", "")),
        bucket=str(section.get("bucket", "")),
        prefix=str(section.get("prefix", "")),
    )


def _schedule(data: dict[str, Any]) -> Schedule:
    section = _section(data, "schedule")
    return Schedule(
        cron=str(os.environ.get("TALANTON_CRON") or section.get("cron", "")),
        idle_timeout_seconds=int(section.get("idle_timeout_seconds", Schedule.idle_timeout_seconds)),
    )


def parse(data: dict[str, Any], base: Path = Path()) -> Config:
    """Builds a Config from already-parsed TOML.

    Args:
        data: The parsed document.
        base: Directory relative store paths resolve against.

    Returns:
        Config: The frozen configuration.

    Raises:
        ConfigError: If a section is the wrong shape.
    """
    inbound = _inbound(data)
    store_section = _section(data, "store")
    store = os.environ.get("TALANTON_STORE") or store_section.get("path", "./data")
    return Config(
        store=(base / Path(str(store))).resolve(),
        cvs=_location(data, "cvs", default_path="cvs"),
        assessments=_location(data, "assessments", default_path="assessments"),
        openings=_location(data, "openings", default_path=PUBLISHED_DIR),
        company=_company(data),
        inbound=inbound,
        outbound=_outbound(data, inbound),
        screening=_screening(data),
        schedule=_schedule(data),
    )


def find(start: Path | None = None) -> Path | None:
    """Locates a config file: $TALANTON_CONFIG, else one in `start`."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    candidate = (start or Path.cwd()) / DEFAULT_CONFIG_NAME
    return candidate if candidate.exists() else None


def load(path: Path | str | None = None) -> Config:
    """Reads a config file. With no file anywhere, returns the defaults.

    Args:
        path: An explicit config file. Discovered if omitted.

    Returns:
        Config: The frozen configuration.

    Raises:
        ConfigError: If an explicitly named file does not exist or is malformed.
    """
    resolved = Path(path) if path else find()
    if resolved is None:
        return parse({})
    if not resolved.exists():
        raise ConfigError(f"no config file at {resolved}")
    try:
        data = tomllib.loads(resolved.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{resolved} is not valid TOML: {exc}") from exc
    return parse(data, base=resolved.parent)


# The model client reads these from the environment at call time. Putting them
# in the config file means nobody has to remember an export, and the project is
# named explicitly rather than inherited from whatever gcloud last pointed at.
VERTEX_ENV = (("GOOGLE_CLOUD_PROJECT", "project"), ("GOOGLE_CLOUD_LOCATION", "location"))
# Without this, a Gemini id routes to the Gemini Developer API and asks for an
# API key, ignoring the project entirely. Anthropic ids never needed it, which
# is why it only surfaced when the default model changed.
VERTEX_FLAG = "GOOGLE_GENAI_USE_VERTEXAI"


def apply_environment(config: "Config") -> list[str]:
    """Exports the configured Vertex project and region, if they are not
    already set. An explicit environment variable always wins.

    Returns:
        list[str]: The variables this call set, for reporting.
    """
    applied = []
    for variable, field_name in VERTEX_ENV:
        value = getattr(config.screening, field_name)
        if value and not os.environ.get(variable):
            os.environ[variable] = value
            applied.append(variable)

    if os.environ.get("GOOGLE_CLOUD_PROJECT") and not os.environ.get(VERTEX_FLAG):
        os.environ[VERTEX_FLAG] = "TRUE"
        applied.append(VERTEX_FLAG)
    return applied


def load_dotenv(path: Path | None = None) -> list[str]:
    """Reads a `.env` beside the config, for the secrets that cannot be in it.

    Deliberately small: `KEY=value` lines, `#` comments, optional quotes, and
    an existing environment variable is never overwritten. A real dependency
    for this would not earn its place.

    Returns:
        list[str]: The names it set.
    """
    target = Path(path) if path else Path.cwd() / ".env"
    if not target.exists():
        return []

    loaded = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and not os.environ.get(key):
            os.environ[key] = value
            loaded.append(key)
    return loaded


_current: Config | None = None


def current() -> Config:
    """The active configuration, loaded on first use."""
    global _current
    if _current is None:
        _current = load()
    return _current


def use(config: Config) -> None:
    """Installs a configuration. The entry point for a company repository."""
    global _current
    _current = config


def override(**changes: Any) -> Config:
    """Returns a copy of the active config with fields replaced. Never mutates."""
    return replace(current(), **changes)
