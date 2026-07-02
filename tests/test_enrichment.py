"""Company Enrichment Engine. The engine reads an agency's own website like a
person — homepage, then discover & classify the navigation by MEANING, then run
one micro-agent per concept. Tests are fully offline: a fake ``fetch`` serves a
small fixture site whose pages are deliberately named oddly (/what-we-do,
/our-work, /team, /sectors, /where-we-are, /join-us, /insights, /say-hello) to
prove concept-mapping is robust to naming.
"""

import pytest

from chordential_oia.web import db as dbm
from chordential_oia.web import enrichment as en


# --------------------------------------------------------------------------- #
# A faithful little agency site with non-obvious page names.
# --------------------------------------------------------------------------- #
SITE = {
    "https://northwind.example/": """<html><head>
        <title>Northwind — Independent Studio</title>
        <meta name="description" content="Northwind is an independent brand and digital studio.">
        </head><body><nav>
            <a href="/about">Who We Are</a>
            <a href="/what-we-do">What We Do</a>
            <a href="/our-work">Our Work</a>
            <a href="/our-clients">Our Clients</a>
            <a href="/sectors">Sectors</a>
            <a href="/where-we-are">Studios</a>
            <a href="/team">Meet the Team</a>
            <a href="/recognition">Recognition</a>
            <a href="/join-us">Work With Us</a>
            <a href="/insights">Insights</a>
            <a href="/say-hello">Say Hello</a>
            <a href="https://www.linkedin.com/company/northwind">LinkedIn</a>
            <a href="https://twitter.com/northwind">Twitter</a>
        </nav></body></html>""",
    "https://northwind.example/about": """<head>
        <meta property="og:description" content="We are a 40-person studio established in 2009, building brands and products for ambitious clients worldwide.">
        </head><body><h1>Who We Are</h1>
        <p>Northwind is an independent studio established in 2009.</p></body>""",
    "https://northwind.example/what-we-do": """<body><h2>What We Do</h2><ul>
        <li>Brand Strategy</li><li>Identity Design</li><li>Web Design</li>
        <li>Web Development</li><li>Motion</li></ul></body>""",
    "https://northwind.example/our-work": """<body><h2>Selected Work</h2>
        <a href="/our-work/aurora-rebrand">AURORA Rebrand</a>
        <a href="/our-work/vance-athletic-site">Vance Athletic Website</a>
        <a href="/about">About</a></body>""",
    "https://northwind.example/our-clients": """<body><h2>Our Clients</h2>
        <img src="/l/aurora.svg" alt="AURORA logo">
        <img src="/l/vance.svg" alt="Vance Athletic">
        <img src="/l/meridian.svg" alt="Meridian Bank">
        <img src="/l/spacer.gif" alt="Logo"></body>""",
    "https://northwind.example/sectors": """<body><h2>Sectors</h2><ul>
        <li>Technology</li><li>Healthcare</li><li>Finance</li></ul></body>""",
    "https://northwind.example/where-we-are": """<body><h2>Studios</h2>
        <address>120 Main St, Portland, OR 97201</address>
        <address>5 Hoxton Sq, London N1 6NU</address></body>""",
    "https://northwind.example/team": """<body><h2>Leadership</h2>
        <div><h3>Dana Reed</h3><p>Founder &amp; CEO</p></div>
        <div><h3>Sam Okafor</h3><p>Chief Creative Officer</p></div>
        <div><h3>Brandmark</h3><p>An image caption, not a person</p></div></body>""",
    "https://northwind.example/recognition": """<body><h2>Recognition</h2><ul>
        <li>D&amp;AD Wood Pencil 2023</li><li>Awwwards Site of the Day</li>
        <li>We hire great people</li></ul></body>""",
    "https://northwind.example/join-us": """<body><h2>Open Positions</h2><ul>
        <li>Senior Designer</li><li>Frontend Engineer</li></ul></body>""",
    "https://northwind.example/insights": """<body><h2>Insights</h2>
        <a href="/insights/the-future-of-brand">The Future of Brand Systems</a>
        <a href="/insights/design-ops-2024">Scaling Design Ops in 2024</a></body>""",
    "https://northwind.example/say-hello": """<body><h2>Say Hello</h2>
        <a href="mailto:hello@northwind.example">hello@northwind.example</a>
        <a href="tel:+15035551234">+1 503 555 1234</a>
        <a href="https://twitter.com/northwind">Twitter</a></body>""",
}


