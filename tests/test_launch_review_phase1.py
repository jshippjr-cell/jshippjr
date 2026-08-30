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
    for path in ("/start", "/book", "/thanks"):
        body = client.get(path).text
        assert 'href="/#reel"' not in body, f"{path} still links to the dead reel anchor"
        assert 'href="/#about"' not in body, f"{path} still links to the dead about anchor"


def test_reel_redirect_lands_somewhere_that_shows_work(client):
    """/reel used to redirect to /?reel=1, which nothing on the current homepage
    handles. It then pointed at /samples; that page is retired too, so it now lands
    on the front door's listening beat — the one place that actually plays the work."""
    r = client.get("/reel", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["location"] == "/#hear"


def test_the_retired_pages_redirect_rather_than_404(client):
    """/samples and /capabilities are gone as pages. An indexed URL or a bookmark
    must still land on what replaced them, not on a dead end."""
    for path in ("/samples", "/capabilities"):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 301, f"{path} answered {r.status_code}"
        assert r.headers["location"] == "/#hear"


def test_homepage_carries_a_persistent_cta(client):
    """Whatever is at the front door, a visitor must be able to leave for the intake
    without first scrolling the whole story. The film that used to land here shipped
    with its only two CTAs after five viewport-heights, and on phones its nav was
    hidden entirely. The Commission carries a header button and a fixed dock; a future
    front door has to carry its own equivalent."""
    body = client.get("/").text
    assert "/start" in body, "the homepage has no route to the intake at all"

    assert 'id="dockCta"' in body and '<header class="bar">' in body, (
        "the homepage exposes no CTA from persistent chrome — the only way out is "
        "reaching the end of the page"
    )


def test_every_front_of_house_route_is_reachable_with_the_gate_on():
    """The admin gate is path-allowlisted, so a public page whose route was written
    without adding it to _PUBLIC_PATHS answers 303 -> /admin/login in production and
    nowhere else — it looks fine in dev, where the gate is off. That is how
    /commission shipped unreachable: the page was built, linked and tested, and the
    only thing missing was one string in a set on the other side of the app."""
    import re
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    # The gate moved out of app.py into `publicpaths.py` (2026-08-28); the audit
    # follows the set rather than the file it used to sit in.
    src = (Path(app_mod.__file__).parent / "publicpaths.py").read_text()
    block = src.split("_PUBLIC_PATHS = frozenset({")[1].split("})")[0]
    allowed = set(re.findall(r'"([^"]+)"', block))

    public_py = (Path(app_mod.__file__).parent / "public.py").read_text()
    routes = set(re.findall(r'@router\.get\(\s*"(/[a-z-]*)"', public_py))

    missing = {r for r in routes if r not in allowed}
    assert not missing, f"front-of-house routes gated behind the admin login: {missing}"


def test_public_pages_answer_with_the_gate_enabled(tmp_path, monkeypatch):
    """The behavioural half of the test above: with a token set, every front-of-house
    page must still render rather than redirect to the login."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "gate.db"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "secret-passphrase")
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)

    with TestClient(app_mod.app) as c:
        for path in ("/", "/commission", "/start", "/book"):
            r = c.get(path, follow_redirects=False)
            assert r.status_code == 200, (
                f"{path} answered {r.status_code} "
                f"({r.headers.get('location')}) with the admin gate on")
        # and the gate still actually gates the console
        assert c.get("/dashboard", follow_redirects=False).status_code == 303


def test_every_shipped_asset_is_actually_packaged():
    """Assets are installed by the package-data globs in pyproject, and those are
    setuptools globs: ``*`` stops at a directory separator. In dev this is invisible
    because StaticFiles serves the source tree, so a file can be committed, linked,
    requested by a template and covered by a test, and still 404 in production because
    it was never installed. That is exactly what happened to the vendored three.js:
    ``static/public/*.js`` does not reach ``static/public/vendor/``, so /commission
    rendered with no 3D layer at all on the live site.

    Asserting the glob list covers the tree catches the next one too — a TestClient
    request never can, whatever it asserts."""
    import glob
    import os
    import tomllib
    from pathlib import Path
    from chordential_oia.web import app as app_mod

    repo = Path(__file__).resolve().parents[1]
    cfg = tomllib.loads((repo / "pyproject.toml").read_text())
    patterns = cfg["tool"]["setuptools"]["package-data"]["chordential_oia.web"]

    web = Path(app_mod.__file__).parent
    included = set()
    for pattern in patterns:
        for hit in glob.glob(str(web / pattern)):
            included.add(os.path.relpath(hit, web))

    missing = []
    for f in web.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(web).as_posix()
        if rel.endswith(".py") or "__pycache__" in rel:
            continue
        if rel.startswith("uploads/"):     # runtime data, correctly not shipped
            continue
        if rel not in included:
            missing.append(rel)

    assert not missing, (
        "these files are served in dev but would 404 in production — add a "
        f"package-data glob for each: {sorted(missing)}"
    )


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
    from conftest import registered_routes
    routes = [r for r in registered_routes(app_mod.app)
              if r[0] == "/webhooks/stripe"]
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
    # ADR-0089 renamed the dispatch: `form.action` is shadowed by a control named
    # "action", so the URL is read with getAttribute via `formURL()`. The invariant this
    # test protects — the guard is read BEFORE the request goes out — is unchanged.
    dispatch = live_js.index("fetch(formURL(form)")
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
    r = client.get("/static/public/hero-spliced.mp4",
                   headers={"Range": "bytes=0-1023", "Accept-Encoding": "gzip"})
    assert r.status_code == 206
    assert r.headers.get("content-encoding") is None, "a partial response was gzipped"
    assert r.headers["content-length"] == "1024"
    assert r.headers["content-range"].startswith("bytes 0-1023/")


def test_already_compressed_media_is_not_re_compressed(client):
    """Gzipping a JPEG or a 512 MB master buys nothing and costs CPU per byte."""
    r = client.get("/static/public/hero-spliced-poster.jpg",
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
