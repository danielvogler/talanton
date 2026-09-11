"""Every test gets its own locations, its own config, and no real mail."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from talanton import config, outbound, store

EXAMPLE = Path(__file__).resolve().parents[1] / "example"

OPENING = "101-ai-engineer"

POSITION = {
    "opening": 101,
    "id": "ai-engineer",
    "version": 1,
    "title": "AI Engineer",
    "location": "Zürich, CH",
    "pitch": "We build agentic systems that do real work.",
    "apply_to": "ai-engineer@example.com",
    "closes": "2026-11-30",
    "requirements": ["Production experience with LLM-based systems."],
    "knockouts": [{"id": "work_permit", "test": "Can work in the country the role is in."}],
    "rubric": [
        {"id": "production_experience", "weight": 100, "guide": "8 — has owned a system in production."}
    ],
    "screening": {"min_score": 5.0},
    "boards": {"linkedin": {"title_max": 200}},
}

FULL_FACTS = {
    "name": "unknown",
    "work_authorisation": "citizen",
    "language": "English fluent",
    "notice_period": "3 months",
    "years_industry": 8,
}


# load_dotenv writes straight to os.environ by design, so a test that exercises
# it would otherwise leak into every test after it.
TALANTON_ENV = (
    "TALANTON_INBOUND_PASSWORD",
    "TALANTON_OUTBOUND_PASSWORD",
    "TALANTON_INBOUND_SECRET",
    "TALANTON_OUTBOUND_SECRET",
    "EMAIL_PASSWORD",
    "EMAIL_USER",
    "TALANTON_CONFIG",
    "TALANTON_STORE",
    "TALANTON_OPERATORS",
    "TALANTON_ALLOW_DOMAINS",
    "TALANTON_DRY_RUN",
    "TALANTON_MODEL",
)


@pytest.fixture(autouse=True)
def clean_environment():
    """Every test starts and ends with the same environment."""
    import os

    before = {name: os.environ.get(name) for name in TALANTON_ENV}
    for name in TALANTON_ENV:
        os.environ.pop(name, None)
    yield
    for name, value in before.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, clean_environment):
    """A clean pair of locations, a clean config, and no SMTP."""
    config.use(
        replace(
            config.Config(),
            store=tmp_path,
            company=config.Company(name="Example Co", description="a test company"),
            inbound=config.Inbound(user="apply@example.com", password="x"),
            outbound=config.Outbound(
                user="hiring-bot@example.com",
                reply_to="apply@example.com",
                operators=("you@example.com",),
                dry_run=True,
            ),
        )
    )
    sent: list[dict] = []
    monkeypatch.setattr(
        outbound,
        "send",
        lambda to, subject, body: sent.append({"to": to, "subject": subject, "body": body}),
    )
    yield sent
    config.use(config.Config())


@pytest.fixture
def sent(isolated):
    return isolated


@pytest.fixture
def configure():
    """Replace fields on the active config. Returns the new one."""

    def _configure(**changes):
        updated = replace(config.current(), **changes)
        config.use(updated)
        return updated

    return _configure


@pytest.fixture
def position(tmp_path):
    """Writes a position file. Returns a callable to write more."""

    def _position(**overrides):
        data = {**POSITION, **overrides}
        directory = tmp_path / "openings"
        directory.mkdir(parents=True, exist_ok=True)
        slug = f"{data['opening']}-{data['id']}"
        (directory / f"{slug}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
        return data

    _position()
    return _position


@pytest.fixture
def cv():
    """Puts a CV in the CVs location. Returns its filename."""

    def _cv(name="anna-mueller.txt", text=None, opening=OPENING):
        body = text if text is not None else ("Ten years shipping production systems. " * 8)
        store.cvs(opening).write(name, body.encode("utf-8"))
        return name

    return _cv


@pytest.fixture
def assessed(cv):
    """Puts a CV in place and an assessment against it. Returns the id."""

    def _assessed(
        name="anna-mueller.txt",
        score=7.0,
        knockouts=None,
        facts=None,
        flags=None,
        justification="",
        opening=OPENING,
    ):
        cv(name, opening=opening)
        candidate = store.candidate_id(name)
        store.save_assessment(
            candidate,
            {
                "candidate": candidate,
                "cv": name,
                "cv_uri": f"https://drive.example.test/{candidate}",
                "opening": int(opening.split("-")[0]),
                "role": opening.split("-", 1)[1],
                "overall": score,
                "facts": {**FULL_FACTS, **(facts or {})},
                "knockouts": knockouts or {"work_permit": "pass"},
                "flags": flags or [],
                "justification": justification,
            },
            opening,
        )
        return candidate

    return _assessed
