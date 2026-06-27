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


# --------------------------------------------------------------------------- #
# 4A's agency *profile* pages (server-rendered WordPress; all six fields).
# The search that lists them is login/JS-walled, so the engine crawls a
# supplied list of profile URLs rather than self-enumerating.
# --------------------------------------------------------------------------- #
# A trimmed-but-faithful slice of a real 4A's /agency-profile/ page (&Barr).
AAAA_PROFILE_HTML = """
<meta property="og:url" content="https://www.aaaa.org/agency-profile/a4O5Y000001ukuQ/barr/">
<div class="module full-width-drawer style--multi-button"><div class="module__wrap font-color--white background--primary-two py-4"><div class="wrapper">
<h1 class="font-color--white" style="padding-bottom:10px;">&amp;Barr</h1>
<p>Last Modified: 06-18-2026</p>
<p><a href="http://www.andbarr.co">http://www.andbarr.co</a><br/>Ownership: Privately Held<br/>Size: 51-100</p>
</div></div>
<div class="module__wrap py-4"><div class="wrapper">
<h2>Overview</h2><h3>Company Summary</h3><p>&amp;Barr is a full-service advertising agency providing integrated services, including branding; creative; and public relations. Celebrating more than 69 years in business, &amp;Barr&#8217;s headquarters is in Orlando, Fla.</p>
<div class="sp-3-col"><h3>Contact</h3><p>600 East Washington St.<br/>Orlando, FL 32801-2938<br/>P: 407-849-0100<br/>F: 407-849-0817</p></div>
<h2>Industry Experience</h2><p>Media | publishing</br>Agriculture</br>Financial services | investments</br>Travel | airlines</br>Restaurants</br></p>
</div></div></div>
"""


def test_parse_aaaa_profile_extracts_all_six_fields():
    rec = dp.parse_aaaa_profile(AAAA_PROFILE_HTML)
    assert rec.company == "&Barr"
    assert rec.website == "http://www.andbarr.co"
    assert rec.employees == "51-100"                       # "Size:" in the header
    assert rec.location == "Orlando, FL"                   # city/state, ZIP dropped
    assert rec.description.startswith("&Barr is a full-service advertising agency")
    assert rec.industries == ("Media | publishing, Agriculture, "
                              "Financial services | investments, Travel | airlines, Restaurants")
    assert rec.source_url == "https://www.aaaa.org/agency-profile/a4O5Y000001ukuQ/barr/"


def test_aaaa_profile_dedup_key_uses_profile_url():
    rec = dp.parse_aaaa_profile(AAAA_PROFILE_HTML)
    assert rec.dedup_key() == "www.aaaa.org/agency-profile/a4o5y000001ukuq/barr"


def test_parse_aaaa_profile_returns_none_when_not_a_profile():
    assert dp.parse_aaaa_profile("<html><body>no agency here</body></html>") is None


def test_make_aaaa_source_walks_url_list_through_engine(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    monkeypatch.setattr(dp, "_fetch", lambda url, timeout=15.0: (AAAA_PROFILE_HTML, True))

    conn = dbm.connect(str(tmp_path / "aaaa.db"))
    dbm.init_db(conn)
    # Two URLs, but both resolve to the same agency here → dedup collapses them.
    urls = ["https://www.aaaa.org/agency-profile/a4O5Y000001ukuQ/barr/",
            "https://www.aaaa.org/agency-profile/a4O5Y000001ukuQ/barr/"]
    summary = dc.run_crawl(conn, "aaaa_directory", dp.make_aaaa_source(urls))

    assert summary["outcome"] == "complete"
    assert summary["pages_done"] == 2          # both URLs visited
    assert dbm.count_agencies(conn, "aaaa_directory") == 1   # &Barr stored once
    row = dbm.list_agencies(conn, "aaaa_directory")[0]
    assert row["employees"] == "51-100" and row["location"] == "Orlando, FL"


def test_aaaa_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "aaaa.db"))
    dbm.init_db(conn)
    src = dp.make_aaaa_source(["https://www.aaaa.org/agency-profile/x/y/"])
    summary = dc.run_crawl(conn, "aaaa_directory", src)
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "aaaa_directory") == 0


