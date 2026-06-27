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


# A trimmed-but-faithful AdForum agency *profile* page (website + description live
# here; AdForum publishes no employee count, so that field stays blank).
PROFILE_HTML = """
<div class="af-company-subtitle">Denver, United States</div>
<h3 class="contact__title--site"><strong>Website:</strong>&nbsp;
  <a href="http://www.worldwidepartners.com" target="_blank" class="contact__link--site">www.worldwidepartners.com</a>
</h3>
<div class="card card-block agency-description">
  <h2 class="agency-description__title">About Us</h2>
  <div class="agency-description__text"><p>Worldwide Partners Inc (WPI) is the world's most collaborative agency network.<span> </span></p></div>
</div>
"""


def test_adforum_dedup_key_uses_profile_url():
    recs = dp.parse_adforum_listing(ADFORUM_HTML)
    # Profile URL is the stable identity (won't change when the row is enriched).
    assert recs[0].dedup_key() == "www.adforum.com/agency/9394/profile/worldwide-partners-inc"


def test_parse_adforum_profile():
    prof = dp.parse_adforum_profile(PROFILE_HTML)
    assert prof["website"] == "http://www.worldwidepartners.com"
    assert prof["description"].startswith("Worldwide Partners Inc (WPI) is the world")


def test_enricher_fills_website_and_description(monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    monkeypatch.setattr(dp, "_fetch", lambda url, timeout=15.0: (PROFILE_HTML, True))
    enrich = dp.make_adforum_enricher()
    rec = dc.AgencyRecord(company="Worldwide Partners, Inc.",
                          source_url="https://www.adforum.com/agency/9394/profile/worldwide-partners-inc")
    out = enrich(rec)
    assert out.website == "http://www.worldwidepartners.com"
    assert out.description.startswith("Worldwide Partners Inc (WPI)")
    assert out.employees == ""        # AdForum doesn't publish headcount


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


def test_engine_with_enricher_fills_all_available_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)

    def fake_fetch(url, timeout=15.0):
        if "/profile/" in url:
            return PROFILE_HTML, True
        if "page=" in url:
            return "<html></html>", True
        return ADFORUM_HTML, True
    monkeypatch.setattr(dp, "_fetch", fake_fetch)

    conn = dbm.connect(str(tmp_path / "af.db"))
    dbm.init_db(conn)
    src = dp.make_adforum_source("https://www.adforum.com/agency/search?location=country_strkey:COU149")
    summary = dc.run_crawl(conn, "adforum", src, enrich=dp.make_adforum_enricher())

    assert summary["outcome"] == "complete" and summary["records_new"] == 3
    rows = {r["company"]: r for r in dbm.list_agencies(conn, "adforum")}
    wp = rows["Worldwide Partners, Inc."]
    assert wp["website"] == "http://www.worldwidepartners.com"      # from profile
    assert wp["description"].startswith("Worldwide Partners Inc")    # from profile
    assert wp["location"] == "Denver, United States"                # from listing
    assert wp["industries"].startswith("Full Service")              # from listing
    assert wp["employees"] == ""                                    # not on AdForum


def test_offline_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "af.db"))
    dbm.init_db(conn)
    src = dp.make_adforum_source("https://www.adforum.com/agency/search")
    summary = dc.run_crawl(conn, "adforum", src)
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "adforum") == 0
