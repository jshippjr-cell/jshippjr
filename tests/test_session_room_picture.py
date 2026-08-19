"""Phase 2 — The Picture: the client's cut dresses the composer's room; references
are hearable; a new cut is a conform event; rooms sort needs-first with per-room
doors (?p, ADR-0025); purged demo talent never orphans live assignments."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c, db_mod, app_mod


def _composer_with_project(db_mod):
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    conn = db_mod.connect()
    tid = db_mod.insert_talent(conn, Talent(
        name="Devin Test", email="devin@example.com", credits="c",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED,
        rate=90.0))
    db_mod.set_talent_agreement(conn, tid, "2026-07-18", "test")
    pid = db_mod.insert_project(
        conn, opp_id=None, client="Acme", need="Brand spot", budget_min=4000,
        budget_max=8000, deadline="2026-08-10", roles=["Composer"])
    db_mod.add_assignment(conn, pid, "Composer", tid)
    tok = db_mod.ensure_talent_portal_token(conn, tid)
    share = db_mod.ensure_project_share_token(conn, pid)
    conn.close()
    return tid, pid, tok, share


def test_client_uploads_cut_and_room_carries_it(ctx):
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    r = client.post(f"/project/{pid}/review/picture",
                    data={"k": share, "author": "Dana"},
                    files={"file": ("cut_v1.mp4", b"\x00\x00\x00 ftypmp42fakevideo", "video/mp4")},
                    follow_redirects=False)
    assert r.status_code == 303
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    pic = d.get("picture")
    assert pic and pic["n"] == 1 and pic["orig"] == "cut_v1.mp4"
    page = client.get(f"/creator/{tok}").text
    assert "sr-video" in page and pic["url"] in page
    assert "CUT 1" in page


def test_second_cut_is_a_conform_event(ctx):
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    for name in ("cut_v1.mp4", "cut_v2.mp4"):
        client.post(f"/project/{pid}/review/picture",
                    data={"k": share, "author": "Dana"},
                    files={"file": (name, b"fakevideo-bytes", "video/mp4")},
                    follow_redirects=False)
    # ADR-0069: a second cut is PARKED, not swapped. Replacing the picture under
    # everyone's notes left each pin at its old second while the ground moved, so the
    # room holds the cut the notes were written against until a human states the shift.
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert d["picture"]["n"] == 1, "the picture was swapped under the existing notes"
    assert (d.get("conform_pending") or {}).get("n") == 2
    assert len(d.get("picture_history") or []) == 1
    page = client.get(f"/creator/{tok}").text
    assert "not conformed yet" in page.replace("\n      ", " ")

    # Once the studio conforms it, the new cut loads and the banner is the classic one.
    client.post("/admin/login", data={"email": "", "password": "passphrase"},
                follow_redirects=False)
    client.post(f"/project/{pid}/conform", data={"offset": "0", "action": "apply"},
                follow_redirects=False)
    conn = db_mod.connect(); d2 = db_mod.get_delivery(conn, pid); conn.close()
    assert d2["picture"]["n"] == 2 and not d2.get("conform_pending")
    page2 = client.get(f"/creator/{tok}").text
    assert "Picture changed" in page2          # the conform banner
    # the money fact stated outright (composer review P1): conforms are free
    assert "doesn't count against" in page2 and "conform" in page2


def test_non_video_rejected_as_picture(ctx):
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    client.post(f"/project/{pid}/review/picture",
                data={"k": share, "author": "Dana"},
                files={"file": ("notavideo.pdf", b"%PDF-fake", "application/pdf")},
                follow_redirects=False)
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert not d.get("picture")


def test_reference_lands_hearable_in_the_room(ctx):
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    r = client.post(f"/project/{pid}/review/reference",
                    data={"k": share, "author": "Dana", "label": "the Bonobo track, 1:10-1:40"},
                    files={"file": ("ref.mp3", b"ID3fakeaudio", "audio/mpeg")},
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/creator/{tok}").text
    assert "the Bonobo track, 1:10-1:40" in page
    assert "sr-ref-play" in page              # playable, not just named
    assert "hear them, don" in page           # the references section header


def test_room_door_filter_and_needs_first_sort(ctx):
    client, db_mod, _ = ctx
    from chordential_oia.talent import InviteStatus, ReviewStatus, Talent
    tid, pid1, tok, _ = _composer_with_project(db_mod)
    conn = db_mod.connect()
    pid2 = db_mod.insert_project(
        conn, opp_id=None, client="Beta", need="Game theme", budget_min=2000,
        budget_max=4000, deadline="2026-09-01", roles=["Composer"])
    db_mod.add_assignment(conn, pid2, "Composer", tid)
    # room 1 becomes delivered → it must sink below the room that needs work
    db_mod.update_delivery(conn, pid1, "state", "Released")
    conn.close()
    page = client.get(f"/creator/{tok}").text
    assert page.index(f'id="p{pid2}"') < page.index(f'id="p{pid1}"')
    # ?p opens one door only
    solo = client.get(f"/creator/{tok}?p={pid2}").text
    assert f'id="p{pid2}"' in solo and f'id="p{pid1}"' not in solo
    assert "All rooms" in solo


def test_species_toggle_conform_shows_free_in_room(ctx):
    """The operator flips a change request to CONFORM; the composer's room says
    per-note that it's free (EP P1) — and the toggle is project-scoped."""
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    conn = db_mod.connect()
    cid = db_mod.add_review_comment(
        conn, pid, version="0", t_seconds=12.0, author="Dana",
        body="Hit the logo harder", kind="change_request")
    conn.close()
    page = client.get(f"/creator/{tok}").text
    assert "conform · free" not in page       # a revision until Jon says otherwise
    r = client.post(f"/project/{pid}/review/note/{cid}/species",
                    follow_redirects=False)
    assert r.status_code == 303
    page = client.get(f"/creator/{tok}").text
    assert "conform · free" in page
    # scoping: toggling through the WRONG project id must not touch the note
    client.post(f"/project/{pid + 999}/review/note/{cid}/species",
                follow_redirects=False)
    conn = db_mod.connect()
    row = conn.execute("SELECT COALESCE(conform,0) AS cf FROM review_comments "
                       "WHERE id=?", (cid,)).fetchone()
    conn.close()
    assert row["cf"] == 1                     # unchanged by the cross-project poke