# --------------------------------------------------------------------------- #
# Cannes Lions / lovethework.com ("The Work" award archive; Next.js flight JSON).
# Not an agency directory — the archive of award-WINNING campaigns — so each
# record is one credited agency (no website/employees/location; the award level,
# campaign, brand and sector are what the source actually states).
# --------------------------------------------------------------------------- #
# A faithful slice of a real lovethework winners page: the flight chunk whose
# searchResults.documents carry the entries. Covers inline enrichmentData, the
# supportText "BRAND, AGENCY" fallback (empty contributors), and a deferred
# enrichmentData ref ("$3e") that falls back to contributors + tags. raw string:
# the flight payload is escaped JSON, so the backslashes must stay literal.
LOVETHEWORK_HTML = r'''<script>self.__next_f.push([1,"29:[\"$\",\"$L2e\",null,{\"initialSearchResultsCollectionItems\":[],\"searchResults\":{\"totalCount\": 1464, \"pageSize\": 24, \"pageNumber\": 1, \"documents\": [{\"contentId\": \"781857\", \"contentType\": \"Entry\", \"title\": \"CAN I GET A SIX PACK QUICKLY?\", \"body\": \"$2f\", \"enrichmentData\": \"{\\\"description\\\": \\\"...\\\", \\\"mediaTag\\\": {\\\"awardLevel\\\": \\\"grandprix\\\", \\\"festivalName\\\": \\\"Cannes Lions\\\"}, \\\"slug\\\": \\\"can-i-get-a-six-pack-quickly-781857\\\", \\\"subText\\\": \\\"Consumer Services/Business to Business\\\", \\\"supportText\\\": \\\"CLAUDE, MOTHER\\\"}\", \"contributors\": [{\"id\": \"a\", \"name\": \"MOTHER\", \"type\": \"Agency\"}], \"tags\": [{\"level1\": \"Trophies\", \"level2\": \"Award level\", \"level3\": \"Grand Prix\"}]}, {\"contentId\": \"781858\", \"contentType\": \"Entry\", \"title\": \"CHALLENGER\", \"body\": \"$30\", \"enrichmentData\": \"{\\\"mediaTag\\\": {\\\"awardLevel\\\": \\\"gold\\\", \\\"festivalName\\\": \\\"Cannes Lions\\\"}, \\\"slug\\\": \\\"challenger-781858\\\", \\\"subText\\\": \\\"Challenger Brand\\\", \\\"supportText\\\": \\\"CLAUDE, MOTHER\\\"}\", \"contributors\": [{\"id\": \"a\", \"name\": \"MOTHER\", \"type\": \"Agency\"}], \"tags\": []}, {\"contentId\": \"781900\", \"contentType\": \"Entry\", \"title\": \"YOUR WAY OUT\", \"body\": \"$31\", \"enrichmentData\": \"{\\\"mediaTag\\\": {\\\"awardLevel\\\": \\\"gold\\\"}, \\\"slug\\\": \\\"your-way-out-781900\\\", \\\"subText\\\": \\\"Market Disruption\\\", \\\"supportText\\\": \\\"COINBASE, ISLE OF ANY\\\"}\", \"contributors\": [], \"tags\": []}, {\"contentId\": \"780570\", \"contentType\": \"Entry\", \"title\": \"L’ULTIMO UOMO REALE\", \"body\": \"$32\", \"enrichmentData\": \"$3e\", \"contributors\": [{\"id\": \"c\", \"name\": \"Team One Advertising\", \"type\": \"Agency\"}], \"tags\": [{\"level1\": \"Trophies\", \"level2\": \"Award level\", \"level3\": \"Silver\"}, {\"level1\": \"Lions Award Category\", \"level2\": \"Online Film: Sectors\", \"level3\": \"B01: Consumer Goods\"}]}]}}]\n"])</script>'''


