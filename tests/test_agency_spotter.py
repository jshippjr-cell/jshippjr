"""The Agency Spotter Agent — catalog entry, pure parser, and the paginating,
human-gated fetch that walks the agency directory page by page.

Mirrors the test discipline of the rest of discovery: the parser is pure (HTML →
records, no network) and the fetch is exercised by monkeypatching the one HTTP
seam (``_get_with_meta``) so nothing here ever touches the network.
"""

import urllib.parse

import pytest

from chordential_oia.web import crawl_adapters as ca
from chordential_oia.web import discovery_sources as catalog


# --------------------------------------------------------------------------- #
# Catalog entry
# --------------------------------------------------------------------------- #
def test_agency_spotter_in_catalog_as_gated_opportunity_source():
    site = catalog.get_site("agencyspotter")
    assert site is not None
    assert site.kind == "opportunity"          # agencies are the demand side
    assert site.status == catalog.STATUS_SUGGESTED
    assert site.login_gated is True            # sign-in / ToS → manual-assist
    # A keywordable search board and a fixed browse-the-whole-directory board.
    templates = [tmpl for (_kind, _label, tmpl) in site.boards]
    assert any("{q}" in t for t in templates)
    assert any(t.endswith("/agencies") for t in templates)


def test_directory_target_paginates_from_a_fixed_board():
    """The fixed directory board has no {q}; site_targets emits a plain listing
    target the agent can then walk page by page."""
    site = catalog.get_site("agencyspotter")
    targets = catalog.site_targets(site, "opportunity")
    dir_target = next(t for t in targets if t["url"].endswith("/agencies"))
    assert dir_target["source_key"] == "agencyspotter"
    assert ca.is_agency_spotter(dir_target) is True


# --------------------------------------------------------------------------- #
# Pure parser
# --------------------------------------------------------------------------- #
def test_parse_agency_spotter_html_shape():
    html = (
        '<ul>'
        '<li class="agency" data-name="AURORA Creative" '
        'data-specialties="branding,video" data-location="Austin, TX" '
        'data-url="https://www.agencyspotter.com/aurora" '
        'data-description="Full-service brand studio."></li>'
        '<li class="agency" data-name="Vance Athletic Agency" '
        'data-url="https://www.agencyspotter.com/vance"></li>'
        '<li class="not-an-agency" data-name="ignore me"></li>'
        '</ul>'
    )
    recs = ca.parse_agency_spotter_html(html)
    assert len(recs) == 2                       # the non-agency element is ignored

    a = recs[0]
    assert a["company"] == "AURORA Creative"
    assert a["need"] == "Agency — branding, video"
    assert a["description"] == "Austin, TX · Full-service brand studio."
    assert a["url"] == "https://www.agencyspotter.com/aurora"

    # No specialties → a sensible default need; no location/desc → empty string.
    b = recs[1]
    assert b["company"] == "Vance Athletic Agency"
    assert b["need"] == "Creative agency (potential music buyer)"
    assert b["description"] == ""


def test_parse_skips_nameless_and_handles_garbage():
    assert ca.parse_agency_spotter_html("") == []
    assert ca.parse_agency_spotter_html('<li class="agency"></li>') == []   # no name
    assert ca.parse_agency_spotter_html("<li class='agency' data-name") == []  # malformed


# --------------------------------------------------------------------------- #
# Page-URL builder (pure)
# --------------------------------------------------------------------------- #
def test_agency_spotter_page_url_sets_and_replaces_page():
    base = "https://www.agencyspotter.com/agencies"
    assert "page=2" in ca.agency_spotter_page_url(base, 2)

    # Existing params preserved; existing page replaced (not duplicated).
    u = ca.agency_spotter_page_url(
        "https://www.agencyspotter.com/search?keywords=video&page=1", 3)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))
    assert q["page"] == "3"
    assert q["keywords"] == "video"


# --------------------------------------------------------------------------- #
# Paginating fetch — walks every page, dedupes, reports honestly
# --------------------------------------------------------------------------- #
def _page_html(agencies):
    return "".join(
        f'<li class="agency" data-name="{n}" data-url="{u}"></li>' for n, u in agencies
    )


def _paged_fetcher(pages):
    """Return a _get_with_meta stand-in serving ``pages`` keyed by page number
    (page 1 = no/blank page param). Any page past the list returns empty HTML —
    the natural end-of-directory signal."""
    def fake(url, headers, timeout=10.0):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        page = int(q.get("page", "1") or "1")
        html = pages.get(page, "")
        return html, 200, url
    return fake


def test_fetch_walks_all_pages_and_dedupes(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    pages = {
        1: _page_html([("Alpha", "u/alpha"), ("Beta", "u/beta")]),
        2: _page_html([("Gamma", "u/gamma"), ("Beta", "u/beta")]),   # Beta repeats
        3: _page_html([("Delta", "u/delta")]),
        # page 4 absent → empty → stop
    }
    monkeypatch.setattr(ca, "_get_with_meta", _paged_fetcher(pages))

    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/agencies")
    assert res["outcome"] == "ok"
    companies = [r["company"] for r in res["records"]]
    assert companies == ["Alpha", "Beta", "Gamma", "Delta"]   # Beta deduped once
    assert "Walked 4 page(s)" in res["detail"]                 # 3 with data + 1 empty
    assert "cap" not in res["detail"]


def test_fetch_respects_page_cap_and_reports_it(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_MAX_PAGES", "2")
    # Every page returns fresh data forever — only the cap can stop the walk.
    def endless(url, headers, timeout=10.0):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        page = int(q.get("page", "1") or "1")
        return _page_html([(f"Agency{page}", f"u/{page}")]), 200, url
    monkeypatch.setattr(ca, "_get_with_meta", endless)

    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/agencies")
    assert len(res["records"]) == 2                 # capped at 2 pages
    assert "2-page cap" in res["detail"]            # truncation reported, not hidden


def test_fetch_login_wall_outcome(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    wall = '<html><form><input type="password"></form>Please log in</html>'
    monkeypatch.setattr(ca, "_get_with_meta",
                        lambda url, headers, timeout=10.0: (wall, 200, url))
    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/agencies")
    assert res["records"] == []
    assert res["outcome"] == "login"                # diagnosed from the first page


# --------------------------------------------------------------------------- #
# Dispatch + the scrape gate
# --------------------------------------------------------------------------- #
def test_dispatch_routes_to_agency_spotter_when_enabled(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    pages = {1: _page_html([("Solo", "u/solo")])}
    monkeypatch.setattr(ca, "_get_with_meta", _paged_fetcher(pages))

    target = {"source_key": "agencyspotter",
              "url": "https://www.agencyspotter.com/agencies", "kind": "opportunity"}
    res = ca.fetch_opportunity_records(target)
    assert res["outcome"] == "ok"
    assert [r["company"] for r in res["records"]] == ["Solo"]


def test_dispatch_off_when_scrape_disabled(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    target = {"source_key": "agencyspotter",
              "url": "https://www.agencyspotter.com/agencies", "kind": "opportunity"}
    res = ca.fetch_opportunity_records(target)
    assert res["outcome"] == "off"
    assert res["records"] == []