def make_fetch(pages, fail_on=None, fail_exc=KeyboardInterrupt):
    """A fake network seam over ``pages`` (trailing-slash tolerant). If ``fail_on``
    is a URL, the first fetch of it raises ``fail_exc`` to simulate a crash —
    KeyboardInterrupt is a BaseException, so the engine does NOT swallow it."""
    state = {"failed": False}

    def fetch(url):
        if fail_on and url == fail_on and not state["failed"]:
            state["failed"] = True
            raise fail_exc("interrupted")
        u = url if url in pages else (url + "/" if url + "/" in pages else url)
        return (pages.get(u, ""), u in pages)
    return fetch


def _seed(tmp_path, website="https://northwind.example", company="Northwind"):
    conn = dbm.connect(str(tmp_path / "enrich.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "manual", {
        "dedup_key": "northwind.example", "company": company, "website": website})
    aid = conn.execute("SELECT id FROM agencies").fetchone()["id"]
    return conn, aid


# --------------------------------------------------------------------------- #
# Concept classification — the robustness layer.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,anchor,concept", [
    ("/about", "", "about"),
    ("/who-we-are", "", "about"),
    ("/services", "", "services"),
    ("/capabilities", "", "services"),
    ("/what-we-do", "What We Do", "services"),
    ("/our-work", "", "work"),
    ("/case-studies", "", "work"),
    ("/our-clients", "Our Clients", "clients"),
    ("/clients", "", "clients"),
    ("/sectors", "", "industries"),
    ("/team", "Meet the Team", "leadership"),
    ("/people", "", "leadership"),
    ("/where-we-are", "Studios", "offices"),
    ("/recognition", "", "awards"),
    ("/insights", "", "news"),
    ("/blog", "", "news"),
    ("/say-hello", "Get in touch", "contact"),
    ("/pricing", "Pricing", None),          # unmapped -> None, never forced
])
def test_classify_link_maps_by_meaning(path, anchor, concept):
    assert en.classify_link("https://x.example" + path, anchor) == concept


def test_classify_prefers_longest_keyword():
    # "work with us" (careers) must beat the bare "work" (portfolio) token.
    assert en.classify_link("https://x.example/work-with-us", "Work With Us") == "careers"
    assert en.classify_link("https://x.example/our-work", "Our Work") == "work"


def test_discover_links_filters_offsite_and_dedupes():
    links = en.discover_links(SITE["https://northwind.example/"],
                              "https://northwind.example")
    by_concept = {c: u for (u, a, c) in links}
    # mapped the oddly-named nav to concepts
    assert by_concept["services"].endswith("/what-we-do")
    assert by_concept["work"].endswith("/our-work")
    assert by_concept["leadership"].endswith("/team")
    assert by_concept["contact"].endswith("/say-hello")
    # off-site social links (linkedin/twitter) are NOT in the same-site map
    assert all("northwind.example" in u for (u, a, c) in links)


# --------------------------------------------------------------------------- #
# Full enrichment — facts extracted and normalized into the profile.
# --------------------------------------------------------------------------- #
def test_enrich_agency_extracts_and_normalizes(tmp_path):
    conn, aid = _seed(tmp_path)
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    assert summary["status"] == "complete"
    p = summary["profile"]

    assert p["founded_year"] == "2009"
    assert p["description"].startswith("We are a 40-person studio")
    assert p["services"] == ["Brand Strategy", "Identity Design", "Web Design",
                             "Web Development", "Motion"]
    assert p["industries"] == ["Technology", "Healthcare", "Finance"]
    assert p["portfolio"] == ["AURORA Rebrand", "Vance Athletic Website"]
    # notable clients come from the dedicated clients page (logo alt text);
    # the generic "Logo" placeholder is filtered out, "AURORA logo" -> "AURORA"
    assert p["clients"] == ["AURORA", "Vance Athletic", "Meridian Bank"]
    assert p["awards"] == ["D&AD Wood Pencil 2023", "Awwwards Site of the Day"]
    assert p["offices"] == ["120 Main St, Portland, OR 97201", "5 Hoxton Sq, London N1 6NU"]
    # the section-header h2 does NOT swallow the first person card
    assert p["leadership"] == [
        {"name": "Dana Reed", "title": "Founder & CEO"},
        {"name": "Sam Okafor", "title": "Chief Creative Officer"}]
    assert p["careers_url"].endswith("/join-us")
    assert p["open_roles"] == ["Senior Designer", "Frontend Engineer"]
    assert [n["title"] for n in p["news"]] == [
        "The Future of Brand Systems", "Scaling Design Ops in 2024"]
    assert p["email"] == "hello@northwind.example"
    assert p["phone"] == "+15035551234"
    assert p["social_links"]["twitter"] == "https://twitter.com/northwind"
    # provenance: which page each concept came from (factual, not inferred)
    assert p["sources"]["services"].endswith("/what-we-do")