def test_parse_lovethework_extracts_award_winning_agencies():
    recs = dp.parse_lovethework_entries(LOVETHEWORK_HTML)
    by = {r.company: r for r in recs}
    assert set(by) == {"MOTHER", "ISLE OF ANY", "Team One Advertising"}  # MOTHER twice
    assert len(recs) == 4
    # inline enrichmentData: agency from contributors, award + brand + sector
    first = next(r for r in recs if r.description.startswith("Cannes Lions Grand Prix"))
    assert first.company == "MOTHER"
    assert first.industries == "Consumer Services/Business to Business"
    assert "CAN I GET A SIX PACK QUICKLY?" in first.description and "for CLAUDE" in first.description
    # empty contributors: agency taken from the "BRAND, AGENCY" supportText tail
    assert by["ISLE OF ANY"].industries == "Market Disruption"
    # deferred enrichmentData ref: falls back to contributors + tags
    team = by["Team One Advertising"]
    assert team.description.startswith("Cannes Lions Silver")
    assert team.industries == "Consumer Goods"          # "B01: " category code stripped
    # award credits carry no contact fields — recorded honestly as blank
    assert first.website == "" and first.employees == "" and first.location == ""


def test_lovethework_total_pages_from_reported_count():
    assert dp.lovethework_total_pages(LOVETHEWORK_HTML) == 61   # ceil(1464 / 24)


def test_lovethework_dedup_collapses_repeat_winners():
    # No source_url, so dedup falls back to the agency name: an agency that wins
    # more than once collapses to a single row.
    recs = dp.parse_lovethework_entries(LOVETHEWORK_HTML)
    mothers = [r for r in recs if r.company == "MOTHER"]
    assert len(mothers) == 2
    assert mothers[0].dedup_key() == mothers[1].dedup_key() == "mother|"


def test_make_lovethework_source_drives_engine_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    # Page 1 has the entries; page 2 comes back empty so the crawl ends cleanly
    # without fetching all 61 reported pages.
    def fake_fetch(url, timeout=15.0):
        return (LOVETHEWORK_HTML if "page=" not in url else "<html></html>"), True
    monkeypatch.setattr(dp, "_fetch", fake_fetch)

    conn = dbm.connect(str(tmp_path / "ltw.db"))
    dbm.init_db(conn)
    src = dp.make_lovethework_source(dp._LTW_BASE)
    summary = dc.run_crawl(conn, "canneslions", src)

    assert summary["outcome"] == "complete"
    assert dbm.count_agencies(conn, "canneslions") == 3      # MOTHER deduped
    rows = {r["company"]: r for r in dbm.list_agencies(conn, "canneslions")}
    assert "Team One Advertising" in rows and "ISLE OF ANY" in rows


def test_lovethework_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "ltw.db"))
    dbm.init_db(conn)
    summary = dc.run_crawl(conn, "canneslions", dp.make_lovethework_source(dp._LTW_BASE))
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "canneslions") == 0


