"""talanton — an agentic hiring pipeline.

A company installs this package, writes one `talanton.toml`, and points it
at a private store:

    from talanton import config, run
    config.use(config.load("talanton.toml"))
    run.cycle("101")

The agents are built lazily, on first access, so `config.use` still has effect
when it is called before them. ADK finds `root_agent` here for `adk run
talanton` and `adk web`.
"""

from typing import Any

from .config import Config, load, use

__all__ = [
    "Config",
    "app",
    "assessor",
    "assessor_app",
    "correspondent",
    "load",
    "root_agent",
    "screener",
    "use",
]

_LAZY = {"root_agent", "screener", "correspondent", "assessor", "app", "assessor_app"}


def __getattr__(name: str) -> Any:
    """Builds the agents on first access, never at import time.

    Importing this package must not read the configuration — otherwise a
    company repository could never install its own before the agents exist.
    """
    if name in _LAZY:
        from . import agent

        return getattr(agent, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
