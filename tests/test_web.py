"""Smoke + behavior tests for the dashboard (FastAPI TestClient)."""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Isolate the DB per test run.
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:  # triggers lifespan seeding
        yield c


def test_dashboard_loads(client):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Today" in r.text
    # The summary reads as a pipeline: targets → tentative → won.
    assert "Top targets to pursue" in r.text
    assert "Tentative" in r.text
    assert "Won" in r.text


def test_dashboard_pipeline_columns_populate(client):
    # The demo seed stages one bid and one win, and the win carries assigned crew.
    dash = client.get("/dashboard").text
    assert "bid submitted" in dash          # tentative column has a live bid
    assert "crew-chip" in dash              # won deal lists assigned team members


def test_inbox_and_search(client):
    assert client.get("/inbox").status_code == 200
    r = client.get("/inbox", params={"action": "Pursue"})
    assert r.status_code == 200
    # Search narrows results without erroring.
    assert client.get("/inbox", params={"q": "campaign"}).status_code == 200


def test_lanes_render_status_kanban(client):
    r = client.get("/lanes")
    assert r.status_code == 200
    assert "kanban" in r.text
    # Columns are the human pipeline stages (relabeled at the view layer), with
    # Lost + Passed collapsed into one "Closed" archive column.
    for stage in ("New", "Reaching out", "Proposal out", "Won", "Closed"):
        assert stage in r.text