def test_uploads_nonmedia_served_as_attachment(ctx):
    """Stored-XSS lane (eng P0): /uploads renders only audio/video/image inline;
    markup downloads as an attachment with nosniff, and svg is never inline."""
    import os as _os
    client, db_mod, app_mod = ctx
    updir = app_mod.UPLOAD_DIR
    _os.makedirs(updir, exist_ok=True)
    for name, body in (("evil.html", b"<script>alert(1)</script>"),
                       ("evil.svg", b"<svg onload=alert(1)></svg>"),
                       ("take.mp3", b"ID3fakeaudio")):
        with open(_os.path.join(updir, name), "wb") as fh:
            fh.write(body)
    for name in ("evil.html", "evil.svg"):
        r = client.get(f"/uploads/{name}")
        assert r.status_code == 200
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert "attachment" in (r.headers.get("content-disposition") or "")
        assert r.headers["content-type"].startswith("application/octet-stream")
    r = client.get("/uploads/take.mp3")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert "attachment" not in (r.headers.get("content-disposition") or "")
    assert r.headers["content-type"].startswith("audio/")


def test_cut_over_cap_rejected(ctx, monkeypatch):
    client, db_mod, app_mod = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    # Patched on `web.project_routes`, not on `app`: ADR-0044 moved the /project
    # routes and this cap out together, and a route reads its own module globals.
    from chordential_oia.web import project_routes
    monkeypatch.setattr(project_routes, "_CUT_MAX_BYTES", 10)
    client.post(f"/project/{pid}/review/picture",
                data={"k": share, "author": "Dana"},
                files={"file": ("big.mp4", b"x" * 64, "video/mp4")},
                follow_redirects=False)
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert not d.get("picture")


