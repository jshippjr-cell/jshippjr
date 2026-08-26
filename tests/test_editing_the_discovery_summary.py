"""Five things reported while editing a real discovery summary (2026-08-26).

    "i can only save my edits, how can i delete the text thats auto populated? Also the
     text runs outside the window and i cant see what's in the text box. Also i dont
     understand what the assumed engagement blurb is for? i dont think that is supposed to
     be client facing? when i change the template it takes me to the top of the page. i
     want the pricing levers that are in the pricing tab to be here in the indicative
     investment section."

The delete one is the interesting one: emptying the box and saving ALWAYS worked. It was
never a missing capability, it was a missing affordance — nothing on screen said so, and
the box was a one-line input showing the first few words of a sentence, so there was no
confident way to select what was in it. A capability nobody can find is not a capability.
"""
import importlib
import re

import pytest

from chordential_oia.pricing import (EXCLUSIVITY_LABELS, MEDIA_LABELS, TERRITORY_LABELS,
                                     LicenceTerms, TERM_FACTORS, licence_from_ci)


@pytest.fixture()
def doc(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "d.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", "passphrase")
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    for m in ("db", "campaigns", "uploads", "app"):
        importlib.reload(importlib.import_module(f"chordential_oia.web.{m}"))
    from fastapi.testclient import TestClient
    from chordential_oia.web import app as app_mod, campaign_intelligence as ci, db
    from chordential_oia.web.shell import ADMIN_COOKIE, admin_cookie_value
    with TestClient(app_mod.app):
        pass
    c = TestClient(app_mod.app)
    c.cookies.set(ADMIN_COOKIE, admin_cookie_value("passphrase"))
    conn = db.connect()
    try:
        cid = int(ci.ensure_for_opportunity(conn, db.get_opportunity(conn, 1))["id"])
        ci.contribute(conn, cid, "buyer", "brand_notes", "Pike and Rowan", kind="fact",
                      source="discovery_call", contributed_by="ai")
        conn.commit()
    finally:
        conn.close()
    c.post("/opportunity/1/doc/toggle", data={"cost": "1"}, follow_redirects=True)
    return c, db, ci, cid


def _field(db, ci, cid, key):
    conn = db.connect()
    try:
        return ci.brief_view(conn, cid)["fields"].get(key)
    finally:
        conn.close()


def _band(html):
    m = re.search(r'class="price">([^<]*)', html)
    return m.group(1).strip() if m else ""


# ── 1 + 2. deleting what the call got wrong ─────────────────────────────────────────
def test_there_is_a_button_that_empties_a_field(doc):
    """Emptying the box and saving already did this. It was folklore — nothing said so,
    and the box was too small to select a sentence in. The button says it."""
    c, db, ci, cid = doc
    assert 'name="clear"' in c.get("/opportunity/1/capabilities?edit=1").text
    c.post("/opportunity/1/doc/ci-field",
           data={"name": "brand_notes", "clear": "1", "value": "Pike and Rowan"},
           follow_redirects=False)
    assert not _field(db, ci, cid, "brand_notes")


def test_saving_an_empty_box_still_clears_it(doc):
    """The old way keeps working. Someone who learned the folklore is not punished for it."""
    c, db, ci, cid = doc
    c.post("/opportunity/1/doc/ci-field", data={"name": "brand_notes", "value": ""},
           follow_redirects=False)
    assert not _field(db, ci, cid, "brand_notes")


def test_the_editor_is_a_box_you_can_read_a_sentence_in(doc):
    """A one-line `<input>` showed the first few words of what the engine extracted, so the
    operator could read the value above the box and not manipulate it inside the box."""
    c, _db, _ci, _cid = doc
    page = c.get("/opportunity/1/capabilities?edit=1").text
    assert "capdoc-grow" in page
    # Only the DISCOVERY rows changed. A one-line box is right for "Client name"; it is
    # wrong for a field holding a sentence the extraction engine wrote.
    rows = page[page.index('id="discovery"'):]
    rows = rows[:rows.index("</section>")]
    assert '<input type="text" name="value"' not in rows, "a discovery row is still one line"
    assert rows.count("capdoc-grow") >= 5


# ── 3. the operator's note stops travelling on the client's document ────────────────
def test_the_client_is_told_the_assumption_and_not_what_to_do_about_it(doc):
    """"Assumed engagement: feature-film score (~20 to 30 cues)" is honest and belongs in
    front of a client — a package built on a guess is one they are entitled to read before
    signing. "Not right? Switch template or edit below." is an instruction about controls
    only the operator can see, and it travelled on every client copy and every PDF."""
    c, _db, _ci, _cid = doc
    client = c.get("/opportunity/1/capabilities").text
    assert "Assumed engagement" in client
    assert "Switch template or edit below" not in client
    assert "Not right?" not in client

    edit = c.get("/opportunity/1/capabilities?edit=1").text
    assert "the client sees the line above, not this one" in edit


