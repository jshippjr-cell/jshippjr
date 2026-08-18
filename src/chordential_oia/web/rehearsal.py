"""A rehearsal deal — the client's side of the product, walkable, on your own instance.

There was no way to test the client experience without either inventing a whole deal by
hand and walking the funnel to reach the interesting part, or practising on a real buyer.
Reported live: *"i no longer have an ability to test what you fixed and i dont want to
start a new opportunity and walk through a whole process — i want to pick back up at the
moment i send the discovery summary."*

So this builds a deal that is already standing at that moment: a discovery call recorded
as held (which is what makes the summary priced and signable at all — ADR-0065's `met`
gate), a brief with real content, and a contact address that is **your own**, so every
client-facing email lands in your inbox and every link in it is a link you can click.

Three rules it keeps:

* **An invented brand, never a real one.** The honesty rule applies to rehearsals too —
  a demo that name-drops a real trademark is the thing we promised not to do.
* **Marked as a rehearsal in the record** (`source='rehearsal'`), so it is filterable,
  obvious on its own page, and never mistaken for pipeline. The CLIENT never sees the
  marker: the workspace has to look exactly like a real one or it proves nothing.
* **The money is real.** The scope is deliberately small — one 15-second social cut —
  but the fee derives from the work and lands on the studio's floor regardless, so the
  quote comes out around five figures and the deposit is a genuine four-figure number.
  On a live Stripe key that Pay button opens a REAL checkout. That is not a flaw to
  engineer around: pricing a tiny job at the floor is what the engine is supposed to do
  (ADR-0065), and a rehearsal that quoted $200 would be rehearsing a different product.
  The deal page warns instead — loading Stripe's page is the test, finishing it is not.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from ..models import (BuyerType, BuyerValue, MusicRequirement, Opportunity)

SOURCE = "rehearsal"

# Invented, and deliberately unglamorous — a rehearsal that reads as a marquee brand
# invites screenshots that imply client work we do not have.
CLIENT = "Vance Athletic"
NEED = "Spring range teaser — 15-second social cut"
DESCRIPTION = (
    "One 15-second social teaser for the spring range. Original music, no library. "
    "Picture is locked and lands with us as an MP4. Instagram and TikTok only, "
    "organic, one territory, six months. One round of revisions expected."
)


def is_rehearsal(row) -> bool:
    """True for a row created here. Tolerant of a missing column / mapping."""
    try:
        return (row["source"] or "") == SOURCE
    except (KeyError, TypeError, IndexError):
        return False


def operator_email() -> str:
    """Where the 'client' half of a rehearsal is delivered — your own inbox."""
    return (os.environ.get("CHORDENTIAL_OPERATOR_EMAIL", "")
            or os.environ.get("CHORDENTIAL_SMTP_FROM", "")).strip()


def create(conn, db, *, contact_email: str = "", contact_name: str = "") -> int:
    """Build the rehearsal deal and return its opportunity id.

    Positioned at the exact moment named: the call has happened, so the Discovery Summary
    is priced, carries an Agreement block and can be signed. Nothing has been sent — the
    next click is yours.
    """
    email = (contact_email or operator_email()).strip()
    name = (contact_name or "Dana Vance").strip()
    opp = Opportunity(
        client=CLIENT,
        need=NEED,
        source=SOURCE,
        description=DESCRIPTION,
        buyer_type=BuyerType.BRAND,
        music_requirement=MusicRequirement.ORIGINAL,
        # A stated budget, because the point of ADR-0065 is that we quote the WORK and
        # report the budget as a check against it. A rehearsal where the two agree
        # proves nothing; these deliberately differ.
        budget_min=900.0,
        budget_max=1600.0,
        location="Miami, FL",
        buyer_value=BuyerValue.UNKNOWN,
        tags=["rehearsal", "social"],
    )
    opp_id = db.insert_opportunity(conn, opp)
    conn.execute(
        "UPDATE opportunities SET contact_name = ?, contact_email = ?, status = ? "
        "WHERE id = ?", (name, email, "Pursuing", opp_id))
    conn.commit()

    # The call, already held. Without this the summary has no price, no terms and no
    # signature block — `met` is the gate, and a rehearsal that stops short of it cannot
    # exercise the thing being rehearsed.
    held = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    db.create_meeting(conn, opp_id=opp_id, start_at=held, status="ingested",
                      client_name=name, client_email=email, scheduled_by="operator")

    # What the call established, in the words the brief reads back. These are ordinary
    # Campaign Intelligence values — the same ones a real transcript would populate.
    try:
        ci = _ci(conn, db, opp_id)
        if ci is not None:
            for key, value in (
                ("campaign_objective",
                 "Launch the spring range to an existing social audience."),
                ("deadline", (datetime.now(timezone.utc) + timedelta(days=21)
                              ).strftime("%d %B %Y")),
                ("budget_band", "$900–$1,600"),
                ("media", "Social — Instagram and TikTok, organic"),
                ("territory", "United States"),
                ("term", "6 months"),
                ("exclusivity", "Non-exclusive"),
                ("revisions", "1"),
            ):
                _set_ci(conn, db, ci, key, value)
    except Exception:  # noqa: BLE001 — a rehearsal must still be created if CI hiccups
        pass

    db.ensure_share_token(conn, opp_id)
    return opp_id


def _ci(conn, db, opp_id):
    from . import campaign_intelligence, campaigns
    if not campaigns.workspace_enabled():
        return None
    row = db.get_opportunity(conn, opp_id)
    return campaign_intelligence.ensure_for_opportunity(conn, row)


def _set_ci(conn, db, ci, key: str, value: str) -> None:
    """Write one Campaign Intelligence value the ordinary way.

    `canonical_slot` derives the facet from the key rather than us guessing one — the
    same rule ADR-0064 exists for. `confirmed=True` because a rehearsal is authored by
    the operator, so these land as settled facts rather than machine proposals waiting
    in a queue nobody wants to clear before testing.
    """
    from . import campaign_intelligence
    facet, k, kind = campaign_intelligence.canonical_slot("engagement", key, "fact")
    campaign_intelligence.contribute(conn, ci["id"], facet, k, value, kind=kind,
                                     source=SOURCE, contributed_by="rehearsal",
                                     confirmed=True)