def test_conform_returns_the_round_everywhere(ctx):
    """The core promise (EP P0): a change request burns a round; classifying it a
    conform RETURNS that round, and the composer room shows the round sentence from
    the SAME counter (not a phantom field that was never written)."""
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    # baseline: no rounds used, composer room shows Round 1 of 2 (scoped defaults to 2)
    page = client.get(f"/creator/{tok}").text
    assert "Round 1 of 2" in page
    # client requests changes → a round is consumed
    client.post(f"/project/{pid}/review/changes",
                data={"k": share, "author": "Dana", "email": "d@x.example",
                      "note": "Resync the tail to the recut ending"},
                follow_redirects=False)
    conn = db_mod.connect()
    d = db_mod.get_delivery(conn, pid)
    cid = conn.execute("SELECT id FROM review_comments WHERE project_id=? AND "
                       "kind='change_request' ORDER BY id DESC LIMIT 1", (pid,)).fetchone()[0]
    conn.close()
    assert int(d.get("revisions_used") or 0) == 1
    assert "Round 2 of 2" in client.get(f"/creator/{tok}").text
    # operator classifies it a conform → the round comes back, room reflects it
    client.post(f"/project/{pid}/review/note/{cid}/species", follow_redirects=False)
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert int(d.get("revisions_used") or 0) == 0        # round returned, not cosmetic
    page = client.get(f"/creator/{tok}").text
    assert "Round 1 of 2" in page and "conform · free" in page


def test_creator_submission_over_cap_rejected(ctx, monkeypatch):
    """A composer's take/deliverable upload is token-gated (no admin auth) — an
    oversized body must be refused via the chunked cap, never buffered whole
    (eng re-verify P1)."""
    client, db_mod, app_mod = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    # Patched on `web.creator_routes`: ADR-0044 moved the /creator routes and this
    # cap out together, and a route reads its own module globals.
    from chordential_oia.web import creator_routes
    monkeypatch.setattr(creator_routes, "_SUBMISSION_MAX_BYTES", 10)
    r = client.post(f"/creator/{tok}/project/{pid}/version",
                    files={"file": ("take.mp3", b"x" * 64, "audio/mpeg")},
                    follow_redirects=False)
    assert r.status_code == 303                # bounced, nothing stored
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert not (d.get("pending") or d.get("versions"))
    r = client.post(f"/creator/{tok}/project/{pid}/deliverable",
                    data={"label": "stems"},
                    headers={"X-Requested-With": "fetch"},
                    files={"file": ("stems.wav", b"x" * 64, "audio/wav")},
                    follow_redirects=False)
    assert r.status_code == 400                # XHR path returns a hard error
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert not (d.get("pending_assets") or [])


def test_blocked_reference_extension_rejected(ctx):
    client, db_mod, _ = ctx
    tid, pid, tok, share = _composer_with_project(db_mod)
    client.post(f"/project/{pid}/review/reference",
                data={"k": share, "author": "Dana", "label": "sneaky"},
                files={"file": ("evil.html", b"<script>1</script>", "text/html")},
                follow_redirects=False)
    conn = db_mod.connect(); d = db_mod.get_delivery(conn, pid); conn.close()
    assert not (d.get("references") or [])


def test_purge_never_orphans_assigned_talent(ctx):
    _, db_mod, app_mod = ctx
    from chordential_oia.web import seed as seed_mod
    tid, pid, tok, _ = _composer_with_project(db_mod)
    conn = db_mod.connect()
    # the composer is demo-sourced (not an applicant) but has a live assignment
    conn.execute("UPDATE talent SET source='demo_delivery' WHERE id=?", (tid,))
    conn.commit()
    seed_mod.purge_demo_data(conn)
    row = conn.execute("SELECT id FROM talent WHERE id=?", (tid,)).fetchone()
    orphans = conn.execute(
        "SELECT COUNT(*) FROM assignments a LEFT JOIN talent t ON t.id=a.talent_id "
        "WHERE a.talent_id IS NOT NULL AND t.id IS NULL").fetchone()[0]
    conn.close()
    assert row is not None                    # assigned talent survives the purge
    assert orphans == 0
