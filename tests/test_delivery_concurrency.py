"""Two writers, both told they succeeded, one change gone.

`delivery_json` is a per-project JSON blob and merging one key into it was a
read-modify-write in Python: read the whole document, set one key, write the whole
document back. Two writers overlapping in that window and the later write carries a
document read BEFORE the earlier one, so the earlier change is erased. Nothing raises.
Both callers are told they succeeded.

Reproduced with two threads doing what the product actually does — a client approving
an asset in the review portal while the operator publishes a version in the console:

    keys that survived : ['versions']
    client's approval  : LOST
    operator's version : kept

That is not an exotic interleaving. Publishing a version fires several
`update_delivery` calls in a row, and the review portal is open on someone else's
screen the entire time.

The fix is not a lock around the read-modify-write — it is to stop doing one. Both
backends merge a key into a JSON document in a single statement, and a single
statement cannot interleave with itself.

**Why not promote `versions` and `asset_approvals` to tables**, which is what the
launch review proposed: it would fix those two keys and leave `state`, `license`,
`cues`, `pending_version` and `delivery_zip` racing exactly as before — and two of
those decide what a client is looking at. The one-statement merge protects every key,
including ones not written yet.
"""

import importlib
import json
import threading
import time

import pytest

from chordential_oia.web import db as db_mod


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.execute("INSERT INTO projects (client, need) VALUES ('Acme', 'Anthem')")
    conn.commit()
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    conn.close()
    return pid


def _concurrently(pid, work):
    def writer(key, value, delay):
        conn = db_mod.connect()
        time.sleep(delay)
        db_mod.update_delivery(conn, pid, key, value)
        conn.close()
    threads = [threading.Thread(target=writer, args=w) for w in work]
    for t in threads: t.start()
    for t in threads: t.join(timeout=30)
    conn = db_mod.connect()
    out = db_mod.get_delivery(conn, pid)
    conn.close()
    return out


def test_a_client_approval_survives_a_simultaneous_publish(project):
    """The exact pair that lost data: the client approves in the portal while the
    operator publishes a version in the console.

    Run in ROUNDS behind a barrier, not once with a sleep. A single timed pair passes
    on the broken implementation whenever the interleaving happens not to occur — and
    a race test that passes intermittently on broken code is worse than no test,
    because it is read as evidence. The barrier makes both writers arrive together and
    the rounds make "it didn't happen this time" not a way out.
    """
    ROUNDS = 25
    losses = []
    for r in range(ROUNDS):
        approval_key, version_key = f"asset_approvals_{r}", f"versions_{r}"
        start = threading.Barrier(2)

        def writer(key, value):
            conn = db_mod.connect()
            start.wait(timeout=10)               # arrive together, every round
            db_mod.update_delivery(conn, project, key, value)
            conn.close()

        ts = [threading.Thread(target=writer,
                               args=(approval_key, {"m01": {"by": "Priya"}})),
              threading.Thread(target=writer,
                               args=(version_key, [{"n": r, "label": "FINAL"}]))]
        for t in ts: t.start()
        for t in ts: t.join(timeout=30)

        conn = db_mod.connect()
        got = db_mod.get_delivery(conn, project)
        conn.close()
        if approval_key not in got:
            losses.append(f"round {r}: the client's approval was erased by the publish")
        elif version_key not in got:
            losses.append(f"round {r}: the operator's version was erased by the approval")
        elif got[approval_key]["m01"]["by"] != "Priya":
            losses.append(f"round {r}: the approval was corrupted")
    assert losses == [], f"{len(losses)}/{ROUNDS} rounds lost a write:\n  " + \
                         "\n  ".join(losses[:5])


def test_every_key_survives_a_pile_up(project):
    """Publishing fires several merges in a row while other surfaces write too. Each
    key here is written by a different real code path."""
    work = [("asset_approvals", {"m01": "Approved"}, 0.00),
            ("versions", [{"n": 4}], 0.02),
            ("state", "In review", 0.01),
            ("license", {"type": "Full buyout"}, 0.03),
            ("pending_version", {"filename": "p-1.mp3"}, 0.02),
            ("delivery_zip", {"filename": "pkg.zip"}, 0.01)]
    final = _concurrently(project, work)
    lost = [k for k, _, _ in work if k not in final]
    assert lost == [], f"lost under concurrency: {lost}"