def test_no_delivery_template_carries_an_instruction_in_its_data():
    """The instruction was baked into the assumption STRING, so every renderer inherited
    it. Splitting it in one template and leaving it in three would have been the same bug
    with a smaller blast radius."""
    from chordential_oia.capabilities import DELIVERY_TEMPLATES
    for key, spec in DELIVERY_TEMPLATES.items():
        text = spec.get("assumptions") or ""
        assert "Switch template" not in text, key
        assert "edit below" not in text, key


# ── 4. an edit returns to where it was made ─────────────────────────────────────────
def test_nothing_submits_a_form_behind_the_scroll_restores_back(doc):
    """THE ACTUAL CAUSE. This page already kept the operator's place — it records scrollY
    on the `submit` EVENT and restores it after the reload. `HTMLFormElement.submit()`
    fires no such event; that is the one documented difference between it and
    `requestSubmit()`. So every control the operator CLICKED kept its place, and the two
    that submit themselves on `change` threw the page to the masthead.

    The restore was never broken. One caller went around it."""
    c, _db, _ci, _cid = doc
    page = c.get("/opportunity/1/capabilities?edit=1").text
    # The ATTRIBUTE, not the phrase — the comment explaining this fix contains the words,
    # and a test that matches its own documentation passes for the wrong reason.
    assert 'onchange="this.form.submit()"' not in page, (
        "a control still submits without firing the event the restore listens for")
    assert "submitAndKeepPlace" in page
    assert "requestSubmit" in page


def test_the_redirect_does_not_race_the_scroll_restore(doc):
    """Two mechanisms for one job is worse than one: the browser jumping to a fragment
    while the script scrolls to a remembered offset, and whichever wins depends on
    timing."""
    c, _db, _ci, _cid = doc
    r = c.post("/opportunity/1/doc/field",
               data={"name": "delivery_template", "value": "campaign"},
               follow_redirects=False)
    assert "#" not in r.headers["location"]


# ── 5. the pricing levers, where the number is read ─────────────────────────────────
def test_the_levers_are_on_the_document_and_only_for_us(doc):
    c, _db, _ci, _cid = doc
    assert "lever-row" in c.get("/opportunity/1/capabilities?edit=1").text
    assert "lever-row" not in c.get("/opportunity/1/capabilities").text, (
        "the client can see our factor table")


def test_moving_a_lever_moves_the_band_on_the_same_page(doc):
    """The whole ask. A lever you have to go to another page to correct is one that stays
    wrong."""
    c, _db, _ci, _cid = doc
    before = _band(c.get("/opportunity/1/capabilities?edit=1").text)
    for key, value in (("territory", "worldwide"), ("license_term", "in perpetuity"),
                       ("exclusivity", "category-exclusive")):
        c.post("/opportunity/1/doc/ci-field", data={"name": key, "value": value},
               follow_redirects=False)
    after = _band(c.get("/opportunity/1/capabilities?edit=1").text)
    assert before and after and before != after, f"{before!r} did not move"


def test_a_lever_nobody_stated_is_badged_as_a_guess(doc):
    """ADR-0058. The operator is entitled to see which parts of the number are guessed
    before they send it — and the count has to fall as they are answered, or the badge is
    decoration."""
    c, _db, _ci, _cid = doc
    assert c.get("/opportunity/1/capabilities?edit=1").text.count("lever-assumed") == 4
    c.post("/opportunity/1/doc/ci-field", data={"name": "territory", "value": "worldwide"},
           follow_redirects=False)
    assert c.get("/opportunity/1/capabilities?edit=1").text.count("lever-assumed") == 3


@pytest.mark.parametrize("field,label", (
    [("media", v) for v in MEDIA_LABELS.values()]
    + [("territory", v) for v in TERRITORY_LABELS.values()]
    + [("exclusivity", v) for v in EXCLUSIVITY_LABELS.values()]
    + [("license_term", LicenceTerms(term_years=n).term_label) for n in TERM_FACTORS]
))
def test_every_option_the_rail_offers_reads_back(field, label):
    """The picker writes a LABEL into Campaign Intelligence and the parser reads it out
    again. An option whose text the parser could not read would look like it worked and
    change nothing — the picker would move, the price would not."""
    terms = licence_from_ci({field: label})
    assert terms.is_stated(field), f"{field}={label!r} did not read back"


def test_the_rail_shows_the_licence_the_price_actually_used(doc):
    """One derivation. A rail that re-derived the licence could display one the band was
    not built from, which is the two-surfaces-disagreeing bug this codebase keeps paying
    for."""
    c, _db, _ci, _cid = doc
    c.post("/opportunity/1/doc/ci-field", data={"name": "territory", "value": "worldwide"},
           follow_redirects=False)
    page = c.get("/opportunity/1/capabilities?edit=1").text
    assert re.search(r"Licence · <b>worldwide,[^<]*</b>", page)
