"""Site-fitted directory parsers. AdForum is fitted against its real markup
(server-rendered .b-search_result__item blocks); the parser is pure and the
fetch seam is monkeypatched so the engine integration test stays offline.
"""

import importlib

from chordential_oia.web import db as dbm
from chordential_oia.web import directory_crawl as dc
from chordential_oia.web import directory_parsers as dp


# A faithful slice of a real AdForum /agency/search results page: the count
# header + three result items (one with an empty city, like "The Annex").
ADFORUM_HTML = """
<h5 class="m-b-sm b-search_result__title">7969 Results</h5>
<div class="b-search_result__items appendable">
  <div class="b-search_result__item" itemscope itemtype="http://schema.org/LocalBusiness">
    <a href="/agency/9394/profile/worldwide-partners-inc" class="b-search_result__logo"><img></a>
    <h3 class="m-a-0"><a href="/agency/9394/profile/worldwide-partners-inc" class="b-search_result__link--title" onClick="x()" itemprop="url">Worldwide Partners, Inc.</a></h3>
    <h4><a href="/agency/9394/profile/worldwide-partners-inc" class="b-search_result__link--subtitle">
        Denver
        , United States                    </a></h4>
    <h4><a href="/agency/9394/profile/worldwide-partners-inc" class="b-search_result__link--competency">
        Full Service,
        Digital,
        Social Media,
        Experiential,
        More...
    </a></h4>
  </div>
  <div class="b-search_result__item" itemscope itemtype="http://schema.org/LocalBusiness">
    <h3 class="m-a-0"><a href="/agency/16436/profile/davidgoliath" class="b-search_result__link--title" itemprop="url">David&Goliath</a></h3>
    <h4><a href="/agency/16436/profile/davidgoliath" class="b-search_result__link--subtitle">
        El Segundo
        , United States                    </a></h4>
    <h4><a href="/agency/16436/profile/davidgoliath" class="b-search_result__link--competency">
        Full Service,
        More...
    </a></h4>
  </div>
  <div class="b-search_result__item" itemscope itemtype="http://schema.org/LocalBusiness">
    <h3 class="m-a-0"><a href="/agency/6657554/profile/the-annex" class="b-search_result__link--title" itemprop="url">The Annex</a></h3>
    <h4><a href="/agency/6657554/profile/the-annex" class="b-search_result__link--subtitle">

        , United States                    </a></h4>
    <h4><a href="/agency/6657554/profile/the-annex" class="b-search_result__link--competency">
        Full Service,
        Digital,
        More...
    </a></h4>
  </div>
</div>
"""


def test_parse_adforum_listing_extracts_fields():
    recs = dp.parse_adforum_listing(ADFORUM_HTML)
    assert [r.company for r in recs] == ["Worldwide Partners, Inc.", "David&Goliath", "The Annex"]

    a = recs[0]
    assert a.location == "Denver, United States"
    assert a.industries == "Full Service, Digital, Social Media, Experiential"   # "More..." dropped
    assert a.source_url == "https://www.adforum.com/agency/9394/profile/worldwide-partners-inc"
    assert a.website == "" and a.employees == ""        # only on the profile page

    assert recs[1].location == "El Segundo, United States"
    assert recs[1].industries == "Full Service"
    assert recs[2].location == "United States"           # empty city handled


def test_adforum_total_results():
    assert dp.adforum_total_results(ADFORUM_HTML) == 7969
    assert dp.adforum_total_results("<html>no count</html>") is None


def test_adforum_dedup_key_uses_name_and_location():
    recs = dp.parse_adforum_listing(ADFORUM_HTML)
    # No website on the listing, so identity falls back to name|location.
    assert recs[0].dedup_key() == "worldwide partners, inc.|denver, united states"


def test_make_adforum_source_drives_engine_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)

    def fake_fetch(url, timeout=15.0):
        return (ADFORUM_HTML if "page=" not in url else "<html></html>"), True
    monkeypatch.setattr(dp, "_fetch", fake_fetch)

    conn = dbm.connect(str(tmp_path / "af.db"))
    dbm.init_db(conn)
    src = dp.make_adforum_source("https://www.adforum.com/agency/search?location=country_strkey:COU149")
    summary = dc.run_crawl(conn, "adforum", src)

    assert summary["outcome"] == "complete"
    assert summary["records_new"] == 3
    assert dbm.count_agencies(conn, "adforum") == 3
    names = {r["company"] for r in dbm.list_agencies(conn, "adforum")}
    assert "Worldwide Partners, Inc." in names and "The Annex" in names

    # Re-run resumes/refreshes without duplicating.
    dc.run_crawl(conn, "adforum", src, reset=True)
    assert dbm.count_agencies(conn, "adforum") == 3


def test_offline_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "af.db"))
    dbm.init_db(conn)
    src = dp.make_adforum_source("https://www.adforum.com/agency/search")
    summary = dc.run_crawl(conn, "adforum", src)
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "adforum") == 0
