"""The LinkedIn Search Agent — a MANUAL-ASSIST source.

LinkedIn requires login and its User Agreement forbids automated scraping, so the
agent never fetches. It builds the exact filtered Companies search deep link; the
human opens it in their own logged-in browser and hand-captures leads. These
tests cover the pure URL builder and that the source surfaces as manual-assist
(login-gated), never as an auto-fetched target.
"""

import importlib
import urllib.parse

from chordential_oia.web import discovery_sources as catalog


def _params(url):
    return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))


# --------------------------------------------------------------------------- #
# Pure deep-link builder
# --------------------------------------------------------------------------- #
def test_builder_defaults_to_requested_search():
    url = catalog.linkedin_company_search_url()
    assert url.startswith("https://www.linkedin.com/search/results/companies/?")
    p = _params(url)
    assert p["keywords"] == "advertising agency"
    assert p["companySize"] == '["C"]'             # 11–50 employees
    assert p["geoUrn"] == '["103644278"]'          # United States


def test_builder_is_parameterizable():
    url = catalog.linkedin_company_search_url(
        keywords="creative studio", geo_urn=None, size_codes=("C", "D"))
    p = _params(url)
    assert p["keywords"] == "creative studio"
    assert p["companySize"] == '["C","D"]'          # 11–50 + 51–200
    assert "geoUrn" not in p                         # omitted when geo is None


def test_company_size_codes():
    assert catalog.LINKEDIN_COMPANY_SIZES["11-50"] == "C"
    assert catalog.LINKEDIN_COMPANY_SIZES["51-200"] == "D"
    assert catalog.LINKEDIN_US_GEO_URN == "103644278"


# --------------------------------------------------------------------------- #
# Catalog entry — manual-assist (login-gated), never auto-fetched
# --------------------------------------------------------------------------- #
def test_linkedin_companies_is_manual_assist():
    site = catalog.get_site("linkedin_companies")
    assert site is not None
    assert site.kind == "opportunity"
    assert site.login_gated is True                  # never auto-scraped
    board = site.boards[0][2]
    p = _params(board)
    assert "search/results/companies" in board
    assert p["companySize"] == '["C"]' and p["geoUrn"] == '["103644278"]'


def test_manual_assist_surfaces_the_filtered_search(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "li.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import discovery as disc
    importlib.reload(disc)

    conn = db_mod.connect()
    db_mod.init_db(conn)
    disc.sync_catalog(conn)

    row = conn.execute(
        "SELECT * FROM discovery_sites WHERE key='linkedin_companies'").fetchone()
    assert row["login_gated"] == 1                   # lands in the manual-assist list

    searches = disc.manual_assist_searches(row)
    assert len(searches) >= 1
    url = searches[0]["url"]
    assert "linkedin.com/search/results/companies" in url
    assert "companySize" in url and "geoUrn" in url

    # Gated → it is never seeded as an auto-fetch target.
    assert disc.seed_active_targets(conn, row) == 0
    assert all(r["source_key"] != "linkedin_companies"
               for r in db_mod.list_crawl_targets(conn))
