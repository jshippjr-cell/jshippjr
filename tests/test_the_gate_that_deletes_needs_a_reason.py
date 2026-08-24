"""Sending a deliverable back told the creator less than sending a master back did.

Both presses are the same judgement, and ADR-0072 gave the MASTER's the treatment: a
`required` reason on the form, the whole note into the room's event stream, and an email
saying what to do next. The DELIVERABLE's — the mixer's stems, the editor's cutdowns —
was the weaker of the two in every way that matters, despite being the more destructive
of the two: a sent-back master stays where the composer left it, while this press calls
`forget_media`, which closes the disk copy *and* the durable mirror. The file is gone.

Measured against the master's, four gaps (operator, 2026-08-24):

1. **A blank reason went through.** The room asked via `window.prompt`, which returns
   ``""`` on a bare OK — so the file was destroyed and the creator emailed the words
   "No reason given." The console's per-asset gate was worse still: a bare "Send back"
   button posting the silent ``discard`` verb, with no note field anywhere on the form.
   The master's cannot do this; its reason is `required`.
2. **The reason was sliced at 200 characters** on its way into the event stream — a
   self-imposed cut, not a column limit — so the note the creator actually reads stopped
   mid-sentence with nothing to mark it. The master's has never truncated.
3. **The consequence was never stated.** The master's gate spells out what each press
   commits. This one was two icon buttons explained only by `title=`, which does not
   exist on a touch screen — and nothing anywhere said the file would be deleted.
4. **The email understated the ask.** "The lane is open for the replacement" reads like
   an edit is possible. There is nothing left to edit.
"""
import importlib

import pytest

pytest.importorskip("fastapi")

LONG = ("The low end is fighting the VO from about 0:14. " * 12).strip()   # >200 chars