# --------------------------------------------------------------------------- #
# Awwwards directory (server-rendered HTML; one .card-directory per agency).
# Company / website / location + the agency's trophy counts are on the listing;
# employees / description / industries are not, so they stay blank (the awards
# summary becomes the description). Promoted .card-directory-sp cards duplicate
# real grid entries and are skipped.
# --------------------------------------------------------------------------- #
# A faithful slice: the header count, one promoted (sp) card that must be
# skipped, and two real grid cards (one with a zero SOTY that must be dropped).
AWWWARDS_HTML = """
<div class="header-grid__left"><strong>1965</strong> professionals waiting.</div>
<div class="card-directory-sp">
    <div class="card-directory-sp__left"><p>International</p>
        <h2 class="card-directory-sp__title"><a href="/clay/">Clay</a></h2></div>
    <div class="card-directory-sp__footer"><div class="card-directory-sp__left">
        <a href="https://clay.global" class="url">clay.global</a></div>
        <div class="card-directory-sp__right">14 awards</div></div>
</div>
<ul class="grid-cards js-ajax-entries">
<li>
    <div class="card-directory">
        <div class="card-directory__cover"><a href="/locomotive/"><img class="card-directory__media"></a></div>
        <div class="card-directory__content"><div class="card-directory__header"><div class="users-credits">
            <figure class="avatar-name"><a class="avatar-name__link" href="/locomotive/">
                <figcaption class="avatar-name__name"><strong>Locomotive</strong><sup>PRO</sup></figcaption>
            </a></figure></div></div>
        <ul class="card-directory__list">
            <li><div class="card-directory__section"><strong>Location</strong></div><div>Canada</div></li>
            <li><div class="card-directory__section"><strong>Website</strong></div>
                <div><a href="https://locomotive.ca" rel="nofollow noopener noreferrer" target="_blank">locomotive.ca</a></div></li>
            <li><div class="card-directory__section"><strong>Awards</strong></div>
                <div class="c-boxes-score">
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>HM</strong></div>
                        <div class="box-score__bottom"><strong>131</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTD</strong></div>
                        <div class="box-score__bottom"><strong>91</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTM</strong></div>
                        <div class="box-score__bottom"><strong>4</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTY</strong></div>
                        <div class="box-score__bottom"><strong>1</strong></div></div>
                </div></li>
        </ul></div>
    </div>
</li>
<li>
    <div class="card-directory">
        <div class="card-directory__cover"><a href="/adoratorio.studio/"><img class="card-directory__media"></a></div>
        <div class="card-directory__content"><div class="card-directory__header"><div class="users-credits">
            <figure class="avatar-name"><a class="avatar-name__link" href="/adoratorio.studio/">
                <figcaption class="avatar-name__name"><strong>Adoratorio Studio</strong><sup>PRO</sup></figcaption>
            </a></figure></div></div>
        <ul class="card-directory__list">
            <li><div class="card-directory__section"><strong>Location</strong></div><div>Italy</div></li>
            <li><div class="card-directory__section"><strong>Website</strong></div>
                <div><a href="https://adoratorio.com/" rel="nofollow noopener noreferrer" target="_blank">adoratorio.com</a></div></li>
            <li><div class="card-directory__section"><strong>Awards</strong></div>
                <div class="c-boxes-score">
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>HM</strong></div>
                        <div class="box-score__bottom"><strong>65</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTD</strong></div>
                        <div class="box-score__bottom"><strong>44</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTM</strong></div>
                        <div class="box-score__bottom"><strong>1</strong></div></div>
                    <div class="box-score box-score--small"><div class="box-score__top"><strong>SOTY</strong></div>
                        <div class="box-score__bottom"><strong>0</strong></div></div>
                </div></li>
        </ul></div>
    </div>
</li>
</ul>
"""


def test_parse_awwwards_listing_extracts_card_fields():
    recs = dp.parse_awwwards_listing(AWWWARDS_HTML)
    assert len(recs) == 2                                   # the .sp promo card is skipped
    loco = recs[0]
    assert loco.company == "Locomotive"
    assert loco.website == "https://locomotive.ca"
    assert loco.location == "Canada"
    assert loco.source_url == "https://www.awwwards.com/locomotive/"
    # awards summary becomes the description; employees/industries stay blank
    assert loco.description == ("Awwwards: 131 Honorable Mentions, 91 Sites of the Day, "
                                "4 Sites of the Month, 1 Sites of the Year")
    assert loco.employees == "" and loco.industries == ""
    # a zero trophy count is dropped from the summary
    assert recs[1].description == ("Awwwards: 65 Honorable Mentions, 44 Sites of the Day, "
                                   "1 Sites of the Month")


def test_awwwards_total_and_pages():
    assert dp.awwwards_total_results(AWWWARDS_HTML) == 1965
    assert dp.make_awwwards_source  # registered factory exists