def test_persisted_profile_matches_summary(tmp_path):
    conn, aid = _seed(tmp_path)
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    stored = dbm.get_agency_enrichment(conn, aid)
    assert stored["status"] == "complete"
    assert stored["profile"]["services"] == summary["profile"]["services"]


# --------------------------------------------------------------------------- #
# Honesty rule — missing info is left empty, never guessed.
# --------------------------------------------------------------------------- #
def test_missing_info_is_left_empty(tmp_path):
    bare = {"https://bare.example/": "<html><body><h1>Bare Co</h1>"
            "<p>" + "x" * 100 + "</p></body></html>"}
    conn, aid = _seed(tmp_path, website="https://bare.example", company="Bare Co")
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(bare))
    assert summary["status"] == "complete"
    p = summary["profile"]
    # no nav -> no concept pages -> every discovered-only field stays empty
    assert p["services"] == [] and p["industries"] == [] and p["portfolio"] == []
    assert p["clients"] == []
    assert p["leadership"] == [] and p["awards"] == [] and p["offices"] == []
    assert p["founded_year"] == "" and p["careers_url"] == ""
    assert p["sources"] == {}                      # nothing fabricated


# --------------------------------------------------------------------------- #
# Resumability — committed mid-pipeline, resumes from where it stopped.
# --------------------------------------------------------------------------- #
def test_enrichment_resumes_after_interruption(tmp_path):
    conn, aid = _seed(tmp_path)
    # Crash the first run when it reaches the offices page (KeyboardInterrupt is a
    # BaseException, so the engine's per-agent `except Exception` won't swallow it).
    crash = make_fetch(SITE, fail_on="https://northwind.example/where-we-are")
    with pytest.raises(KeyboardInterrupt):
        en.enrich_agency(conn, aid, fetch=crash)

    mid = dbm.get_agency_enrichment(conn, aid)
    assert mid["status"] == "running"
    # earlier agents committed their work before the crash...
    assert "services" in mid["steps_done"] and "industries" in mid["steps_done"]
    assert mid["profile"]["services"]            # already captured
    # ...but offices and everything after it have not run yet.
    assert "offices" not in mid["steps_done"]
    assert mid["profile"]["offices"] == [] and mid["profile"]["email"] == ""

    # Resume with a healthy fetch: it picks up at offices and finishes.
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    assert summary["status"] == "complete"
    assert summary["profile"]["offices"]         # filled on resume
    assert summary["profile"]["email"] == "hello@northwind.example"
    assert summary["profile"]["services"]        # earlier work preserved


def test_reset_reenriches_from_scratch(tmp_path):
    conn, aid = _seed(tmp_path)
    en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE), reset=True)
    assert summary["status"] == "complete"
    assert summary["steps_done"][0] == "discover"   # started over from the homepage


# --------------------------------------------------------------------------- #
# Network gate + bad input.
# --------------------------------------------------------------------------- #
def test_enrich_blocked_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(en, "scrape_enabled", lambda: False)
    conn, aid = _seed(tmp_path)
    summary = en.enrich_agency(conn, aid)            # no fetch + scraping off
    assert summary["status"] == "blocked"
    assert dbm.get_agency_enrichment(conn, aid)["status"] == "blocked"


def test_enrich_errors_without_website(tmp_path):
    conn, aid = _seed(tmp_path, website="")
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    assert summary["status"] == "error"
    assert "website" in summary["detail"]


def test_enrich_errors_when_homepage_unreachable(tmp_path):
    conn, aid = _seed(tmp_path)
    summary = en.enrich_agency(conn, aid, fetch=lambda url: ("", False))
    assert summary["status"] == "error"


