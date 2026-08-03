"""Phase 1 of the launch review: the fixes that were verified by rendering the
running app, pinned here so they cannot silently regress.

Each test names the failure it is guarding against. These were found by walking the
product cold, so the assertions are deliberately behavioural — "the button goes
somewhere real", "the number survives the click" — rather than checks that a
particular line of markup still exists.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


# --------------------------------------------------------------------------- #
# The conversion graph. Every CTA on the sales surfaces has to land on a route
# that exists — the whole page is wasted otherwise.
# --------------------------------------------------------------------------- #

def test_commission_ctas_leave_the_page(client):
    """Every CTA on /commission was href="#brief" — and #brief was the closing
    section, whose only content was two more buttons pointing back at itself. The
    page could not convert at all."""
    body = client.get("/commission").text
    assert 'href="#brief"' not in body, "a CTA still loops back into the page"
    assert 'href="/start"' in body
    assert 'href="/book"' in body


def test_public_nav_has_no_dead_anchors(client):
    """'Work' → /#reel and 'About' → /#about survived two homepage replacements;
    neither anchor exists on the live homepage, so both landed silently at the top
    of a film showing no work."""
    for path in ("/start", "/book", "/capabilities", "/samples", "/thanks"):
        body = client.get(path).text
        assert 'href="/#reel"' not in body, f"{path} still links to the dead reel anchor"
        assert 'href="/#about"' not in body, f"{path} still links to the dead about anchor"


def test_reel_redirect_lands_somewhere_that_shows_work(client):
    """/reel used to redirect to /?reel=1, which nothing on the current homepage
    handles."""
    r = client.get("/reel", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["location"] == "/samples"
    assert client.get("/samples").status_code == 200


def test_homepage_carries_a_persistent_cta(client):
    """The scroll engine has always supported a topbar CTA; the homepage never
    passed one, so the only way out was two buttons after five viewport-heights of
    film — and on phones the section nav is hidden entirely."""
    body = client.get("/").text
    assert "cta:" in body and "/start" in body


def test_retired_homepage_template_is_gone(client):
    """public/home.html was rendered by no route while remaining the only inbound
    link to /samples — dead code feeding stale links into the live site."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod
    tpl = Path(app_mod.__file__).parent / "templates" / "public" / "home.html"
    assert not tpl.exists()


# --------------------------------------------------------------------------- #
# Data safety.
# --------------------------------------------------------------------------- #

def test_marking_won_preserves_the_deal_value(client, tmp_path):
    """Reproduced live before the fix: the board and the stepper post status with no
    outcome_value, and update_status assigned it unconditionally — so one click on
    Won wrote NULL over what the deal was worth."""
    from chordential_oia.models import BuyerType, MusicRequirement, Opportunity
    from chordential_oia.web import db

    conn = db.connect()
    try:
        db.init_db(conn)
        opp_id = db.insert_opportunity(conn, Opportunity(
            client="Test Buyer", need="Original :30 spot", description="x",
            buyer_type=BuyerType.AGENCY, music_requirement=MusicRequirement.ORIGINAL,
            budget_min=0, budget_max=0))
        db.update_status(conn, opp_id, "Submitted", 4847.0)
        assert db.get_opportunity(conn, opp_id)["outcome_value"] == 4847.0

        # the stepper's payload: a stage move carrying no money
        db.update_status(conn, opp_id, "Won")
        assert db.get_opportunity(conn, opp_id)["outcome_value"] == 4847.0, \
            "marking Won erased the recorded value"

        # an explicitly supplied value must still overwrite
        db.update_status(conn, opp_id, "Won", 12345.0)
        assert db.get_opportunity(conn, opp_id)["outcome_value"] == 12345.0
    finally:
        conn.close()


def test_only_one_stripe_webhook_is_registered():
    """Two @app.post("/webhooks/stripe") handlers were declared. Starlette matches
    the first, so the second was dead code — and it had already drifted: it never
    unlocked client downloads. A payment bug fixed in the dead one would do nothing."""
    from chordential_oia.web import app as app_mod
    routes = [r for r in app_mod.app.routes
              if getattr(r, "path", None) == "/webhooks/stripe"]
    assert len(routes) == 1, f"{len(routes)} stripe webhook routes registered"