def test_awwwards_dedup_key_uses_profile_url():
    rec = dp.parse_awwwards_listing(AWWWARDS_HTML)[0]
    assert rec.dedup_key() == "www.awwwards.com/locomotive"


def test_make_awwwards_source_drives_engine_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    # Page 1 returns the cards; the count says 1965 (82 pages), but page 2 comes
    # back empty here so the crawl ends cleanly without 82 fetches.
    def fake_fetch(url, timeout=15.0):
        return (AWWWARDS_HTML if "page=" not in url else "<html></html>"), True
    monkeypatch.setattr(dp, "_fetch", fake_fetch)

    conn = dbm.connect(str(tmp_path / "aw.db"))
    dbm.init_db(conn)
    src = dp.make_awwwards_source("https://www.awwwards.com/directory/")
    summary = dc.run_crawl(conn, "awwwards", src)

    assert summary["outcome"] == "complete"
    assert summary["records_new"] == 2
    rows = {r["company"]: r for r in dbm.list_agencies(conn, "awwwards")}
    assert rows["Locomotive"]["location"] == "Canada"
    assert rows["Adoratorio Studio"]["website"] == "https://adoratorio.com/"


def test_awwwards_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "aw.db"))
    dbm.init_db(conn)
    summary = dc.run_crawl(conn, "awwwards", dp.make_awwwards_source("https://www.awwwards.com/directory/"))
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "awwwards") == 0


# --------------------------------------------------------------------------- #
# The Drum ranked-list ("Hotlist") page. The whole ranking is embedded as
# HTML-entity-encoded JSON in <td-rankings-list :list-data="[...]"> — one page,
# no pagination. Each entry has company / location / editorial + a profile URL;
# there's no outbound website or employee count, so those stay blank.
# --------------------------------------------------------------------------- #
# A faithful slice: the data attribute with two real entries (one with an empty
# location, like several real rows), entity-encoded exactly as The Drum emits it.
THEDRUM_HTML = (
    '<td-rankings-list list-type="company" pagination="" :items-per-page="20" '
    ':list-data="[{&quot;companyName&quot;:&quot;Bader Rutter&quot;,&quot;url&quot;:&quot;\\/profile\\/bader-rutter&quot;,'
    '&quot;location&quot;:&quot;Milwaukee County United States&quot;,&quot;yearFounded&quot;:1973,'
    '&quot;topExecutive&quot;:&quot;David Jordan&quot;,'
    '&quot;editorial&quot;:&quot;Bader Rutter is an employee-owned US B2B agency known for agriculture and food.&quot;},'
    '{&quot;companyName&quot;:&quot;Marketbridge&quot;,&quot;url&quot;:&quot;\\/profile\\/marketbridge&quot;,'
    '&quot;location&quot;:&quot; United States&quot;,&quot;yearFounded&quot;:1991,'
    '&quot;topExecutive&quot;:&quot;Bob Ray&quot;,'
    '&quot;editorial&quot;:&quot;Marketbridge is a data-driven B2B growth consultancy.&quot;}]"'
    '></td-rankings-list>'
)


def test_parse_thedrum_list_extracts_entries():
    recs = dp.parse_thedrum_list(THEDRUM_HTML)
    assert len(recs) == 2
    bader = recs[0]
    assert bader.company == "Bader Rutter"
    assert bader.location == "Milwaukee County United States"
    assert bader.source_url == "https://www.thedrum.com/profile/bader-rutter"
    assert bader.description.startswith("Bader Rutter is an employee-owned US B2B agency")
    # no outbound website / employee count on the Drum list — left blank, not faked
    assert bader.website == "" and bader.employees == "" and bader.industries == ""
    # a leading-space location is normalized
    assert recs[1].location == "United States"


def test_parse_thedrum_list_returns_empty_without_list_data():
    assert dp.parse_thedrum_list("<html><body>no list here</body></html>") == []


def test_thedrum_dedup_key_uses_profile_url():
    rec = dp.parse_thedrum_list(THEDRUM_HTML)[0]
    assert rec.dedup_key() == "www.thedrum.com/profile/bader-rutter"


