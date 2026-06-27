"""The Agency Spotter Agent — catalog entry, the Next.js flight-JSON parser, and
the paginating fetch that walks the whole directory and saves to the database.

Agency Spotter is a Next.js app, so the listing data lives in embedded RSC
"flight" payloads, not visible markup. The parser is pure (HTML string → records
+ page counts) and the fetch is exercised by monkeypatching the one HTTP seam
(``_get_with_meta``), so nothing here touches the network.
"""

import importlib
import importlib.util
import json
import pathlib
import urllib.parse

import pytest

from chordential_oia.web import crawl_adapters as ca
from chordential_oia.web import discovery_sources as catalog


def _load_exporter():
    """Load the standalone export script as a module (it isn't a package)."""
    path = (pathlib.Path(__file__).resolve().parent.parent
            / "scripts" / "export_agency_spotter_pdf.py")
    spec = importlib.util.spec_from_file_location("export_agency_spotter_pdf", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- #
# Flight-JSON fixtures (mimic Agency Spotter's __next_f script chunks)
# --------------------------------------------------------------------------- #
def _agency(name, slug, **kw):
    a = {"name": name, "slug": slug, "url": f"https://{slug}.com",
         "email": f"hi@{slug}.com", "city": "Austin", "state": "TX",
         "country": "United States", "size": "10 - 49", "services": ["Video Production"],
         "budget_min": 5000, "budget_mid": 20000, "avg_rating": 5, "review_count": 7,
         "client_list": "Nike\nApple"}
    a.update(kw)
    return a


def _flight_html(agencies, current=1, total=1, count=None, split=False):
    """Build page HTML carrying ``agencies`` in RSC flight chunks (optionally split
    across two chunks to exercise reconstruction)."""
    if count is None:
        count = len(agencies)
    flight = ('d:["$","$L1c",null,{"value":{"agencies":' + json.dumps(agencies)
              + ',"currentPage":%d,"totalPages":%d,"count":%d,"groupName":"Video Production"}}]'
              % (current, total, count))
    chunks = ([flight[:len(flight) // 2], flight[len(flight) // 2:]] if split else [flight])
    return "".join('<script>self.__next_f.push([1,%s])</script>' % json.dumps(c) for c in chunks)


# --------------------------------------------------------------------------- #
# Catalog entry — now an active, public (non-gated) source
# --------------------------------------------------------------------------- #
def test_agency_spotter_is_active_public_source():
    site = catalog.get_site("agencyspotter")
    assert site is not None
    assert site.kind == "opportunity"
    assert site.status == catalog.STATUS_ESTABLISHED   # auto-fetched, not manual-assist
    assert site.login_gated is False                   # public directory, no login
    templates = [t for (_k, _l, t) in site.boards]
    assert any(t.endswith("/all") for t in templates)          # walk the whole directory
    assert any("{q}" in t for t in templates)                  # keyworded search board


def test_directory_target_is_recognized():
    site = catalog.get_site("agencyspotter")
    targets = catalog.site_targets(site, "opportunity")
    dir_target = next(t for t in targets if t["url"].endswith("/all"))
    assert ca.is_agency_spotter(dir_target) is True


# --------------------------------------------------------------------------- #
# Pure flight-JSON parser
# --------------------------------------------------------------------------- #
def test_parse_agency_spotter_page_shape():
    html = _flight_html(
        [_agency("AURORA Creative", "aurora", city="Los Angeles", state="CA",
                 services=["Video Production", "Branding"], avg_rating=5, review_count=9)],
        current=1, total=21, count=602)
    page = ca.parse_agency_spotter_page(html)
    assert page["total_pages"] == 21 and page["count"] == 602 and page["current_page"] == 1
    assert len(page["records"]) == 1

    r = page["records"][0]
    assert r["company"] == "AURORA Creative"
    assert r["need"] == "Agency — Video Production, Branding"  # is_agency_need recognizes this
    assert r["url"] == "https://www.agencyspotter.com/aurora"  # profile, from slug
    assert "Los Angeles, CA, United States" in r["description"]
    assert "https://aurora.com" in r["description"]            # agency website kept in desc
    assert "clients: Nike, Apple" in r["description"]


def test_parse_handles_split_chunks_and_garbage():
    html = _flight_html([_agency("Split Co", "splitco")], split=True)
    assert [r["company"] for r in ca.parse_agency_spotter(html)] == ["Split Co"]
    assert ca.parse_agency_spotter("<html>no flight here</html>") == []
    assert ca.parse_agency_spotter("") == []


def test_parse_skips_nameless_and_flight_reference_clients():
    html = _flight_html([
        _agency("", "noname"),                       # dropped (no name)
        _agency("Ref Co", "refco", client_list="$1e"),  # flight ref → clients omitted
    ])
    recs = ca.parse_agency_spotter(html)
    assert [r["company"] for r in recs] == ["Ref Co"]
    assert "clients:" not in recs[0]["description"]


# --------------------------------------------------------------------------- #
# Page-URL builder (pure)
# --------------------------------------------------------------------------- #
def test_agency_spotter_page_url_sets_and_replaces_page():
    assert "page=2" in ca.agency_spotter_page_url("https://www.agencyspotter.com/all", 2)
    u = ca.agency_spotter_page_url("https://www.agencyspotter.com/search?keywords=video&page=1", 3)
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(u).query))
    assert q["page"] == "3" and q["keywords"] == "video"


# --------------------------------------------------------------------------- #
# Paginating fetch — walks the whole directory via totalPages, dedupes
# --------------------------------------------------------------------------- #
def _paged_fetcher(pages):
    def fake(url, headers, timeout=10.0):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        page = int(q.get("page", "1") or "1")
        return pages.get(page, _flight_html([], current=page, total=len(pages))), 200, url
    return fake


def test_fetch_walks_to_total_pages_and_dedupes(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    pages = {
        1: _flight_html([_agency("Alpha", "alpha"), _agency("Beta", "beta")], current=1, total=2, count=3),
        2: _flight_html([_agency("Gamma", "gamma"), _agency("Alpha", "alpha")], current=2, total=2, count=3),
    }
    monkeypatch.setattr(ca, "_get_with_meta", _paged_fetcher(pages))

    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/all")
    assert res["outcome"] == "ok"
    assert [r["company"] for r in res["records"]] == ["Alpha", "Beta", "Gamma"]  # Alpha deduped
    assert "Walked 2 of 2 page(s)" in res["detail"]
    assert "3 agencies" in res["detail"] and "cap" not in res["detail"]


def test_fetch_respects_page_cap_and_reports_it(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_MAX_PAGES", "2")

    def endless(url, headers, timeout=10.0):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        page = int(q.get("page", "1") or "1")
        return _flight_html([_agency(f"Agency{page}", f"a{page}")], current=page, total=10, count=10), 200, url
    monkeypatch.setattr(ca, "_get_with_meta", endless)

    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/all")
    assert len(res["records"]) == 2
    assert "2-page cap" in res["detail"] and "of 10 page(s)" in res["detail"]


def test_fetch_login_or_block_outcome(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    wall = '<html><form><input type="password"></form>Please log in</html>'
    monkeypatch.setattr(ca, "_get_with_meta", lambda url, headers, timeout=10.0: (wall, 200, url))
    res = ca.fetch_agency_spotter("https://www.agencyspotter.com/all")
    assert res["records"] == [] and res["outcome"] == "login"


# --------------------------------------------------------------------------- #
# Dispatch + the scrape gate
# --------------------------------------------------------------------------- #
def test_dispatch_routes_to_agency_spotter_when_enabled(monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_ENABLE_SCRAPE", "1")
    monkeypatch.setenv("CHORDENTIAL_AGENCYSPOTTER_DELAY", "0")
    pages = {1: _flight_html([_agency("Solo", "solo")], current=1, total=1, count=1)}
    monkeypatch.setattr(ca, "_get_with_meta", _paged_fetcher(pages))
    target = {"source_key": "agencyspotter",
              "url": "https://www.agencyspotter.com/all", "kind": "opportunity"}
    res = ca.fetch_opportunity_records(target)
    assert res["outcome"] == "ok" and [r["company"] for r in res["records"]] == ["Solo"]


def test_dispatch_off_when_scrape_disabled(monkeypatch):
    monkeypatch.delenv("CHORDENTIAL_ENABLE_SCRAPE", raising=False)
    target = {"source_key": "agencyspotter",
              "url": "https://www.agencyspotter.com/all", "kind": "opportunity"}
    res = ca.fetch_opportunity_records(target)
    assert res["outcome"] == "off" and res["records"] == []


# --------------------------------------------------------------------------- #
# Agency-need recognition + the PDF exporter's row selection
# --------------------------------------------------------------------------- #
def test_is_agency_need():
    assert ca.is_agency_need("Agency — Video Production") is True
    assert ca.is_agency_need(ca.AGENCY_NEED_DEFAULT) is True
    assert ca.is_agency_need("Brand spot music") is False
    assert ca.is_agency_need("") is False and ca.is_agency_need(None) is False


def _seed_leads(db):
    conn = db.connect()
    db.init_db(conn)
    db.insert_inbound_lead(conn, contact_name="(discovered)", company="AURORA Creative",
                           project_type="Agency — Video Production", source="crawl")
    db.insert_inbound_lead(conn, contact_name="(discovered)", company="Vance Athletic",
                           project_type=ca.AGENCY_NEED_DEFAULT, source="crawl")
    db.insert_inbound_lead(conn, contact_name="(discovered)", company="IndieGameCo",
                           project_type="Composer for trailer", source="crawl")
    db.insert_inbound_lead(conn, contact_name="Jane", company="BrandX",
                           project_type="Spot music", source="questionnaire")
    conn.commit()
    return conn


def test_select_agency_leads_filters_to_agencies(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "x.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = _seed_leads(db_mod)

    exporter = _load_exporter()
    names = {l["company"] for l in exporter.select_agency_leads(conn)}
    assert names == {"AURORA Creative", "Vance Athletic"}
    all_crawl = {l["company"] for l in exporter.select_agency_leads(conn, all_crawl=True)}
    assert all_crawl == {"AURORA Creative", "Vance Athletic", "IndieGameCo"}


def test_build_pdf_smoke(tmp_path, monkeypatch):
    pytest.importorskip("reportlab")
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "x.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = _seed_leads(db_mod)

    exporter = _load_exporter()
    out = str(tmp_path / "findings.pdf")
    exporter.build_pdf(exporter.select_agency_leads(conn), out)
    data = pathlib.Path(out).read_bytes()
    assert data[:5] == b"%PDF-" and b"%%EOF" in data[-2048:]
    empty = str(tmp_path / "empty.pdf")
    exporter.build_pdf([], empty)
    assert pathlib.Path(empty).read_bytes()[:5] == b"%PDF-"