@pytest.fixture()
def studio(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.models import MusicDiscipline
    from chordential_oia.talent import Talent
    from chordential_oia.web import app as app_mod, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    from chordential_oia.web.uploads import _persist_upload
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        pid = conn.execute("SELECT id FROM projects ORDER BY id LIMIT 1").fetchone()["id"]
        tid = db.insert_talent(conn, Talent(
            name="Rae Okonkwo", email="rae@example.com", rate=80.0,
            disciplines=[MusicDiscipline.MIXING]))
        db.add_assignment(conn, pid, "Mixer", tid)
        _persist_upload(conn, "stem-1.wav", b"RIFFfake", "audio/wav")
        db.update_delivery(conn, pid, "pending_assets", [{
            "label": "Instrumental / TV mix", "url": "/uploads/stem-1.wav",
            "filename": "stem-1.wav", "orig": "TVmix_(Instrumental).wav",
            "kind": "audio", "by": "Rae Okonkwo", "at": "2026-08-20"}])
    finally:
        conn.close()
    return c, app_mod, db, pid


def _press(c, pid, action="send_back", note=""):
    return c.post(f"/project/{pid}/delivery/asset/publish",
                  data={"filename": "stem-1.wav", "action": action,
                        "origin": "room", "note": note},
                  headers={"X-Requested-With": "fetch"})


def _still_waiting(db, pid):
    conn = db.connect()
    try:
        return [a.get("filename")
                for a in (db.get_delivery(conn, pid).get("pending_assets") or [])]
    finally:
        conn.close()


# ── 1. a destructive press may not fire on an empty reason ──────────────────────────
def test_a_blank_reason_does_not_destroy_the_file(studio):
    from chordential_oia.web.uploads import media_present
    c, _app, db, pid = studio
    r = _press(c, pid, note="")
    assert r.json()["ok"] is False
    assert r.json()["reason"] == "no_note"
    conn = db.connect()
    try:
        assert media_present(conn, "stem-1.wav"), (
            "the file was deleted on a press that carried no reason for deleting it")
    finally:
        conn.close()


def test_a_refused_press_leaves_the_file_waiting(studio):
    """Refusing must be a no-op, not a half-done send-back: the row has to still be
    there to press again once a reason is written."""
    c, _app, db, pid = studio
    _press(c, pid, note="   ")
    assert _still_waiting(db, pid) == ["stem-1.wav"]


def test_the_refusal_covers_the_legacy_verb_too(studio):
    """`discard` is the door the console was still pressing, with no note field at all."""
    c, _app, db, pid = studio
    assert _press(c, pid, action="discard", note="").json()["reason"] == "no_note"
    assert _still_waiting(db, pid) == ["stem-1.wav"]


def test_the_guard_is_on_the_server_not_only_the_markup(studio):
    """`required` in a template is honoured by a browser. This press deletes a file;
    the refusal has to hold for anything that can POST."""
    c, _app, db, pid = studio
    r = c.post(f"/project/{pid}/delivery/asset/publish",
               data={"filename": "stem-1.wav", "action": "send_back", "origin": "room"},
               headers={"X-Requested-With": "fetch"})           # note omitted entirely
    assert r.json()["ok"] is False
    assert _still_waiting(db, pid) == ["stem-1.wav"]


def test_a_real_reason_still_goes_through(studio):
    from chordential_oia.web.uploads import media_present
    c, _app, db, pid = studio
    assert _press(c, pid, note="Pull 200Hz.").json()["ok"] is True
    conn = db.connect()
    try:
        assert not media_present(conn, "stem-1.wav")
    finally:
        conn.close()
    assert _still_waiting(db, pid) == []


# ── 2. the whole note reaches the person it is addressed to ─────────────────────────
def test_the_reason_is_not_truncated_on_the_way_to_the_creator(studio):
    c, _app, db, pid = studio
    _press(c, pid, note=LONG)
    conn = db.connect()
    try:
        sent = [e for e in db.list_project_events(conn, pid, role="talent")
                if (e["kind"] or "") == "sent_back"]
    finally:
        conn.close()
    assert sent, "the creator's room was told nothing"
    body = sent[0]["body"] or ""
    assert LONG in body, (
        f"the direction was cut short at {len(body)} characters — the creator reads "
        "this and cannot see the end of the sentence")


def test_the_master_and_the_deliverable_agree_on_the_length_they_accept(studio):
    """600, taken where it is taken. The room and the console both cap the field there;
    the server clamps to the same number so a longer POST cannot smuggle past it."""
    c, _app, db, pid = studio
    _press(c, pid, note="x" * 900)
    conn = db.connect()
    try:
        sent = [e for e in db.list_project_events(conn, pid, role="talent")
                if (e["kind"] or "") == "sent_back"]
    finally:
        conn.close()
    assert "x" * 600 in (sent[0]["body"] or "")
    assert "x" * 601 not in (sent[0]["body"] or "")


# ── 3. what the press does, said before it is pressed ───────────────────────────────
def _tpl(app_mod, name):
    from pathlib import Path
    return (Path(app_mod.__file__).parent / "templates" / name).read_text(encoding="utf-8")


def _scripts(html):
    import re
    return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)


def _brace_depths(js):
    """Brace depth at every character, skipping strings and comments.

    Scope, measured. The check this replaces looked at INDENTATION and passed while a
    real browser reported both helpers `undefined` — column position is not scope, and
    this is the second time a helper has been declared somewhere its caller could not
    reach (the first was `formURL`)."""
    out, depth, i, n = [], 0, 0, len(js)
    while i < n:
        ch = js[i]
        nxt = js[i + 1] if i + 1 < n else ""
        if ch in "\"'`":
            out.append(depth)
            i += 1
            while i < n and js[i] != ch:
                i += 2 if js[i] == "\\" else 1
                out.append(depth)
            out.append(depth)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and js[i] != "\n":
                out.append(depth)
                i += 1
            continue
        if ch == "/" and nxt == "*":
            end = js.find("*/", i + 2)
            end = n if end == -1 else end + 2
            out.extend([depth] * (end - i))
            i = end
            continue
        if ch == "{":
            out.append(depth)
            depth += 1
        elif ch == "}":
            depth -= 1
            out.append(depth)
        else:
            out.append(depth)
        i += 1
    return out