def test_make_thedrum_source_drives_engine_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    monkeypatch.setattr(dp, "_fetch", lambda url, timeout=15.0: (THEDRUM_HTML, True))

    conn = dbm.connect(str(tmp_path / "td.db"))
    dbm.init_db(conn)
    src = dp.make_thedrum_source("https://www.thedrum.com/b2b-agencies")
    summary = dc.run_crawl(conn, "thedrum", src)

    assert summary["outcome"] == "complete"
    assert summary["pages_done"] == 1          # whole list is on one page
    assert dbm.count_agencies(conn, "thedrum") == 2
    rows = {r["company"]: r for r in dbm.list_agencies(conn, "thedrum")}
    assert rows["Marketbridge"]["source_url"] == "https://www.thedrum.com/profile/marketbridge"


def test_thedrum_source_reports_error_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: False)
    conn = dbm.connect(str(tmp_path / "td.db"))
    dbm.init_db(conn)
    summary = dc.run_crawl(conn, "thedrum", dp.make_thedrum_source("https://www.thedrum.com/b2b-agencies"))
    assert summary["outcome"] == "error"
    assert dbm.count_agencies(conn, "thedrum") == 0


# --------------------------------------------------------------------------- #
# parse_listing dispatch — turns a pasted page into records for DB ingest.
# --------------------------------------------------------------------------- #
def test_parse_listing_dispatches_by_source():
    drum = dp.parse_listing("thedrum", THEDRUM_HTML)
    assert [r.company for r in drum] == ["Bader Rutter", "Marketbridge"]
    aw = dp.parse_listing("awwwards", AWWWARDS_HTML)
    assert aw and aw[0].company == "Locomotive"


def test_parse_listing_aaaa_single_profile():
    recs = dp.parse_listing("aaaa", AAAA_PROFILE_HTML)
    assert len(recs) == 1 and recs[0].company == "&Barr"


def test_parse_listing_unknown_or_empty_is_safe():
    assert dp.parse_listing("nope", THEDRUM_HTML) == []
    assert dp.parse_listing("thedrum", "") == []


# --------------------------------------------------------------------------- #
# Fetch failure reporting — the crawl says WHY (HTTP 403 / unreachable / ...).
# --------------------------------------------------------------------------- #
def test_fetch_records_http_error_reason(monkeypatch):
    import urllib.error

    def boom(req, timeout=15.0):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, None)
    monkeypatch.setattr(dp.urllib.request, "urlopen", boom)
    text, ok = dp._fetch("https://example.com/x")
    assert ok is False and text == ""
    assert dp.last_fetch_error() == "HTTP 403"


def test_source_surfaces_fetch_reason_in_detail(monkeypatch):
    monkeypatch.setattr(dp, "scrape_enabled", lambda: True)
    monkeypatch.setattr(dp, "_fetch", lambda url, timeout=15.0: ("", False))
    monkeypatch.setattr(dp, "_LAST_FETCH_ERROR", "HTTP 403", raising=False)
    res = dp.make_adforum_source("https://www.adforum.com/x")(1)
    assert res.ok is False and "403" in res.detail


def test_fetch_sends_browser_user_agent(monkeypatch):
    # Directories 403 self-identified bots; the crawler must present as a browser.
    captured = {}

    class _Resp:
        headers = type("H", (), {"get_content_charset": staticmethod(lambda: "utf-8")})()
        def read(self): return b"<html>ok</html>"
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_urlopen(req, timeout=15.0):
        captured["ua"] = req.get_header("User-agent")
        captured["accept"] = req.get_header("Accept")
        return _Resp()
    monkeypatch.setattr(dp.urllib.request, "urlopen", fake_urlopen)
    text, ok = dp._fetch("https://www.adforum.com/x")
    assert ok is True
    assert "Mozilla/5.0" in captured["ua"] and "Chrome" in captured["ua"]
    assert "ChordentialDirectoryBot" not in captured["ua"]
    assert captured["accept"]
