"""A Location that counts what it costs.

Every slowdown reported so far is the same shape: an operation whose cost
scales with the size of the pool rather than the size of the question, built
out of `list()` plus `read()` because the protocol offers nothing in between.

They are invisible where they are written. `load_assessments()` reads like a
dictionary lookup and is one HTTP request per assessment; `LocalLocation.read`
is a file read costing nothing, so the tests and a laptop never pay and only
an operator with a live Drive folder does.

This makes the cost visible to the tests. It is a dict with a tally: no
network, no credentials, and `LocationError` behaviour unchanged.
"""

from dataclasses import dataclass, field

from talanton import locations


@dataclass
class Tally:
    """How many round trips a block of work cost."""

    lists: int = 0
    reads: int = 0
    writes: int = 0
    by_location: dict[str, int] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.lists} list(s), {self.reads} read(s), {self.writes} write(s)"

    def reset(self) -> None:
        """Forgets what came before, so setup is not counted as work."""
        self.lists = self.reads = self.writes = 0
        self.by_location.clear()

    def snapshot(self) -> "Tally":
        return Tally(self.lists, self.reads, self.writes, dict(self.by_location))


class CountingLocation:
    """Wraps a real location and records every round trip through it."""

    def __init__(self, inner, tally: Tally) -> None:
        self._inner = inner
        self._tally = tally
        self.backend = inner.backend

    def list(self):
        self._tally.lists += 1
        key = repr(self._inner)
        self._tally.by_location[key] = self._tally.by_location.get(key, 0) + 1
        return self._inner.list()

    def read(self, item):
        self._tally.reads += 1
        return self._inner.read(item)

    def write(self, filename, payload):
        self._tally.writes += 1
        return self._inner.write(filename, payload)

    def child(self, name):
        return CountingLocation(self._inner.child(name), self._tally)

    def verify(self) -> None:
        self._inner.verify()

    def __repr__(self) -> str:
        return f"counting:{self._inner!r}"


def counted(monkeypatch) -> Tally:
    """Counts every round trip any location makes from here on.

    Wraps `locations.build`, which is the one place a location is constructed,
    so this reaches the CVs location and the assessments location alike without
    either caller knowing.
    """
    tally = Tally()
    # The real one, never a wrapper: installing this twice in a test would
    # otherwise count every round trip once per installation.
    original = getattr(locations.build, "__wrapped_build__", locations.build)

    def _build(spec, base):
        return CountingLocation(original(spec, base), tally)

    _build.__wrapped_build__ = original  # type: ignore[attr-defined]
    monkeypatch.setattr(locations, "build", _build)
    return tally
