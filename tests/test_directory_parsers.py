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


# --------------------------------------------------------------------------- #
# DesignRush  (all six fields live on the listing page; no profile sub-fetch)
# --------------------------------------------------------------------------- #
# A faithful slice of a real DesignRush /agency/<category>/us page: the count
# header, the paginator (reports the last page directly), two agency cards, and a
# non-agency "help box" that must be skipped (it has no data-agency-name).
DESIGNRUSH_HTML = """
<mark class="results-count"><span>8,941 Companies</span></mark>
<div class="agency-list">
  <article class="item-box agency-list-help-box">
    <div class="item-description">Need help choosing? Talk to an advisor.</div>
  </article>
  <article class="item-box js-agency-item" data-agency-id="17094"
           data-agency-name="Funnel Boost Media"
           data-gtm-agency-category="digital-marketing">
    <a class="gtm-agency-profile-link" href="https://www.designrush.com/agency/profile/funnel-boost-media">Funnel Boost Media</a>
    <a class="visit gtm-name gtm-agency-website-link" href="https://www.funnelboostmedia.net/?utm_source=designrush&amp;utm_medium=referral">Visit Website</a>
    <div class="agency-info-item i-region"><i class="icon"></i><span><span>San Antonio,</span> Texas</span></div>
    <div class="agency-info-item i-employees"><i class="icon"></i><span>50 - 99</span></div>
    <div class="item-description"><p>Funnel Boost Media is a digital marketing agency focused on SEO &amp; PPC.</p></div>
    <div class="item-services">
      <ul class="inner-tags inner-tags--services">
        <li><span>Search Engine Optimization</span></li>
        <li><span>PPC</span></li>
        <li><span>Web Design</span></li>
      </ul>
    </div>
  </article>
  <article class="item-box js-agency-item" data-agency-id="20531"
           data-agency-name="SmartSites"
           data-gtm-agency-category="digital-marketing">
    <a class="gtm-agency-profile-link" href="/agency/profile/smartsites">SmartSites</a>
    <a class="visit gtm-agency-website-link" href="https://www.smartsites.com/">Visit Website</a>
    <div class="agency-info-item i-region"><span><span>Paramus,</span> New Jersey</span></div>
    <div class="agency-info-item i-employees"><span>100 - 249</span></div>
    <div class="item-description">SmartSites is a full-service digital marketing agency.</div>
    <div class="item-services">
      <ul class="inner-tags inner-tags--services">
        <li><span>Digital Marketing</span></li>
        <li><span>SEO</span></li>
      </ul>
    </div>
  </article>
</div>
<nav id="paginator" data-count="of 179"><a href="?page=2">2</a></nav>
"""


def test_parse_designrush_listing_extracts_all_six_fields():
    recs = dp.parse_designrush_listing(DESIGNRUSH_HTML)
    # The help box (no data-agency-name) is skipped.
    assert [r.company for r in recs] == ["Funnel Boost Media", "SmartSites"]

    a = recs[0]
    assert a.website == "https://www.funnelboostmedia.net"          # utm query dropped
    assert a.employees == "50 - 99"
    assert a.location == "San Antonio, Texas"
    assert a.description.startswith("Funnel Boost Media is a digital marketing agency")
    assert a.industries == "Search Engine Optimization, PPC, Web Design"
    assert a.source_url == "https://www.designrush.com/agency/profile/funnel-boost-media"

    b = recs[1]
    assert b.website == "https://www.smartsites.com"
    assert b.employees == "100 - 249"
    assert b.location == "Paramus, New Jersey"
    assert b.industries == "Digital Marketing, SEO"
    # Relative profile href is resolved against the DesignRush base.
    assert b.source_url == "https://www.designrush.com/agency/profile/smartsites"


def test_designrush_total_results_and_pages():
    assert dp.designrush_total_results(DESIGNRUSH_HTML) == 8941
    assert dp.designrush_total_pages(DESIGNRUSH_HTML) == 179
    assert dp.designrush_total_results("<html>none</html>") is None
    assert dp.designrush_total_pages("<html>none</html>") is None


def test_designrush_dedup_key_uses_profile_url():
    recs = dp.parse_designrush_listing(DESIGNRUSH_HTML)
    assert recs[0].dedup_key() == "www.designrush.com/agency/profile/funnel-boost-media"


def test_make_designrush_source_drives_engine_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)

    # Page 1 returns the two cards; the paginator says "of 179", but page 2
    # comes back empty here so the crawl ends cleanly without 179 fetches.
    def fake_fetch(url, timeout=15.0):
        return (DESIGNRUSH_HTML if "page=" not in url else "<html></html>"), True
    monkeypatch.setattr(dp, "_fetch", fake_fetch)

    conn = dbm.connect(str(tmp_path / "dr.db"))
    dbm.init_db(conn)
    src = dp.make_designrush_source("https://www.designrush.com/agency/digital-marketing/us")
    summary = dc.run_crawl(conn, "designrush", src)

    assert summary["outcome"] == "complete"
    assert summary["records_new"] == 2
    assert dbm.count_agencies(conn, "designrush") == 2
    rows = {r["company"]: r for r in dbm.list_agencies(conn, "designrush")}
    assert rows["Funnel Boost Media"]["employees"] == "50 - 99"
    assert rows["SmartSites"]["location"] == "Paramus, New Jersey"

    # Re-run resets and re-sweeps without duplicating.
    dc.run_crawl(conn, "designrush", src, reset=True)
    assert dbm.count_agencies(conn, "designrush") == 2


def test_designrush_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "dr.db"))
    dbm.init_db(conn)
    src = dp.make_designrush_source("https://www.designrush.com/agency/digital-marketing/us")
    summary = dc.run_crawl(conn, "designrush", src)
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "designrush") == 0