def test_production_uploads_are_configured_onto_the_persistent_disk():
    """CHORDENTIAL_UPLOAD_DIR was unset in render.yaml, so uploads landed inside the
    installed package — rebuilt on every deploy, and autoDeploy means every push.
    Client cuts and masters did not survive."""
    from pathlib import Path
    import yaml

    blueprint = Path(__file__).resolve().parents[1] / "render.yaml"
    spec = yaml.safe_load(blueprint.read_text())
    service = spec["services"][0]
    env = {v["key"]: v.get("value") for v in service["envVars"] if "key" in v}
    upload_dir = env.get("CHORDENTIAL_UPLOAD_DIR")
    assert upload_dir, "uploads would land in the ephemeral package directory"
    assert upload_dir.startswith(service["disk"]["mountPath"]), \
        "uploads must live on the persistent disk"


# --------------------------------------------------------------------------- #
# Trust surfaces.
# --------------------------------------------------------------------------- #

def test_spend_guard_runs_before_the_request_is_sent():
    """The cost confirm was an inline onsubmit=, but live.js binds submit in the
    CAPTURE phase — it had already fired the paid fetch before the inline handler
    ran, so answering No cancelled only the navigation, never the charge. The guard
    now lives inside that same capture handler, ahead of the dispatch."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    web = Path(app_mod.__file__).parent
    live_js = (web / "static" / "live.js").read_text()
    detail = (web / "templates" / "detail.html").read_text()

    assert "data-confirm" in live_js, "live.js no longer implements the guard"
    guard = live_js.index("data-confirm")
    dispatch = live_js.index("fetch(form.action")
    assert guard < dispatch, "the guard must be read before the request is dispatched"

    # The invariant is specifically about forms live.js intercepts. An inline
    # onsubmit elsewhere (the Delete-deal confirm) is fine — nothing preempts it.
    import re
    intercepted = [tag for tag in re.findall(r"<form\b[^>]*>", detail, re.S)
                   if "data-think" in tag]
    assert intercepted, "the analyze form is no longer a data-think form"
    for tag in intercepted:
        assert "onsubmit=" not in tag, \
            "a capture-intercepted form carries an inline onsubmit, which cannot win"
    assert any("data-confirm=" in tag for tag in intercepted), \
        "the analyze form lost its spend guard"


def test_analyze_form_does_not_fake_progress():
    """The analyze form stacked three loading states, one of them a hairline bar
    easing toward 90% on a timer with no connection to the work. Motion is supposed
    to report real state; the veil already does."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    web = Path(app_mod.__file__).parent
    assert "data-progress" not in (web / "templates" / "detail.html").read_text()
    assert "chordentialEasedProgress" not in (web / "static" / "ui.js").read_text()


def test_demo_copy_carries_no_real_trademark(client):
    """The invented-brand rule exists so the demo fiction stays honest; a real
    campaign was hanging inside a fabricated client's brief."""
    body = client.get("/experience").text
    assert "Nike" not in body


def test_text_is_compressed(client):
    """Nothing was content-encoded before: the vendored three.js build went out as
    594 KB of raw JavaScript on every visit to /commission."""
    r = client.get("/static/public/vendor/three.min.js",
                   headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") == "gzip"


def test_range_requests_are_never_compressed(client):
    """Starlette's GZipMiddleware compresses on size alone — applied naively it gzips
    a 206 body while leaving content-range describing the uncompressed extent, so the
    response contradicts itself. The homepage film is scrubbed through range requests,
    so this would break the front door on any browser that seeks."""
    r = client.get("/static/public/world/leg1.mp4",
                   headers={"Range": "bytes=0-1023", "Accept-Encoding": "gzip"})
    assert r.status_code == 206
    assert r.headers.get("content-encoding") is None, "a partial response was gzipped"
    assert r.headers["content-length"] == "1024"
    assert r.headers["content-range"].startswith("bytes 0-1023/")


def test_already_compressed_media_is_not_re_compressed(client):
    """Gzipping a JPEG or a 512 MB master buys nothing and costs CPU per byte."""
    r = client.get("/static/public/world/still1.jpg",
                   headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200
    assert r.headers.get("content-encoding") is None


@pytest.mark.parametrize("claim", [
    "only you can approve as you",
    "cannot approve",
])
def test_portal_does_not_promise_a_gate_it_does_not_enforce(claim):
    """Three places claimed the share link could not approve. The code deliberately
    allows it (ADR-0020: the client's single approval IS the award, so it must not
    depend on a link they may not have). The copy now describes what actually
    happens — a forwardable bearer token — instead of a gate that isn't there."""
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    templates = Path(app_mod.__file__).parent / "templates"
    for name in ("delivery_portal.html", "delivery_console.html"):
        assert claim not in (templates / name).read_text(), f"{name} still claims: {claim}"