def test_lanes_card_advances_status(client):
    # Put opp 3 in New, then advance it from the board; it returns to /lanes.
    client.post("/opportunity/3/status", data={"status": "New"}, follow_redirects=True)
    r = client.post(
        "/opportunity/3/status",
        data={"status": "Pursuing", "return_to": "/lanes"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/lanes"
    assert client.get("/opportunity/3").text  # still renders
    # The opportunity now reports Pursuing (relabeled "Reaching out"); the next
    # suggested step is the relabeled "Proposal out".
    assert "Mark Proposal out" in client.get("/opportunity/3").text


def test_dashboard_columns_capped_at_four(client):
    t = client.get("/dashboard").text
    # Every column has a "View all" overflow path (Top targets, Tentative, Won).
    assert 'href="/inbox?status=Submitted"' in t  # Tentative overflow
    assert 'href="/inbox?status=Won"' in t        # Won overflow
    # Top-targets is capped at 4 cards (one advance button per card).
    assert 0 < t.count("→ Mark") <= 4


def test_dashboard_kpi_strip_and_followups_promoted(client):
    dash = client.get("/dashboard").text
    assert "kpi-strip" in dash
    assert "win rate" in dash and "follow-ups due" in dash
    # Inline advance affordance on a top-target card.
    assert "return_to" in dash


def test_inbox_inline_advance_returns_to_filtered_view(client):
    client.post("/opportunity/3/status", data={"status": "New"}, follow_redirects=True)
    r = client.post(
        "/opportunity/3/status",
        data={"status": "Pursuing", "return_to": "/inbox?status=New"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/inbox?status=New"


def test_inbox_has_sortable_headers_and_autosubmit(client):
    page = client.get("/inbox").text
    assert "sortable" in page
    assert 'order_by=client' in page  # buyer column is a sort link
    assert "onchange" in page         # filters auto-submit
    # Sorting by budget does not error.
    assert client.get("/inbox?order_by=budget").status_code == 200


def test_buyers_stage_filter_sort_and_recency(client):
    page = client.get("/buyers").text
    assert "Last touch" in page and "All stages" in page
    assert "nba" in page  # next-best-action emphasized
    assert client.get("/buyers?stage=Cold&order_by=touches").status_code == 200
    assert client.get("/buyers?order_by=recent").status_code == 200


def test_talent_review_queue_inline_approve(client):
    # Seeded roster has pending creators; the queue surfaces them.
    roster = client.get("/talent").text
    assert "Reel-review queue" in roster
    import re
    m = re.search(r'/talent/(\d+)/review', roster)
    assert m, "no pending creator in the review queue"
    tid = m.group(1)
    r = client.post(
        f"/talent/{tid}/review",
        data={"review_status": "Approved", "return_to": "/talent"},
        follow_redirects=False,
    )
    assert r.headers["location"] == "/talent"


def test_talent_kpis_are_clickable_filters(client):
    page = client.get("/talent").text
    assert 'href="/talent?review=Pending"' in page
    assert client.get("/talent?sort=matchable").status_code == 200


def test_projects_deadline_understaffed_and_filter(client):
    pid = _win_and_make_project(client, 1)
    page = client.get("/projects").text
    assert "Deadline" in page
    # A freshly spun-up project has roles but no crew yet -> understaffed flag.
    assert "understaffed" in page
    # Status segments filter without error.
    assert client.get("/projects?status=Active").status_code == 200
    assert f"/project/{pid}" in client.get("/projects?status=Active").text


def test_detail_and_subpages(client):
    # First opportunity id should exist after seeding.
    r = client.get("/opportunity/1")
    assert r.status_code == 200
    assert client.get("/opportunity/1/qualification").status_code == 200
    assert client.get("/opportunity/1/estimate").status_code == 200
    # Estimate page surfaces the Phase-1 honesty banner.
    assert "Phase 1" in client.get("/opportunity/1/estimate").text


def test_win_loss_tracking_updates_metrics(client):
    # Mark an opportunity Won with a value, then confirm it shows on the dashboard.
    r = client.post(
        "/opportunity/1/status",
        data={"status": "Won", "outcome_value": "9000"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    dash = client.get("/dashboard").text
    assert "$9,000" in dash  # won value rendered


def test_notes_persist(client):
    client.post("/opportunity/2/notes", data={"notes": "Call the EP Monday"},
                follow_redirects=True)
    assert "Call the EP Monday" in client.get("/opportunity/2").text


def test_buyer_profile(client):
    detail = client.get("/opportunity/1")
    assert detail.status_code == 200
    # The buyer link is reachable.
    r = client.get("/buyer/Acme%20Marketing%20(agency)")
    assert r.status_code in (200, 404)  # depends on seed naming; must not 500


def test_buyer_profile_shows_strategic_standing(client):
    import re
    detail = client.get("/opportunity/1").text
    m = re.search(r'href="(/buyer/[^"]+)"', detail)
    assert m, "buyer link not found on detail page"
    page = client.get(m.group(1)).text
    assert "Strategic value" in page  # CMO buyer-value KPI present
    # Header shows a buyer relationship value chip (one of the BuyerValue labels).
    assert any(lbl in page for lbl in
               ("One-time project", "Repeat buyer", "Enterprise buyer", "Unknown"))


def test_missing_opportunity_404(client):
    assert client.get("/opportunity/99999").status_code == 404


def test_brief_checklist_tracks_progress(client):
    page = client.get("/opportunity/1/brief").text
    assert "Pursuit checklist" in page
    assert "0 /" in page  # nothing ticked yet
    import re
    key = re.search(r'name="step_key" value="([^"]+)"', page).group(1)
    # Tick the first step done; progress advances and persists.
    client.post("/opportunity/1/brief/step",
                data={"step_key": key, "done": "1"}, follow_redirects=True)
    after = client.get("/opportunity/1/brief").text
    assert "1 /" in after
    assert "checked" in after
    # Untick it again.
    client.post("/opportunity/1/brief/step",
                data={"step_key": key, "done": ""}, follow_redirects=True)
    assert "0 /" in client.get("/opportunity/1/brief").text


def test_brief_export_buttons_removed(client):
    page = client.get("/opportunity/1/brief").text
    assert "Copy brief" not in page
    assert "Plain text" not in page


def test_outreach_recommends_examples_and_template_message(client):
    page = client.get("/opportunity/1/outreach").text
    assert "Recommended examples to attach" in page
    assert "Chordential is built for" in page  # template-style first-touch message
    assert "we would anticipate supporting" in page


def test_outreach_page_and_text(client):
    r = client.get("/opportunity/1/outreach")
    assert r.status_code == 200
    assert "Recommended cadence" in r.text
    txt = client.get("/opportunity/1/outreach.txt")
    assert txt.status_code == 200
    assert "OUTREACH PLAN" in txt.text


def test_outreach_contact_and_followup_persist(client):
    r = client.post(
        "/opportunity/1/outreach",
        data={
            "contact_name": "Dana Reyes",
            "contact_email": "dana@acme.com",
            "contact_role": "Creative Director",
            "next_action": "Send intro email + reel",
            "next_action_due": "2020-01-01",  # in the past -> due now
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    page = client.get("/opportunity/1/outreach").text
    assert "Dana Reyes" in page
    assert "dana@acme.com" in page
    # A past-due next action surfaces on the dashboard follow-up queue.
    dash = client.get("/dashboard").text
    assert "Follow-ups due" in dash
    assert "Send intro email + reel" in dash


def test_outreach_email_and_linkedin_links(client):
    # Save a contact email + LinkedIn, then confirm both render as clickable links:
    # a mailto with the pitch prefilled, and the LinkedIn profile (normalized).
    client.post(
        "/opportunity/1/outreach",
        data={
            "contact_name": "Dana Reyes",
            "contact_email": "dana@acme.com",
            "contact_linkedin": "linkedin.com/in/danareyes",
            "next_action": "Send intro",
        },
        follow_redirects=True,
    )
    page = client.get("/opportunity/1/outreach").text
    # mailto link addressed to the contact, carrying a subject + body (the pitch).
    assert "mailto:dana@acme.com?subject=" in page
    assert "&amp;body=" in page  # body of the email prefilled
    # LinkedIn handle was normalized to a working https:// profile link.
    assert 'href="https://linkedin.com/in/danareyes"' in page
    assert "LinkedIn profile" in page


def test_outreach_email_link_works_without_saved_email(client):
    # Even with no contact email captured, the compose draft is offered.
    page = client.get("/opportunity/2/outreach").text
    assert "mailto:?subject=" in page  # empty recipient, template still prefilled


def test_outreach_autopopulates_linkedin_research(client):
    # With nothing saved, the page auto-populates a LinkedIn research deep-link
    # for the inferred decision-maker — no manual entry needed.
    page = client.get("/opportunity/2/outreach").text
    assert "linkedin.com/search/results/people" in page
    # The LinkedIn field is pre-filled with that suggested URL.
    assert ('name="contact_linkedin" '
            'value="https://www.linkedin.com/search/results/people') in page
    assert "Find on LinkedIn" in page
    assert "auto-researched" in page.lower()


def test_saved_linkedin_overrides_autoresearch(client):
    # Pasting a verified profile takes over from the auto-built search link.
    client.post("/opportunity/2/outreach",
                data={"contact_linkedin": "linkedin.com/in/realperson"},
                follow_redirects=True)
    page = client.get("/opportunity/2/outreach").text
    assert 'href="https://linkedin.com/in/realperson"' in page
    assert "LinkedIn profile" in page
    assert "search/results/people" not in page  # suggestion no longer shown


def test_outreach_event_logs_and_stamps_contact(client):
    client.post(
        "/opportunity/2/outreach/event",
        data={"channel": "Email", "direction": "Sent", "note": "Sent intro + reel"},
        follow_redirects=True,
    )
    page = client.get("/opportunity/2/outreach").text
    assert "Sent intro + reel" in page
    assert "Last contacted" in page  # last_contacted stamped


def test_outreach_event_ignores_empty_note(client):
    client.post(
        "/opportunity/3/outreach/event",
        data={"channel": "Email", "direction": "Sent", "note": "   "},
        follow_redirects=True,
    )
    page = client.get("/opportunity/3/outreach").text
    assert "No touches logged yet" in page


def test_buyers_directory_renders_and_ranks(client):
    r = client.get("/buyers")
    assert r.status_code == 200
    assert "Buyer Graph" in r.text
    # Every seeded buyer should appear as a relationship row (Cold until touched).
    assert "Cold" in r.text


def test_buyer_profile_shows_relationship_panel(client):
    # Find a real buyer via an opportunity, then open its profile.
    import re
    detail = client.get("/opportunity/1").text
    m = re.search(r'href="(/buyer/[^"]+)"', detail)
    assert m
    page = client.get(m.group(1)).text
    assert "Relationship" in page
    assert "Next best action" in page


def test_relationship_reflects_outreach_and_wins(client):
    # Capture a contact + log a touch on opp 1, then mark it Won.
    client.post("/opportunity/1/outreach", data={
        "contact_name": "Dana Reyes", "contact_email": "dana@acme.com",
        "contact_role": "Creative Director", "next_action": "Call",
        "next_action_due": "2026-01-01"}, follow_redirects=True)
    client.post("/opportunity/1/outreach/event", data={
        "channel": "Email", "direction": "Sent", "note": "Sent intro"},
        follow_redirects=True)
    client.post("/opportunity/1/status", data={"status": "Won", "outcome_value": "9000"},
                follow_redirects=True)
    import re
    detail = client.get("/opportunity/1").text
    m = re.search(r'href="(/buyer/[^"]+)"', detail)
    page = client.get(m.group(1)).text
    assert "Client" in page          # a won deal -> Client stage
    assert "Dana Reyes" in page      # captured contact surfaces on the buyer
    # The buyer also appears as a Client in the directory.
    assert "Client" in client.get("/buyers").text


def test_opportunity_overview_action_bar(client):
    # Reset to New so the advance button is deterministic (seed may stage opp 1).
    client.post("/opportunity/1/status", data={"status": "New"}, follow_redirects=True)
    page = client.get("/opportunity/1").text
    # The Overview carries a quick-action bar; the redundant brief/outreach/match
    # buttons were removed (those live in the subnav now).
    assert "action-bar" in page
    assert "Plan outreach" not in page  # redundant button removed
    # A New opportunity offers a one-click advance, pushed to the right
    # (label relabeled at the view layer: Pursuing → "Reaching out").
    assert "Mark Reaching out" in page
    assert "action-right" in page


def test_overview_subnav_order(client):
    # Subnav order: Overview · Budget estimate · Outreach · Talent match ·
    # Pursuit brief · Buyer profile · Qualification rationale.
    page = client.get("/opportunity/1").text
    order = ["Budget estimate", "Outreach", "Talent match", "Pursuit brief",
             "Buyer profile", "Qualification rationale"]
    positions = [page.index(x) for x in order]
    assert positions == sorted(positions), "subnav tabs out of expected order"


def test_action_bar_advances_pipeline_status(client):
    # The bar's advance button moves New -> Pursuing in one click.
    client.post("/opportunity/1/status", data={"status": "Pursuing"}, follow_redirects=True)
    page = client.get("/opportunity/1").text
    # Next step now offered is "Proposal out" (was Submitted); the prior step's
    # label "Reaching out" (was Pursuing) is no longer the suggested action.
    assert "Mark Proposal out" in page
    assert "Mark Reaching out" not in page


def test_company_website_persists_and_displays(client):
    import re
    detail = client.get("/opportunity/1").text
    m = re.search(r'href="(/buyer/[^"]+)"', detail)
    assert m, "buyer link not found"
    buyer_url = m.group(1)
    # A bare host is normalized to an https:// link and shown compactly.
    client.post(f"{buyer_url}/website", data={"website": "acme-music.com"},
                follow_redirects=True)
    page = client.get(buyer_url).text
    assert 'href="https://acme-music.com"' in page
    assert "acme-music.com" in page  # compact display (scheme stripped)


def test_talent_roster_seeds_and_renders(client):
    r = client.get("/talent")
    assert r.status_code == 200
    assert "Talent Roster" in r.text
    assert "Maya Okafor" in r.text  # seeded creator


def test_talent_roster_filters(client):
    # Filter to approved creators only — should not error and should narrow.
    assert client.get("/talent", params={"review": "Approved"}).status_code == 200
    assert client.get("/talent", params={"discipline": "composition"}).status_code == 200


def test_add_talent_and_view_detail(client):
    r = client.post("/talent", data={
        "name": "Riley Composer", "email": "riley@x.com",
        "disciplines": ["composition", "sound_design"],
        "credits": "Scored two shorts", "location": "Chicago",
        "demo_reel_url": "https://example.com/riley"},
        follow_redirects=True)
    assert r.status_code == 200
    assert "Riley Composer" in r.text
    assert "Scored two shorts" in r.text


def test_demo_reel_review_gate_controls_matchable(client):
    # Add a creator with a discipline; pending => not matchable; approve => matchable.
    create = client.post("/talent", data={
        "name": "Gate Test", "disciplines": ["composition"],
        "demo_reel_url": "https://example.com/gate"}, follow_redirects=True)
    import re
    # The redirect lands on /talent/{id}; recover the id from the roster link.
    roster = client.get("/talent").text
    m = re.search(r'/talent/(\d+)"[^>]*>\s*(?:<[^>]+>\s*)*', roster)
    # Find this talent's id by posting review and re-reading; simplest: search detail pages.
    # Approve via the most recently added — locate by name on a detail page scan.
    # Pull id from the create response URL chain instead:
    assert "Gate Test" in create.text
    tid = int(re.search(r'/talent/(\d+)/review', create.text).group(1))
    assert "✓ Matchable" not in client.get(f"/talent/{tid}").text
    client.post(f"/talent/{tid}/review", data={"review_status": "Approved"},
                follow_redirects=True)
    assert "✓ Matchable" in client.get(f"/talent/{tid}").text


def test_invite_funnel_updates(client):
    create = client.post("/talent", data={"name": "Funnel Test"}, follow_redirects=True)
    import re
    tid = int(re.search(r'/talent/(\d+)/invite', create.text).group(1))
    client.post(f"/talent/{tid}/invite", data={"invite_status": "Invited"},
                follow_redirects=True)
    assert "Invited" in client.get(f"/talent/{tid}").text


def test_talent_match_page_renders(client):
    # Seeded roster includes approved composers, so opp 1 should surface matches.
    r = client.get("/opportunity/1/match")
    assert r.status_code == 200
    assert "Talent match" in r.text
    assert "Recommended creators" in r.text
    # The human-decision framing is present (Jon makes the final call).
    assert "final call" in r.text.lower()


def test_match_excludes_unapproved_until_reviewed(client):
    # Add a composer but leave them Pending — they must NOT appear as a match.
    create = client.post("/talent", data={
        "name": "Unseen Composer", "disciplines": ["composition"],
        "demo_reel_url": "https://example.com/unseen"}, follow_redirects=True)
    import re
    tid = int(re.search(r'/talent/(\d+)/review', create.text).group(1))
    assert "Unseen Composer" not in client.get("/opportunity/1/match").text
    # Approve the reel -> now eligible to surface.
    client.post(f"/talent/{tid}/review", data={"review_status": "Approved"},
                follow_redirects=True)
    assert "Unseen Composer" in client.get("/opportunity/1/match").text


def _win_and_make_project(client, opp_id=1):
    """Mark an opportunity Won and spin up its project; return the project id."""
    client.post(f"/opportunity/{opp_id}/status",
                data={"status": "Won", "outcome_value": "9000"}, follow_redirects=True)
    r = client.post(f"/opportunity/{opp_id}/project", follow_redirects=False)
    # 303 redirect to /project/{id}
    loc = r.headers["location"]
    import re
    return int(re.search(r"/project/(\d+)", loc).group(1))


def test_spin_up_project_from_won_opportunity(client):
    pid = _win_and_make_project(client, 1)
    page = client.get(f"/project/{pid}")
    assert page.status_code == 200
    assert "Roles & assignment" in page.text or "Roles &amp; assignment" in page.text
    # Re-posting must not create a duplicate — it redirects to the same project.
    r2 = client.post("/opportunity/1/project", follow_redirects=False)
    assert r2.headers["location"].endswith(f"/project/{pid}")


def test_assignment_is_explicit_and_reversible(client):
    pid = _win_and_make_project(client, 1)
    view = client.get(f"/project/{pid}").text
    # The project should offer matched creators to assign (seeded approved composers).
    import re
    m = re.search(r'<option value="(\d+)">([^<]+) — fit', view)
    assert m, "no matched creator option on the project page"
    talent_id = m.group(1)
    # Before assigning, that creator is not shown as assigned (no checkmark row yet).
    assert "✓" not in client.get(f"/project/{pid}").text
    # Assign — the explicit decision action.
    client.post(f"/project/{pid}/assign",
                data={"role": "Composer", "talent_id": talent_id}, follow_redirects=True)
    after = client.get(f"/project/{pid}").text
    assert "✓" in after and "Unassign" in after
    # Unassign reverses it.
    aid = re.search(r'name="assignment_id" value="(\d+)"', after).group(1)
    client.post(f"/project/{pid}/unassign",
                data={"assignment_id": aid}, follow_redirects=True)
    assert "Unassign" not in client.get(f"/project/{pid}").text


def test_projects_directory_lists_project(client):
    pid = _win_and_make_project(client, 1)
    page = client.get("/projects")
    assert page.status_code == 200
    assert f"/project/{pid}" in page.text


def test_project_status_toggle(client):
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/status", data={"status": "Delivered"}, follow_redirects=True)
    assert "Delivered" in client.get(f"/project/{pid}").text


def test_project_seeds_milestones_from_roles(client):
    pid = _win_and_make_project(client, 1)
    page = client.get(f"/project/{pid}").text
    assert "Delivery progress" in page
    # A default deliverable milestone per scoped role (e.g. Composer).
    assert "Composer deliverable" in page
    assert "0 /" in page  # nothing done yet


def test_milestone_status_advances_progress(client):
    import re
    pid = _win_and_make_project(client, 1)
    page = client.get(f"/project/{pid}").text
    mid = re.search(r'name="milestone_id" value="(\d+)"', page).group(1)
    client.post(f"/project/{pid}/milestone/status",
                data={"milestone_id": mid, "status": "Done"}, follow_redirects=True)
    after = client.get(f"/project/{pid}").text
    # At least one done now; progress reflects it.
    assert "1 /" in after


def test_add_and_delete_milestone(client):
    import re
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/milestone",
                data={"title": "First sketch to client"}, follow_redirects=True)
    page = client.get(f"/project/{pid}").text
    assert "First sketch to client" in page
    # Delete it (grab the last milestone id present on the page).
    ids = re.findall(r'name="milestone_id" value="(\d+)"', page)
    client.post(f"/project/{pid}/milestone/delete",
                data={"milestone_id": ids[-1]}, follow_redirects=True)
    # Page still renders fine.
    assert client.get(f"/project/{pid}").status_code == 200


def test_milestone_move_auto_broadcasts(client):
    import re
    pid = _win_and_make_project(client, 1)
    page = client.get(f"/project/{pid}").text
    assert "Activity & broadcast" in page or "Activity &amp; broadcast" in page
    mid = re.search(r'name="milestone_id" value="(\d+)"', page).group(1)
    client.post(f"/project/{pid}/milestone/status",
                data={"milestone_id": mid, "status": "Done"}, follow_redirects=True)
    feed = client.get(f"/project/{pid}").text
    assert "Done" in feed and "→" in feed  # the auto-posted milestone update


def test_assign_auto_broadcasts_and_lists_crew(client):
    import re
    pid = _win_and_make_project(client, 1)
    view = client.get(f"/project/{pid}").text
    m = re.search(r'<option value="(\d+)">([^<]+) — fit', view)
    talent_id, name = m.group(1), m.group(2).strip()
    client.post(f"/project/{pid}/assign",
                data={"role": "Composer", "talent_id": talent_id}, follow_redirects=True)
    page = client.get(f"/project/{pid}").text
    assert "assigned to Composer" in page          # auto-broadcast entry
    assert "Broadcasts to" in page                 # crew recipient line
    assert name in page


def test_manual_broadcast_post(client):
    pid = _win_and_make_project(client, 1)
    client.post(f"/project/{pid}/update",
                data={"body": "Kickoff call Thursday 10am"}, follow_redirects=True)
    assert "Kickoff call Thursday 10am" in client.get(f"/project/{pid}").text


def test_old_database_migrates_without_data_loss(tmp_path, monkeypatch):
    """An old-shape chordential.db (no outreach columns) must migrate cleanly."""
    import sqlite3

    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """CREATE TABLE opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client TEXT NOT NULL, need TEXT NOT NULL, status TEXT DEFAULT 'New'
        )"""
    )
    conn.execute("INSERT INTO opportunities (client, need) VALUES ('Legacy Co','Old need')")
    conn.commit()
    conn.close()

    monkeypatch.setenv("CHORDENTIAL_DB", str(db_file))
    import importlib
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)  # should ALTER in the new columns + events table
    # Pre-existing row survives and gains the new (NULL) outreach fields.
    row = conn.execute("SELECT * FROM opportunities WHERE client='Legacy Co'").fetchone()
    assert row["need"] == "Old need"
    assert "next_action_due" in row.keys()
    db_mod.update_outreach(conn, row["id"], next_action="Call", next_action_due="2020-01-01")
    db_mod.add_outreach_event(conn, row["id"], "Email", "Sent", "hello")
    assert len(db_mod.list_outreach_events(conn, row["id"])) == 1
    conn.close()


def test_strategic_value_on_detail_and_sort(client):
    # Detail page surfaces the CMO Strategic-Value lens.
    detail = client.get("/opportunity/1").text
    assert "Strategic value" in detail
    # Inbox can sort by strategic value without erroring.
    assert client.get("/inbox", params={"order_by": "strategic"}).status_code == 200


def test_set_strategic_inputs_recomputes(client):
    # Marking a buyer as enterprise + marquee should raise its strategic standing.
    r = client.post(
        "/opportunity/1/strategic",
        data={"buyer_value": "enterprise", "marquee": "on"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Enterprise buyer" in r.text  # selected option reflected back


# --------------------------------------------------------------------------- #
# Phase 1 — unified "Incoming" queue (leads + signals UNION), one badge, push.
# --------------------------------------------------------------------------- #
def _seed_incoming():
    """Seed one inbound lead and one signal into the (already-isolated) test DB."""
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        lead_id = db_mod.insert_inbound_lead(
            conn, "Ada Lovelace", "ada@example.com", "Analytical Engine Co",
            project_type="Brand film", source="questionnaire",
        )
        sig_id = db_mod.insert_signal(
            conn, source="reddit-forhire", source_weight=5,
            title="Need a composer for a short film", body="Paying gig, 2 weeks.",
            external_ref="test:incoming:1", score=70.0, tier="Watch",
        )
    finally:
        conn.close()
    return lead_id, sig_id


def test_incoming_shows_lead_and_signal(client):
    _seed_incoming()
    r = client.get("/incoming")
    assert r.status_code == 200
    # Both a lead and a signal appear in the one unified queue.
    assert "Brand film" in r.text                     # the lead's title
    assert "Need a composer for a short film" in r.text  # the signal's title
    # Source chips render for each source.
    assert "Website" in r.text and "Signal" in r.text


def test_incoming_unactioned_count_sums_both(client):
    _seed_incoming()
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        assert db_mod.incoming_unactioned_count(conn) == 2  # 1 New lead + 1 New signal
    finally:
        conn.close()


def test_incoming_count_endpoint(client):
    _seed_incoming()
    r = client.get("/incoming/count")
    assert r.status_code == 200
    assert r.json()["new"] == 2


def test_incoming_dismiss_lead_sets_status(client):
    lead_id, _ = _seed_incoming()
    r = client.post(
        f"/leads/{lead_id}/status", data={"status": "Dismissed"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        lead = db_mod.get_inbound_lead(conn, lead_id)
        assert lead["status"] == "Dismissed"
        # Dismissed items drop out of the unified count (was 2, now 1 signal).
        assert db_mod.incoming_unactioned_count(conn) == 1
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Phase 4 — tab consolidation + stage relabel + the two-list "Today" home.
# --------------------------------------------------------------------------- #
def test_today_home_shows_needs_triage(client):
    # An inbound lead is waiting; the "Today" home surfaces it in Needs triage
    # with inline Promote/Dismiss, above the qualified Top-targets list.
    _seed_incoming()
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Needs triage" in r.text          # the new first module
    assert "Brand film" in r.text            # the waiting inbound lead's title
    assert "Promote" in r.text and "Dismiss" in r.text
    # Top-targets stays below, qualified-only.
    assert "Top targets to pursue" in r.text


def test_today_home_triage_empty_state(client):
    # No leads/signals seeded → a clean all-caught-up state, still renders 200.
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Needs triage" in r.text
    assert "all caught up" in r.text


def test_lanes_collapses_closed_and_relabels(client):
    r = client.get("/lanes")
    assert r.status_code == 200
    # Friendly relabels appear as column headers.
    assert "Reaching out" in r.text          # was "Pursuing"
    assert "Proposal out" in r.text          # was "Submitted"
    # Lost + Passed collapse into a single "Closed" column; the old raw labels
    # are gone from the board's column heads.
    assert "Closed" in r.text
    assert r.text.count("kcol-head") == 5    # New, Reaching out, Proposal out, Won, Closed


def test_stage_label_maps_view_layer():
    from chordential_oia.web import db as db_mod
    assert db_mod.stage_label("Submitted") == "Proposal out"
    assert db_mod.stage_label("Pursuing") == "Reaching out"
    assert db_mod.stage_label("Passed") == "Closed"
    assert db_mod.stage_label("Lost") == "Closed"
    assert db_mod.stage_label("New") == "New"
    # Stored values are untouched (no data migration).
    assert "Submitted" in db_mod.PIPELINE_STATES
    assert db_mod.stage_label("Unknown") == "Unknown"  # fallback to raw


# --------------------------------------------------------------------------- #
# Phase 3 — public intake gate (email always + phone OR LinkedIn) + honeypot.
# --------------------------------------------------------------------------- #
def _lead_count():
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM inbound_leads").fetchone()[0]
    finally:
        conn.close()


def test_start_requires_phone_or_linkedin(client):
    # Email but neither phone nor LinkedIn -> rejected, no lead stored.
    r = client.post(
        "/start",
        data={"contact_name": "Pat", "contact_email": "pat@example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "phone" in r.text.lower()
    assert _lead_count() == 0


def test_start_requires_email(client):
    # No email at all (but a phone) -> still rejected.
    r = client.post(
        "/start",
        data={"contact_name": "Pat", "phone": "555-1212"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert _lead_count() == 0


def test_start_email_plus_phone_succeeds_and_stores_phone(client):
    r = client.post(
        "/start",
        data={
            "contact_name": "Pat", "contact_email": "pat@example.com",
            "phone": "555-1212", "project_type": "Brand film",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303  # redirect to /thanks
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        row = conn.execute(
            "SELECT * FROM inbound_leads WHERE contact_email = 'pat@example.com'"
        ).fetchone()
        assert row is not None
        assert row["phone"] == "555-1212"
    finally:
        conn.close()


def test_start_email_plus_linkedin_succeeds(client):
    r = client.post(
        "/start",
        data={
            "contact_name": "Pat", "contact_email": "pat@example.com",
            "contact_linkedin": "linkedin.com/in/pat",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _lead_count() == 1


def test_start_honeypot_silently_drops_bot(client):
    r = client.post(
        "/start",
        data={
            "contact_name": "Bot", "contact_email": "bot@example.com",
            "phone": "555-0000", "company_url": "http://spam.example",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303          # looks like success to the bot
    assert _lead_count() == 0            # but nothing was stored


def test_book_email_plus_phone_succeeds(client):
    r = client.post(
        "/book",
        data={
            "contact_name": "Pat", "contact_email": "pat@example.com",
            "phone": "555-1212",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert _lead_count() == 1


def test_book_requires_reachable_channel(client):
    r = client.post(
        "/book",
        data={"contact_name": "Pat", "contact_email": "pat@example.com"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert _lead_count() == 0


# --------------------------------------------------------------------------- #
# Phase 5 — lead detail: contact-first + guided stepper + delivery milestone.
# --------------------------------------------------------------------------- #
def test_detail_shows_contact_tap_to_act_links(client):
    # Seed a contact (incl. phone) via the outreach form, then the Overview pulls
    # it to the top as tel:/mailto: tap-to-act links.
    client.post(
        "/opportunity/1/outreach",
        data={
            "contact_name": "Dana Reyes",
            "contact_email": "dana@acme.com",
            "contact_phone": "(415) 555-0142",
        },
        follow_redirects=True,
    )
    page = client.get("/opportunity/1").text
    assert "Dana Reyes" in page
    assert 'href="tel:(415) 555-0142"' in page
    assert 'href="mailto:dana@acme.com"' in page


def test_detail_stepper_shows_friendly_stage_labels(client):
    page = client.get("/opportunity/1").text
    assert "stage-stepper" in page
    # The stepper renders the working stages with their friendly view-layer labels.
    for label in ("New", "Reaching out", "Proposal out", "Won"):
        assert label in page


def test_delivery_doc_sent_milestone(client):
    page = client.get("/opportunity/1").text
    assert "Mark delivery doc sent" in page          # not yet sent -> the button
    r = client.post(
        "/opportunity/1/delivery-sent", follow_redirects=False
    )
    assert r.status_code == 303
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        row = db_mod.get_opportunity(conn, 1)
    finally:
        conn.close()
    assert row["delivery_doc_sent_at"]               # stamped
    page = client.get("/opportunity/1").text
    assert "Delivery doc sent" in page and "✓" in page  # now the checkmark marker


def test_promote_carries_lead_phone_onto_opportunity(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        lead_id = db_mod.insert_inbound_lead(
            conn, "Casey Park", "casey@studio.com", "Studio Park",
            project_type="Brand film", source="questionnaire",
            phone="(212) 555-0199", contact_linkedin="linkedin.com/in/caseypark",
        )
    finally:
        conn.close()
    r = client.post(f"/leads/{lead_id}/promote", follow_redirects=False)
    assert r.status_code == 303
    new_opp = r.headers["location"].split("/opportunity/")[1].split("?")[0]
    page = client.get(f"/opportunity/{new_opp}").text
    assert 'href="tel:(212) 555-0199"' in page       # phone carried + tap-to-act


# --------------------------------------------------------------------------- #
# Phase 6 — combined personalized client document + surfaced Stripe deposit.
# --------------------------------------------------------------------------- #
def test_capabilities_doc_shows_delivery_outline_for_submitted_opp(client):
    # Opp 1 is seeded Submitted (proposal stage) → the delivery-package outline
    # renders alongside the capabilities framing.
    page = client.get("/opportunity/1/capabilities").text
    assert "delivery package" in page.lower()        # the combined block heading
    assert "Deliverables manifest" in page           # a rich sub-section renders
    assert "Final master" in page                    # a deliverables row appears
    assert "Rights &amp; ownership" in page


def test_capabilities_doc_hides_delivery_for_discovery_opp(client):
    # Opp 3 is seeded New (discovery) → no delivery block by default.
    page = client.get("/opportunity/3/capabilities").text
    assert "Deliverables manifest" not in page
    assert "What your delivery package includes" not in page


def test_capabilities_doc_no_sample_data_leaks(client):
    # The static AURORA sample must never bleed into a real deal's doc.
    page = client.get("/opportunity/1/capabilities").text
    assert "AURORA" not in page
    assert "Find Your Horizon" not in page


def test_capabilities_doc_surfaces_pay_deposit_with_invoice(client):
    # Spin up the deal: project → proposal → Deposit invoice, all via the
    # existing routes, then the doc surfaces a Stripe checkout form.
    client.post("/opportunity/1/project", follow_redirects=True)
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        pid = db_mod.project_for_opp(conn, 1)["id"]
    finally:
        conn.close()
    client.post(f"/project/{pid}/proposal", follow_redirects=True)
    client.post(f"/project/{pid}/invoice", data={"kind": "Deposit"}, follow_redirects=True)
    conn = db_mod.connect()
    try:
        inv = [i for i in db_mod.list_invoices(conn, pid) if i["kind"] == "Deposit"][0]
    finally:
        conn.close()
    page = client.get("/opportunity/1/capabilities").text
    assert f'action="/invoice/{inv["id"]}/checkout"' in page
    assert "Pay deposit" in page


def test_capabilities_doc_deposit_amount_without_invoice(client):
    # No project/invoice yet → show the amount with the muted spin-up note,
    # not a checkout form.
    page = client.get("/opportunity/1/capabilities").text
    assert "Deposit invoice is generated when the project is spun up" in page
    assert "/checkout" not in page


def test_capabilities_doc_mark_delivery_sent_in_toolbar(client):
    page = client.get("/opportunity/1/capabilities").text
    assert "Mark delivery doc sent" in page
    client.post(
        "/opportunity/1/delivery-sent",
        data={"return_to": "/opportunity/1/capabilities"},
        follow_redirects=False,
    )
    page = client.get("/opportunity/1/capabilities").text
    assert "✓ Sent" in page
    assert "Mark delivery doc sent" not in page


# --------------------------------------------------------------------------- #
# Phase 7 — crawler legibility + source→won attribution.
# --------------------------------------------------------------------------- #
def test_source_attribution_rolls_up_leads_promoted_won(client):
    """A website lead promoted-and-won, a crawler lead promoted-not-won, and an
    un-promoted website lead → correct leads_in/promoted/won per normalized source."""
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        # 1. Website lead → promote → mark Won.
        web_won = db_mod.insert_inbound_lead(
            conn, "Won Webster", "won@site.com", "Webster Co",
            project_type="Brand film", source="questionnaire",
        )
        # 2. Crawler lead → promote, leave open (not won).
        crawl_open = db_mod.insert_inbound_lead(
            conn, "(discovered)", company="Crawled Corp",
            project_type="Score", source="crawl",
        )
        # 3. Website lead, never promoted.
        db_mod.insert_inbound_lead(
            conn, "Raw Lead", "raw@site.com", "Raw Co",
            project_type="Jingle", source="book_call",
        )
    finally:
        conn.close()

    # Promote via the real route (creates + links the opportunity).
    r1 = client.post(f"/leads/{web_won}/promote", follow_redirects=False)
    won_opp = int(r1.headers["location"].split("/opportunity/")[1].split("?")[0])
    client.post(f"/leads/{crawl_open}/promote", follow_redirects=False)

    conn = db_mod.connect()
    try:
        db_mod.update_status(conn, won_opp, "Won")
        ordered = db_mod.source_attribution(conn)
    finally:
        conn.close()
    rows = {r["source"]: r for r in ordered}

    assert rows["Website"]["leads_in"] == 2      # one won, one un-promoted
    assert rows["Website"]["promoted"] == 1
    assert rows["Website"]["won"] == 1
    assert rows["Crawler"]["leads_in"] == 1
    assert rows["Crawler"]["promoted"] == 1
    assert rows["Crawler"]["won"] == 0
    # Sorted by won desc → the channel with a win leads the list.
    assert ordered[0]["source"] == "Website"


def test_source_attribution_buckets_signals(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        db_mod.insert_signal(
            conn, source="reddit-forhire", source_weight=5,
            title="Composer wanted", external_ref="test:attr:sig:1",
        )
        rows = {r["source"]: r for r in db_mod.source_attribution(conn)}
    finally:
        conn.close()
    assert "Signal" in rows
    assert rows["Signal"]["leads_in"] >= 1
    assert rows["Signal"]["promoted"] == 0


def test_discovery_renders_attribution_and_autofetch_state(client):
    from chordential_oia.web import db as db_mod
    conn = db_mod.connect()
    try:
        db_mod.insert_inbound_lead(
            conn, "Panel Lead", "panel@site.com", "Panel Co",
            project_type="Brand film", source="questionnaire",
        )
    finally:
        conn.close()
    r = client.get("/discovery")
    assert r.status_code == 200
    # The attribution panel renders with its table once a lead exists.
    assert "Where your deals come from" in r.text
    assert "Win rate" in r.text
    # The auto-fetch on/off banner renders (off in tests — no scrape flag set).
    assert "Auto-fetch is OFF" in r.text
