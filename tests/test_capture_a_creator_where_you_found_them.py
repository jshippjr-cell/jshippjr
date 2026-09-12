"""One tap from a forum to a roster row, with the link attached (ADR-0097).

The supply-side rule is that a name enters only with a public source beside it
(`docs/marketing/deliverables/09-composer-track.md` §6). That rule survives contact
with a laptop and dies on a phone: the moment you find someone good you are three
threads deep in Reddit, and doing it honestly costs six fields of typing. So these
tests are mostly about the two things that make the rule cheap enough to keep — the
URL arrives by construction, and the door is open to a share-sheet that carries no
session cookie but shut to everyone else.
"""
import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

TOKEN = "a-long-capture-token-value"


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "c.db"))
    monkeypatch.setenv("CHORDENTIAL_CAPTURE_TOKEN", TOKEN)
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    for m in ("db", "capture", "talent_routes", "publicpaths", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as a, db
    conn = db.connect(); db.init_db(conn); conn.close()
    return a


# --------------------------------------------------------------------------- #
# The token is the access control, and an instance that never opted in has none.
# --------------------------------------------------------------------------- #
def test_the_capture_door_is_shut_without_the_token(app_mod):
    c = TestClient(app_mod.app)
    assert c.get("/capture/creator?k=wrong&url=https://x.test/").status_code == 404
    assert c.get("/capture/creator").status_code == 404
    assert c.post("/capture/creator", data={"k": "wrong", "url": "https://x.test/"}).status_code == 404


def test_capture_is_off_entirely_when_the_variable_is_unset(tmp_path, monkeypatch):
    """A null-by-default seam, like mail and payments. Not a door with a weak lock —
    no door. Otherwise every deployment that never configured this is running an open
    write endpoint on the public internet."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.delenv("CHORDENTIAL_CAPTURE_TOKEN", raising=False)
    for m in ("db", "capture", "talent_routes", "publicpaths", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from chordential_oia.web import app as a, capture, db
    conn = db.connect(); db.init_db(conn); conn.close()
    assert capture.capture_enabled() is False
    assert capture.token_ok("") is False and capture.token_ok("anything") is False
    c = TestClient(a.app)
    assert c.get("/capture/creator?k=&url=https://x.test/").status_code == 404


def test_the_admin_gate_lets_capture_through_but_nothing_near_it(app_mod):
    """A share-sheet shortcut carries no session cookie, so the gate must not bounce
    it — and a 303 to the login page would answer **200 with a login form**, which is
    indistinguishable from success on a phone."""
    from chordential_oia.web import publicpaths
    assert publicpaths.is_public("/capture/creator") and publicpaths.is_public("/capture/creator/")
    assert not publicpaths.is_public("/capture"), (
        "/capture alone is the operator's gig page — exempting it hands that away")
    assert not publicpaths.is_public("/capturex")
    assert not publicpaths.is_public("/talent")
    c = TestClient(app_mod.app)
    # gated neighbour bounces; capture answers on its own token
    assert c.get("/talent", follow_redirects=False).status_code in (302, 303, 307)
    assert c.get(f"/capture/creator?k={TOKEN}&url=https://x.test/").status_code == 200


# --------------------------------------------------------------------------- #
# The link arrives by construction — that is the whole point of the thing.
# --------------------------------------------------------------------------- #
def test_a_capture_keeps_the_url_it_came_from(app_mod):
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    url = "https://www.reddit.com/r/composer/comments/x/some_thread/"
    r = c.post("/capture/creator", data={"k": TOKEN, "url": url, "handle": "mira",
                                 "source": "reddit", "note": "left space in the pad"},
               follow_redirects=False)
    assert r.status_code == 303
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM talent ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row["source_url"] == url, "the link is the one thing that must never be lost"
    assert row["source"] == "reddit"
    assert row["handle"] == "mira"
    assert "left space" in row["notes"]


def test_a_row_with_only_a_handle_is_still_worth_making(app_mod):
    """A thread gives a username and nothing else. A row named for the handle with a
    live link under it beats the row that never got made because six fields were
    required."""
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    c.post("/capture/creator", data={"k": TOKEN, "url": "https://vi-control.net/community/threads/x.9/",
                             "handle": "pinescore", "source": "vi-control"},
           follow_redirects=False)
    conn = db.connect()
    try:
        row = conn.execute("SELECT name, source FROM talent ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row["name"] == "pinescore"
    assert row["source"] == "vi-control"


def test_capture_refuses_a_row_with_no_link(app_mod):
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    r = c.post("/capture/creator", data={"k": TOKEN, "url": "", "name": "Someone"},
               follow_redirects=False)
    assert r.status_code == 303 and "err=url" in r.headers["location"]
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM talent").fetchone()["c"] == 0
    finally:
        conn.close()


def test_the_form_arrives_already_filled_in(app_mod):
    c = TestClient(app_mod.app)
    page = c.get(f"/capture/creator?k={TOKEN}"
                 "&url=https://www.reddit.com/user/mira/&title=Mira%20K&note=the%20pad").text
    assert "https://www.reddit.com/user/mira/" in page
    assert 'value="mira"' in page, "the handle was in the URL and should be read out of it"
    assert "the pad" in page


# --------------------------------------------------------------------------- #
# Sending. Email leaves; the other two are opened for a human to send.
# --------------------------------------------------------------------------- #
def test_reddit_is_a_composed_message_not_an_api_call(app_mod):
    """Reddit's API would let the studio message strangers without a human, which is
    the fastest way to lose the account — and the account is how the composer track
    reaches its rooms at all. So the door OPENS the message, addressed and written."""
    from chordential_oia.web import capture
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    c.post("/capture/creator", data={"k": TOKEN, "url": "https://www.reddit.com/user/mira/",
                             "handle": "mira", "source": "reddit", "name": "Mira K"},
           follow_redirects=False)
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    page = jon.get("/talent/1").text
    assert "reddit.com/message/compose" in page
    assert "to=mira" in page
    url = capture.reddit_compose_url("mira", "Your piece", "Hello there")
    assert url.startswith("https://www.reddit.com/message/compose?to=mira")
    assert "Hello%20there" in url


def test_the_three_doors_carry_one_draft(app_mod):
    """`recruiting.compose_invite` is the single author of what we say. Three doors
    that each wrote their own pitch is three pitches inside a month."""
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    c = TestClient(app_mod.app)
    c.post("/capture/creator", data={"k": TOKEN, "url": "https://www.reddit.com/user/mira/",
                             "handle": "mira", "source": "reddit", "name": "Mira K"},
           follow_redirects=False)
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    jon.post("/talent/1/contact",
             data={"handle": "mira", "linkedin_url": "linkedin.com/in/mira"},
             follow_redirects=False)
    page = jon.get("/talent/1").text
    assert "li-copy" in page, "no LinkedIn door once a profile is on file"
    assert "reddit.com/message/compose" in page
    # the honest sentence about which of them actually sends
    assert "only email leaves without you" in page


def test_the_setup_page_hands_over_a_bookmarklet_and_stays_gated(app_mod):
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    anon = TestClient(app_mod.app)
    assert anon.get("/talent/capture-setup",
                    follow_redirects=False).status_code in (302, 303, 307), (
        "the setup page prints the capture token and must stay behind the gate")
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    page = jon.get("/talent/capture-setup").text
    assert "javascript:" in page and "/capture/creator?k=" in page
    assert "Show in Share Sheet" in page, "no phone instructions"


# --------------------------------------------------------------------------- #
# The small pure functions, which is where the guessing is kept.
# --------------------------------------------------------------------------- #
def test_the_source_is_read_from_the_host_and_never_guessed(app_mod):
    from chordential_oia.web import capture
    assert capture.source_for("https://www.reddit.com/r/x/") == "reddit"
    assert capture.source_for("https://vi-control.net/community/") == "vi-control"
    assert capture.source_for("https://example.test/someone") == "web"
    assert capture.source_for("") == "web"
    assert capture.source_for("not a url at all") == "web"


def test_a_handle_is_only_taken_where_the_url_states_one(app_mod):
    from chordential_oia.web import capture
    assert capture.handle_for("https://www.reddit.com/user/mira/") == "mira"
    assert capture.handle_for("https://www.reddit.com/u/mira") == "mira"
    assert capture.handle_for("https://www.reddit.com/r/composer/comments/x/y/") == ""
    assert capture.handle_for("https://example.test/anyone") == ""


def test_the_bookmarklet_cannot_be_pressed_on_the_setup_page(app_mod):
    """It is a thing to DRAG, and it looks exactly like a thing to press.

    The founder pressed it (2026-09-11) and captured the setup page he was standing
    on. The gig-capture page had already solved this with `onclick="return false;"`
    and a "drag me" label; this one had not copied it.
    """
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    jon = TestClient(app_mod.app)
    jon.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    page = jon.get("/talent/capture-setup").text
    assert 'onclick="return false;"' in page, "clicking the bookmarklet still fires it"
    assert "drag me to the bookmarks bar" in page


def test_capturing_our_own_site_says_so(app_mod, monkeypatch):
    """Belt to the braces above: whatever the button does, a capture of our own domain
    has no creator in it, and the form should say that rather than take the row
    silently."""
    c = TestClient(app_mod.app)
    from chordential_oia.web.shell import public_base
    own = public_base().rstrip("/") + "/talent/capture-setup"
    page = c.get(f"/capture/creator?k={TOKEN}&url={own}").text
    assert "nobody here to capture" in page
    assert "Save anyway" in page, "the escape hatch is still there, just not the default"
    other = c.get(f"/capture/creator?k={TOKEN}&url=https://www.reddit.com/user/mira/").text
    assert "nobody here to capture" not in other


def test_the_bookmarklet_reads_the_page_not_just_its_address(app_mod):
    """The first version sent the URL, the title and the selection — which on a forum
    thread is the THREAD's title and nothing else, while the member's name sits two
    elements away in the markup. The founder's verdict was "kinda useless" and it was
    right: saving one paste does not earn a bookmark.
    """
    from chordential_oia.web import capture
    js = capture.bookmarklet("https://chordential.test", TOKEN)
    assert "\n" not in js, "a newline ends a bookmarklet pasted into a bookmark field"
    # the three things it has to find on the page
    assert "memberHeader-name" in js and "message-name" in js, "no forum member name"
    assert "mailto:" in js, "no email"
    assert "soundcloud" in js and "bandcamp" in js, "no link to the work"
    # and it must hand them over
    for param in ("&name=", "&email=", "&reels=", "&url="):
        assert param in js, f"{param} never reaches the form"


def test_what_the_page_gave_up_arrives_in_the_form(app_mod):
    c = TestClient(app_mod.app)
    page = c.get(
        f"/capture/creator?k={TOKEN}"
        "&url=https://vi-control.net/community/threads/a-thread.172115/"
        "&title=Indie+Film+Music+Contest+Summer+2026"
        "&name=Remnant&email=r%40x.test"
        "&reels=https%3A%2F%2Fsoundcloud.com%2Fremnant%7Chttps%3A%2F%2Fvimeo.com%2Fremnant"
    ).text
    assert 'value="Remnant"' in page, "the member name was on the page and not carried"
    assert 'value="r@x.test"' in page
    assert page.count('class="pick"') == 2, "the links to their work are not offered"
    assert "soundcloud.com/remnant" in page


def test_the_link_to_the_work_is_saved_because_it_gates_everything(app_mod):
    """`talent.matchable` needs an approved reel, so the reel link decides whether the
    row is ever usable — and it is almost always already on the page."""
    from chordential_oia.web import db
    c = TestClient(app_mod.app)
    c.post("/capture/creator", data={
        "k": TOKEN, "url": "https://vi-control.net/community/threads/a.172115/",
        "name": "Remnant", "handle": "Remnant", "source": "vi-control",
        "demo_reel_url": "https://soundcloud.com/remnant"}, follow_redirects=False)
    conn = db.connect()
    try:
        row = conn.execute("SELECT name, demo_reel_url FROM talent ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row["name"] == "Remnant"
    assert row["demo_reel_url"] == "https://soundcloud.com/remnant"