def test_enrich_survives_a_crashing_discover_step(tmp_path, monkeypatch):
    # A malformed homepage that makes link discovery itself raise must NOT crash
    # the whole run — before this fix an uncaught exception here killed the worker
    # process, and since the agency was never marked complete/error, the batch
    # re-picked (and re-crashed on) this exact agency every single pass, forever.
    conn, aid = _seed(tmp_path)

    def _boom(html, base_url):
        raise ValueError("malformed markup")

    monkeypatch.setattr(en, "discover_links", _boom)
    summary = en.enrich_agency(conn, aid, fetch=make_fetch(SITE))
    assert summary["status"] == "complete"          # run finished, not crashed
    st = dbm.get_agency_enrichment(conn, aid)
    assert st.get("status") == "complete"            # queue will not re-pick it


# --------------------------------------------------------------------------- #
# Batch runner — enrich the whole Master Company Database, resumably.
# --------------------------------------------------------------------------- #
# A second tiny site so a batch has more than one agency to walk.
SITE2 = {
    "https://southgate.example/": """<html><head><title>Southgate</title></head>
        <body><nav><a href="/capabilities">Capabilities</a>
        <a href="/get-in-touch">Get in touch</a></nav></body></html>""",
    "https://southgate.example/capabilities": """<body><h2>Capabilities</h2><ul>
        <li>Media Planning</li><li>Performance</li></ul></body>""",
    "https://southgate.example/get-in-touch": """<body>
        <a href="mailto:team@southgate.example">Email us</a></body>""",
}


def _seed_many(tmp_path):
    conn = dbm.connect(str(tmp_path / "batch.db"))
    dbm.init_db(conn)
    for key, company, site in [
        ("northwind.example", "Northwind", "https://northwind.example"),
        ("southgate.example", "Southgate", "https://southgate.example"),
    ]:
        dbm.upsert_agency(conn, "manual", {
            "dedup_key": key, "company": company, "website": site})
    return conn


def test_enrich_batch_processes_all_agencies(tmp_path):
    conn = _seed_many(tmp_path)
    pages = {**SITE, **SITE2}
    seen = []
    summary = en.enrich_batch(conn, fetch=make_fetch(pages),
                              on_agency=lambda s: seen.append(s["company"]))
    assert summary["total"] == 2 and summary["completed"] == 2
    assert set(seen) == {"Northwind", "Southgate"}
    rows = {r["company"]: dbm.get_agency_enrichment(conn, r["id"])
            for r in dbm.list_agencies(conn, "manual")}
    assert rows["Southgate"]["profile"]["services"] == ["Media Planning", "Performance"]
    assert rows["Southgate"]["profile"]["email"] == "team@southgate.example"


def test_enrich_batch_resumes_and_skips_completed(tmp_path):
    conn = _seed_many(tmp_path)
    pages = {**SITE, **SITE2}
    en.enrich_batch(conn, fetch=make_fetch(pages))
    # Everything is complete now, so a second pass selects nothing.
    again = en.enrich_batch(conn, fetch=make_fetch(pages))
    assert again["total"] == 0
    # Add a fresh agency; only IT gets processed on the next pass.
    dbm.upsert_agency(conn, "manual", {
        "dedup_key": "southgate.example", "company": "Southgate",
        "website": "https://southgate.example", "industries": "x"})  # update is no-op for status
    dbm.upsert_agency(conn, "manual", {
        "dedup_key": "new.example", "company": "Newco", "website": "https://southgate.example"})
    third = en.enrich_batch(conn, fetch=make_fetch(pages),
                            on_agency=lambda s: None)
    assert third["total"] == 1 and third["results"][0]["company"] == "Newco"


def test_enrich_batch_respects_limit(tmp_path):
    conn = _seed_many(tmp_path)
    summary = en.enrich_batch(conn, fetch=make_fetch({**SITE, **SITE2}), limit=1)
    assert summary["total"] == 1
    # the other agency is still pending
    assert len(dbm.agencies_needing_enrichment(conn, "manual")) == 1


def test_enrich_batch_blocked_when_scraping_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(en, "scrape_enabled", lambda: False)
    conn = _seed_many(tmp_path)
    summary = en.enrich_batch(conn)               # no fetch + scraping off
    assert summary["total"] == 2 and summary["blocked"] == 2 and summary["completed"] == 0


