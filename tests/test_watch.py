"""The unattended loop. It runs for weeks, so what it leaks matters."""

import pytest

from talanton import inbound, run


class FakeSession:
    """An IMAP session that records whether it was closed."""

    def __init__(self, fail_on: str = "") -> None:
        self.fail_on = fail_on
        self.logged_out = False

    def _maybe_fail(self, step: str) -> None:
        if self.fail_on == step:
            raise OSError(f"the connection dropped during {step}")

    def select_folder(self, name):
        self._maybe_fail("select_folder")

    def idle(self):
        self._maybe_fail("idle")

    def idle_check(self, timeout):
        self._maybe_fail("idle_check")
        return []

    def idle_done(self):
        self._maybe_fail("idle_done")

    def logout(self):
        self.logged_out = True


class StopWatchingError(Exception):
    """Breaks out of watch's deliberately infinite loop."""


@pytest.mark.parametrize("fail_on", ["", "select_folder", "idle", "idle_check", "idle_done"])
def test_the_watch_loop_always_closes_its_imap_session(monkeypatch, fail_on):
    """Gmail counts simultaneous IMAP connections. A session dropped without a
    logout on every transient failure eventually exhausts them."""
    sessions: list[FakeSession] = []
    passes: list[str] = []

    def fake_client():
        sessions.append(FakeSession(fail_on))
        return sessions[-1]

    def fake_cycle(role):
        passes.append(role)
        if len(passes) > 1:
            raise StopWatchingError
        return {}

    def stop_sleeping(seconds):
        raise StopWatchingError

    monkeypatch.setattr(inbound, "client", fake_client)
    monkeypatch.setattr(run, "cycle", fake_cycle)
    monkeypatch.setattr(run.time, "sleep", stop_sleeping)

    with pytest.raises(StopWatchingError):
        run.watch("101")

    assert sessions, "the loop never opened a session"
    assert all(s.logged_out for s in sessions), f"a session was dropped unclosed after {fail_on!r}"
