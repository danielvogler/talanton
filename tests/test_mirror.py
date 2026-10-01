"""One file per opening that mirrors its assessments, so a shortlist is one read.

The mirror is a cache, never the record. Every row carries the version of the
file it was read from; a row whose file changed, vanished or was never
mirrored is read again, so a lost or stale mirror costs reads and never a
wrong answer.
"""

import json

from talanton import cli, store, tools
from tests.conftest import OPENING, picks
from tests.roundtrips import counted
from tests.test_round_trip_budget import build_pool


def test_once_mirrored_the_pool_is_one_read(position, monkeypatch):
    build_pool(30)
    store.load_assessments(OPENING)
    tally = counted(monkeypatch)
    tally.reset()
    pool = store.load_assessments(OPENING)
    assert len(pool) == 30
    assert tally.reads == 1, tally
    assert tally.writes == 0, tally


def test_a_changed_assessment_is_read_again(position):
    ids = build_pool(5)
    first = store.load_assessments(OPENING)
    store.save_assessment(ids[0], {**first[ids[0]], "overall": 9.5}, OPENING)
    assert store.load_assessments(OPENING)[ids[0]]["overall"] == 9.5


def test_a_removed_assessment_leaves_the_mirror(position):
    ids = build_pool(3)
    store.load_assessments(OPENING)
    store.assessments(OPENING).path.joinpath(store.assessment_name(ids[0])).unlink()
    assert ids[0] not in store.load_assessments(OPENING)


def test_a_damaged_mirror_is_rebuilt_not_fatal(position):
    build_pool(3)
    store.assessments(OPENING).write(store.ASSESSMENT_MIRROR, b"{not json")
    assert len(store.load_assessments(OPENING)) == 3


def test_a_row_lost_to_another_writer_comes_back(position):
    """Two runs writing the mirror at once: the later one wins, and whatever
    the earlier one added is missing. The next read puts it back."""
    ids = build_pool(4)
    store.load_assessments(OPENING)
    location = store.assessments(OPENING)
    mirror = json.loads(location.path.joinpath(store.ASSESSMENT_MIRROR).read_bytes())
    del mirror["rows"][store.assessment_name(ids[0])]
    location.write(store.ASSESSMENT_MIRROR, json.dumps(mirror).encode())
    assert ids[0] in store.load_assessments(OPENING)


def test_the_mirror_is_neither_an_assessment_nor_a_cv(position):
    build_pool(2)
    store.load_assessments(OPENING)
    assert store.ASSESSMENT_MIRROR not in {store.assessment_name(c) for c in store.load_assessments(OPENING)}
    assert len(store.assessed_ids(OPENING)) == 2
    assert not store.is_cv(store.ASSESSMENT_MIRROR)


def test_arrivals_are_mirrored_too(position, monkeypatch):
    ids = build_pool(10)
    for candidate in ids:
        store.write_provenance(candidate, {"arrived": "2026-09-14", "via": "mailbox"}, OPENING)
    store.provenances(OPENING)
    tally = counted(monkeypatch)
    tally.reset()
    records = store.provenances_for(set(ids[:3]), OPENING)
    assert set(records) == set(ids[:3])
    assert tally.reads == 1, tally


def test_refresh_reports_what_it_read(position):
    build_pool(4)
    assert store.refresh(OPENING) == {"assessments": 4, "arrivals": 0}
    assert store.refresh(OPENING) == {"assessments": 4, "arrivals": 0}


def test_the_index_command_builds_the_mirror(position, capsys):
    build_pool(3)
    assert cli.main(["index", OPENING]) == 0
    assert "3 assessment(s)" in capsys.readouterr().out
    assert store.assessments(OPENING).path.joinpath(store.ASSESSMENT_MIRROR).exists()


def test_resend_sends_the_last_shortlist_again(configure, assessed, position, sent, capsys):
    from talanton import config

    configure(outbound=config.Outbound(user="bot@example.com", operators=("you@example.com",), dry_run=False))
    cid = assessed()
    tools.send_digest(OPENING, "Worth a look.", picks(cid, why="owned retrieval"))
    sent.clear()
    assert cli.main(["resend", OPENING]) == 0
    assert len(sent) == 1
    assert "owned retrieval" in sent[0]["body"]
    assert f"https://drive.example.test/{cid}" in sent[0]["body"]


def test_resend_with_nothing_sent_yet_says_so(position, sent, capsys):
    assert cli.main(["resend", OPENING]) != 0
    assert sent == []