def test_needing_enrichment_skips_no_website_and_errored(tmp_path):
    # Directories like The Drum list no outbound website; those rows can never be
    # enriched, so they must NOT count as awaiting (else they clog the queue and a
    # fixed-size batch makes zero forward progress). An errored row is terminal too.
    conn = dbm.connect(str(tmp_path / "q.db"))
    dbm.init_db(conn)
    dbm.upsert_agency(conn, "thedrum", {            # no website
        "dedup_key": "nosite", "company": "No Site Co", "website": ""})
    dbm.upsert_agency(conn, "awwwards", {           # enrichable
        "dedup_key": "acme.example", "company": "Acme", "website": "https://acme.example"})

    needing = dbm.agencies_needing_enrichment(conn)
    assert [r["company"] for r in needing] == ["Acme"]   # the no-website row is skipped

    # Acme's site is unreachable here -> the pass marks it 'error'; it must then
    # drop out of the queue rather than be retried forever.
    en.enrich_batch(conn, fetch=lambda url, timeout=15.0: ("", False))
    assert dbm.agencies_needing_enrichment(conn) == []


def test_queue_selectors_match_their_counts_and_handle_edge_blobs(tmp_path):
    """The six autonomous-engine queue selectors filter in SQL (not a full-table
    Python scan). This locks the invariant that matters: each selector returns
    exactly the rows its count function counts, AND the SQL LIKE markers treat the
    tricky blob states the same as the old Python logic — a 'blocked' row is still
    retried, a malformed blob is 'not complete', a no-website row is excluded from
    the site-gated queues."""
    import json as _json
    conn = dbm.connect(str(tmp_path / "sel.db"))
    dbm.init_db(conn)

    def mk(name, website, enr=None, dm=None, intel=None):
        dbm.upsert_agency(conn, "s", {"dedup_key": name, "company": name,
                                      "website": website})
        aid = conn.execute("SELECT id FROM agencies WHERE company=?",
                           (name,)).fetchone()["id"]
        if enr is not None:
            dbm.save_agency_enrichment(conn, aid, {"status": enr})
        if dm is not None:
            conn.execute("UPDATE agencies SET dm_json=? WHERE id=?",
                         (_json.dumps({"status": dm}), aid))
        if intel is not None:
            conn.execute("UPDATE agencies SET intel_json=? WHERE id=?",
                         (_json.dumps({"status": intel}), aid))
        conn.commit()
        return aid

    mk("HasSiteNoEnr", "https://a.example")
    mk("NoSite", "")
    mk("Complete", "https://c.example", enr="complete")
    mk("Errored", "https://e.example", enr="error")
    mk("Blocked", "https://b.example", enr="blocked")
    mk("DmDone", "https://d.example", enr="complete", dm="complete")
    mk("IntelDone", "https://j.example", enr="complete", intel="complete")
    bad = mk("Malformed", "https://m.example")
    conn.execute("UPDATE agencies SET enrichment_json='{bad' WHERE id=?", (bad,))
    conn.commit()

    def names(rows):
        return sorted(r["company"] for r in rows)

    # 'blocked' + malformed + not-yet-enriched are enrichable; complete/error/no-site
    # are not. And the selector's length matches the count function exactly.
    enr = dbm.agencies_needing_enrichment(conn)
    assert names(enr) == ["Blocked", "HasSiteNoEnr", "Malformed"]
    assert len(enr) == dbm.count_needing_enrichment(conn)

    # dm: any website whose dm isn't complete/error (independent of enrichment).
    dm = dbm.agencies_needing_decision_makers(conn)
    assert "DmDone" not in names(dm) and "NoSite" not in names(dm)
    assert len(dm) == dbm.count_needing_decision_makers(conn)

    # intel: enrichment complete AND intel not complete.
    intel = dbm.agencies_needing_intelligence(conn)
    assert names(intel) == ["Complete", "DmDone"]
    assert len(intel) == dbm.count_needing_intelligence(conn)

    # signal-scan: enrichment complete (regardless of intel/dm).
    assert names(dbm.agencies_for_signal_scan(conn)) == [
        "Complete", "DmDone", "IntelDone"]
    # score: intelligence complete.
    assert names(dbm.agencies_to_score(conn)) == ["IntelDone"]


def test_start_manual_enrich_is_non_blocking_and_guarded(tmp_path, monkeypatch):
    from chordential_oia.web import scheduler as sch
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)
    monkeypatch.setenv("CHORDENTIAL_AUTOENRICH", "1")
    # disabled here -> returns False, starts nothing
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: False)
    assert sch.start_manual_enrich(5) is False
    # while a pass is already running, a second nudge is a no-op
    monkeypatch.setattr(sch.discovery, "scrape_enabled", lambda: True)
    sch._enrich_status["running"] = True
    try:
        assert sch.start_manual_enrich(5) is False
    finally:
        sch._enrich_status["running"] = False
