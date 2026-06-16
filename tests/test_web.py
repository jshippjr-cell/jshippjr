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
    r = client.get("/")
    assert r.status_code == 200
    assert "Executive Summary" in r.text
    # The summary reads as a pipeline: targets → tentative → won.
    assert "Top targets to pursue" in r.text
    assert "Tentative" in r.text
    assert "Won" in r.text


def test_dashboard_pipeline_columns_populate(client):
    # The demo seed stages one bid and one win, and the win carries assigned crew.
    dash = client.get("/").text
    assert "bid submitted" in dash          # tentative column has a live bid
    assert "crew-chip" in dash              # won deal lists assigned team members


def test_inbox_and_search(client):
    assert client.get("/inbox").status_code == 200
    r = client.get("/inbox", params={"action": "Pursue"})
    assert r.status_code == 200
    # Search narrows results without erroring.
    assert client.get("/inbox", params={"q": "campaign"}).status_code == 200


def test_lanes_render(client):
    r = client.get("/lanes")
    assert r.status_code == 200
    for lane in ("Pursue", "Review", "Pass"):
        assert lane in r.text


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
    dash = client.get("/").text
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
    dash = client.get("/").text
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
    # The Overview carries a quick-action bar with the common next steps.
    assert "action-bar" in page
    assert "Pursuit brief" in page
    assert "Plan outreach" in page
    assert "Talent match" in page
    # A New opportunity offers a one-click advance to the next pipeline stage.
    assert "Mark Pursuing" in page


def test_action_bar_advances_pipeline_status(client):
    # The bar's advance button moves New -> Pursuing in one click.
    client.post("/opportunity/1/status", data={"status": "Pursuing"}, follow_redirects=True)
    page = client.get("/opportunity/1").text
    assert "Mark Submitted" in page  # next step now offered
    assert "Mark Pursuing" not in page


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
