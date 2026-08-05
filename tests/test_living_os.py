"""The Living-OS layer (bible: "Living OS principle"): every page carries at
least one living element that can't exist in print, implemented honestly —
the machine beacon breathes only when the autonomous engines are actually on,
and live.js is a progressive enhancement every page loads."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_ADMIN_TOKEN", raising=False)
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    with TestClient(app_mod.app) as c:
        yield c


def test_live_js_is_served_and_loaded_on_every_app_page(client):
    assert client.get("/static/live.js").status_code == 200
    page = client.get("/dashboard").text
    assert "/static/live.js" in page


def test_machine_beacon_is_honest_about_engine_state(client, monkeypatch):
    # engines off (default in tests) → the beacon must NOT claim the machine runs
    monkeypatch.delenv("CHORDENTIAL_AUTONOMOUS", raising=False)
    page = client.get("/dashboard").text
    assert "machine idle" in page and 'machine-beacon off' in page
    # engines on → it breathes
    monkeypatch.setenv("CHORDENTIAL_AUTONOMOUS", "1")
    page = client.get("/dashboard").text
    assert "machine running" in page and 'machine-beacon off' not in page


def test_living_grammar_present_in_stylesheet(client):
    css = client.get("/static/style.css").text
    for cls in (".machine-beacon", ".lv-veil", ".lv-halo", "lv-breathe"):
        assert cls in css
    # reduced-motion dignity is mandatory for the living layer
    assert "prefers-reduced-motion" in css


def test_update_intelligence_carries_the_honest_thinking_hooks(client):
    """Phase 2: the CI analyze form is marked for the thinking veil, its path
    names the real modules — and the no-JS path (a plain form post) stays fully
    intact. (The big-number fit% count-up was retired when the Opportunity
    Workspace was redesigned; the fit% now lives in the header fit-chip.)"""
    page = client.get("/opportunity/1").text
    assert "data-think" in page
    assert "Campaign Intelligence|Qualification|Buyer Profile" in page
    # the plain form action is unchanged — progressive enhancement only
    assert 'action="/opportunity/1/intelligence/analyze"' in page
    # the real POST still works without any JS
    r = client.post("/opportunity/1/intelligence/analyze",
                    data={"stance": "objective", "lane": "meeting_notes",
                          "text": "Budget is $18,000. Need it by November."},
                    follow_redirects=False)
    assert r.status_code == 303


def test_mission_control_hero_and_honest_machine_feed(client):
    """Phase 3: 'Waiting on you' counts only human-blocking decisions; the
    machine feed shows only real recorded events; the living element is the
    ticking clock (data-live-clock). Existing dashboard anchors preserved."""
    page = client.get("/dashboard").text
    assert "Waiting on you" in page and "mc-count" in page
    assert "Machine running" in page
    assert "data-live-clock" in page                  # the page's living element
    # existing anchors survive (council ruling: the hero is additive)
    assert "Top targets to pursue" in page
    assert 'href="/inbox?status=Submitted"' in page
    assert 'href="/inbox?status=Won"' in page


def test_alive_waveform_layer_on_client_audio_surfaces(client):
    """Phase 4: wave-live.js is served, and every surface with the compact
    .cap-audio player loads it (brief, first-touch, delivery portal/package).
    The original player markup is untouched — the wave is a pure overlay."""
    assert client.get("/static/wave-live.js").status_code == 200
    page = client.get("/opportunity/1/capabilities").text
    assert "wave-live.js" in page
    assert "cap-audio" in page or "relevant_uploads" not in page  # markup intact


def test_the_waveform_never_captures_audio_it_cannot_play(client):
    """The waveform silenced the product for a real client, and nothing reported it.

    `createMediaElementSource(audio)` does not observe an element — it CAPTURES it. Once
    called, the element's only route to the speakers is through the graph, so a suspended
    AudioContext means the client hears nothing while `audio.paused` stays false, no
    MediaError fires, and every other layer — file, bucket, read path, player — is
    healthy and says so. Measured in a browser before the fix: element playing, context
    suspended, graph clock frozen at 0, `currentTime` stuck at 0, no visible signal
    anywhere. After: the element plays untouched (`currentTime` 2.95 over 3s) because a
    context that is not running is never allowed to take the audio.

    Two invariants hold that line, and both are asserted because losing either brings the
    silence back:
      1. the context is built and resumed from the CLICK — the `play` event is not
         reliably inside the user-gesture window, and a context created outside it starts
         suspended;
      2. nothing is tapped unless `ctx.state` is genuinely "running" — not resuming, not
         a promise of running.
    """
    js = client.get("/static/wave-live.js").text
    assert 'ctx.state !== "running"' in js, (
        "the tap is not gated on a running context — a suspended one silences the player")
    assert 'player.addEventListener("click", gestureContext, true)' in js, (
        "the context is not built from the user gesture, so it will start suspended")
    # The capture must not sit in the play handler, which is where it was.
    play_handler = js.split('audio.addEventListener("play"')[1].split("});")[0]
    assert "createMediaElementSource" not in play_handler, (
        "the play handler taps the element directly again")


def _won_project(client):
    import re
    client.post("/opportunity/1/status", data={"status": "Won"},
                follow_redirects=True)
    client.post("/opportunity/1/project", follow_redirects=True)
    page = client.get("/opportunity/1").text
    m = re.search(r'href="/project/(\d+)"', page)
    return int(m.group(1))


def test_session_room_bus_is_role_filtered_server_side(client):
    """Phase 5: one event bus, filtered in SQL — an operator-only event never
    reaches the client role, no matter what the client asks for."""
    from chordential_oia.web import db as db_mod
    pid = _won_project(client)
    conn = db_mod.connect()
    try:
        db_mod.add_project_event(conn, pid, "comment", actor_role="client",
                                 actor_name="Elena", body="note for everyone")
        db_mod.add_project_event(conn, pid, "payout", actor_role="operator",
                                 actor_name="Studio", body="internal",
                                 audience="operator")
        token = db_mod.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    # operator (no token) sees both
    ops = client.get(f"/project/{pid}/session.json").json()
    assert len(ops["events"]) == 2
    # client (share token) sees only the shared event — the boundary held
    cl = client.get(f"/project/{pid}/session.json?k={token}").json()
    kinds = [e["kind"] for e in cl["events"]]
    assert kinds == ["comment"]
    # a bad token gets nothing at all
    assert client.get(f"/project/{pid}/session.json?k=wrong").status_code == 404


def test_session_room_presence_and_comment_event_roundtrip(client):
    from chordential_oia.web import db as db_mod
    pid = _won_project(client)
    conn = db_mod.connect()
    try:
        token = db_mod.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    # client pings presence via their token; operator sees them in the room
    r = client.post(f"/project/{pid}/presence",
                    data={"k": token, "name": "Elena"})
    assert r.json() == {"ok": True}
    d = client.get(f"/project/{pid}/session.json").json()
    assert {"name": "Elena", "role": "client"} in d["presence"]
    # a real portal comment lands on the bus for every role
    client.post(f"/project/{pid}/review/comment",
                data={"k": token, "author": "Elena", "email": "e@vance.com",
                      "body": "Love the bridge."}, follow_redirects=False)
    d2 = client.get(f"/project/{pid}/session.json?k={token}").json()
    assert any(e["kind"] == "comment" and "bridge" in e["body"]
               for e in d2["events"])


def test_session_room_strip_mounted_on_console_and_portal(client):
    from chordential_oia.web import db as db_mod
    pid = _won_project(client)
    conn = db_mod.connect()
    try:
        token = db_mod.ensure_project_share_token(conn, pid)
    finally:
        conn.close()
    console = client.get(f"/project/{pid}/delivery").text
    assert 'id="session-room"' in console and 'data-role="operator"' in console
    portal = client.get(f"/project/{pid}/delivery-portal?k={token}").text
    assert 'id="session-room"' in portal and 'data-role="client"' in portal
    assert "session-room.js" in portal