def test_the_room_states_that_the_file_is_deleted(studio):
    _c, app_mod, _db, _pid = studio
    tpl = _tpl(app_mod, "creator_portal.html")
    assert "window.prompt(" not in tpl.split("askWhy")[-1][:1500], (
        "the reason is still asked for in a browser dialog — no length, unreadable once "
        "dismissed, suppressed entirely on some mobile browsers")
    assert "removes it from the server" in tpl, (
        "nothing tells the studio that sending a deliverable back destroys the file")
    assert "no revision round is spent" in tpl


def test_the_gate_helper_is_reachable_from_the_handler_that_calls_it(studio):
    """`askWhy` and `runGate` must be hoisted into the SAME scope as the `form.lf-gate`
    binding — the mistake `formURL` made, where the function existed but the handler
    that needed it could not see it.

    Asserted as scope, not as indentation. The first version of this test checked for a
    two-space indent and passed while a browser reported both helpers `undefined`; the
    page's whole script lives in an IIFE, so column position says nothing about what can
    reach what."""
    _c, app_mod, _db, _pid = studio
    tpl = _tpl(app_mod, "creator_portal.html")
    script = max(_scripts(tpl), key=lambda s: s.count("lf-gate"))
    depth = _brace_depths(script)
    where = {}
    for probe in ("function askWhy(", "function runGate(",
                  'querySelectorAll("form.lf-gate")'):
        at = script.find(probe)
        assert at != -1, f"{probe} is gone from the script that binds the gate"
        where[probe] = depth[at]
    binding = where['querySelectorAll("form.lf-gate")']
    for probe in ("function askWhy(", "function runGate("):
        assert where[probe] == binding, (
            f"{probe} is nested {where[probe] - binding} level(s) deeper than the "
            "handler that calls it — it will be `undefined` there")


def test_the_console_gate_has_a_reason_field(studio):
    """The console's per-asset gate was a bare button posting `discard`, with nowhere
    on the form to say why — ten lines below the master's gate, which requires one."""
    _c, app_mod, _db, _pid = studio
    tpl = _tpl(app_mod, "delivery_console.html")
    gate = tpl.split("pending_assets or []")[1].split("{% endfor %}")[0]
    assert 'value="send_back"' in gate and 'value="discard"' not in gate
    assert 'name="note"' in gate and "required" in gate


# ── 4. the email asks for what is actually needed ───────────────────────────────────
def test_the_creator_is_told_the_file_is_gone_and_to_re_upload(studio, monkeypatch):
    from chordential_oia.web import project_routes
    sent = []
    monkeypatch.setattr(project_routes.signals, "fire_and_forget",
                        lambda fn, *a, **kw: sent.append(kw))
    c, _app, _db, pid = studio
    _press(c, pid, note="Pull 200Hz.")
    bodies = [s.get("body_text", "") for s in sent]
    assert bodies, "nobody was emailed"
    body = bodies[0]
    assert "Pull 200Hz." in body
    assert "taken off the server" in body, (
        "the email implies the file is still there to revise; it is not")
    assert "fresh upload" in body


def test_it_still_goes_to_the_owner_of_that_lane_only(studio, monkeypatch):
    """ADR-0075 — the mixer's stems go back to the mixer. Guarded here because the
    refusal added an early return above the code that resolves the owner."""
    from chordential_oia.web import project_routes
    sent = []
    monkeypatch.setattr(project_routes.signals, "fire_and_forget",
                        lambda fn, *a, **kw: sent.append(kw))
    c, _app, _db, pid = studio
    _press(c, pid, note="Pull 200Hz.")
    assert [s.get("only_craft") for s in sent] == ["mixer"]