def test_the_merge_preserves_every_json_shape(project):
    """A blob holds lists, dicts, strings, numbers and booleans. A merge that
    stringified any of them would corrupt the ladder rather than lose it."""
    conn = db_mod.connect()
    shapes = {"versions": [{"n": 1}, {"n": 2}], "state": "Delivered",
              "revisions_used": 2, "license_confirmed": True,
              "license": {"type": "Full buyout", "term": None}}
    for k, v in shapes.items():
        db_mod.update_delivery(conn, project, k, v)
    got = db_mod.get_delivery(conn, project)
    conn.close()
    for k, v in shapes.items():
        assert got[k] == v, f"{k}: {got.get(k)!r} != {v!r}"


def test_none_removes_a_key_and_the_rest_stay(project):
    """`update_delivery(..., None)` is how a version is dropped and how the pending
    submission is consumed. It must remove that key ONLY."""
    conn = db_mod.connect()
    db_mod.update_delivery(conn, project, "versions", [{"n": 1}])
    db_mod.update_delivery(conn, project, "state", "In review")
    db_mod.update_delivery(conn, project, "versions", None)
    got = db_mod.get_delivery(conn, project)
    conn.close()
    assert "versions" not in got
    assert got["state"] == "In review"


def test_an_empty_string_sets_rather_than_removes(project):
    """`_publish_pending_submission` clears the pending slot with `""`, not None, and
    other code distinguishes "present and empty" from "absent"."""
    conn = db_mod.connect()
    db_mod.update_delivery(conn, project, "pending_version", {"filename": "x.mp3"})
    db_mod.update_delivery(conn, project, "pending_version", "")
    got = db_mod.get_delivery(conn, project)
    conn.close()
    assert "pending_version" in got and got["pending_version"] == ""


def test_a_column_holding_junk_still_merges(project):
    """Both engines refuse to merge into something that is not JSON, where the old
    read-modify-write silently reset it. A row that is already broken must not become
    a 500 on a client's page."""
    conn = db_mod.connect()
    conn.execute("UPDATE projects SET delivery_json = ? WHERE id = ?",
                 ("not json at all", project))
    conn.commit()
    db_mod.update_delivery(conn, project, "state", "In review")
    got = db_mod.get_delivery(conn, project)
    conn.close()
    assert got == {"state": "In review"}


def test_a_missing_row_is_not_an_error(project):
    """Called for a project that has since been deleted — best-effort, as before."""
    conn = db_mod.connect()
    db_mod.update_delivery(conn, 999999, "state", "In review")
    conn.close()


def test_a_hostile_key_is_refused_not_interpolated(project):
    """The key is interpolated into a JSON path, so it is validated rather than
    trusted. Every real key is an identifier; anything else is a bug or an attack."""
    conn = db_mod.connect()
    with pytest.raises(ValueError):
        db_mod.update_delivery(conn, project, 'a"]) OR 1=1--', "x")
    conn.close()


def test_the_client_document_overrides_are_fixed_too(project):
    """`doc_overrides` had the identical read-modify-write, on the document the CLIENT
    reads, edited field by field — the shape most likely to be written concurrently."""
    conn = db_mod.connect()
    conn.execute("INSERT INTO opportunities (client, need) VALUES ('Acme', 'Anthem')")
    conn.commit()
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    conn.close()

    def writer(key, value, delay):
        c = db_mod.connect()
        time.sleep(delay)
        db_mod.update_doc_override(c, oid, key, value)
        c.close()

    work = [("headline", "A warm holiday anthem", 0.00),
            ("scope", "One :60 plus cutdowns", 0.02),
            ("terms", "Net 30", 0.01)]
    ts = [threading.Thread(target=writer, args=w) for w in work]
    for t in ts: t.start()
    for t in ts: t.join(timeout=30)

    conn = db_mod.connect()
    got = db_mod.get_doc_overrides(conn, oid)
    conn.close()
    assert sorted(got) == ["headline", "scope", "terms"], got


def test_a_blank_override_still_resets_to_generated(project):
    """A blank value means "reset this field to the generated default", which is a
    REMOVAL, not an empty string — the opposite of the delivery blob's convention."""
    conn = db_mod.connect()
    conn.execute("INSERT INTO opportunities (client, need) VALUES ('Acme', 'Anthem')")
    conn.commit()
    oid = conn.execute("SELECT id FROM opportunities LIMIT 1").fetchone()["id"]
    db_mod.update_doc_override(conn, oid, "headline", "Written by hand")
    db_mod.update_doc_override(conn, oid, "headline", "   ")
    got = db_mod.get_doc_overrides(conn, oid)
    conn.close()
    assert "headline" not in got, "a blank must reset to generated, not store whitespace"
