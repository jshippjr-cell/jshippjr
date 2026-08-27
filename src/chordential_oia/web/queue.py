"""The Disposition Queue — every pending founder decision, one ranked surface.

The company-architecture blueprint's §8.1: the machine-proposes law made
*ergonomic*. Every department's pending state lands here as a card —
recommendation + evidence + a link to the EXISTING decision surface. This module
is pure aggregation over queries that already exist: it computes and ranks, it
never decides, and it adds zero new decision logic (ADR-0002 — the web layer
renders and routes; the decision buttons stay where they live today).

Ranking is a deterministic urgency ladder — revenue- and client-touching first:

  0  a client is waiting        (new discovery-call requests)
  1  money is owed to us        (issued, unpaid invoices)
  2  money we owe our people    (Owed payouts — the composer-side brand)
  3  someone signed and is waiting on us (a composer's agreement, or a client's
     proposal, signed and awaiting our countersignature)
  4  the pipeline has a date    (follow-ups due today or earlier)
  5  the deal's next move is yours (per-deal court-state, pointed inward)
  6  a composer is waiting at the taste gate (pending submissions)
  7  qualified-enough to look at (REVIEW-tier opportunities — the funnel
     audit's Finding 1: the volume the precision-biased alert tier hides)
  8  a reel awaits your verdict (talent review queue)
  9  the supply-side floor has a gap (ADR-0024: approved creator, no
     agreement/rate — not assignable until fixed)
  10 intelligence housekeeping  (CI conflicts, then proposed fields)

Age breaks ties within a rung (oldest first). No LLM anywhere.
"""
from __future__ import annotations

from datetime import date
from typing import List

from . import billing, delivery_ops, next_action, opportunity_ops

# The rung labels, indexable by urgency — the template renders these as section
# headings so the queue reads as priorities, not a jumble.
RUNGS = (
    "A client is waiting",
    "Money owed to us",
    "Money we owe our people",
    "Signed — waiting on your countersignature",
    "Follow-ups due",
    "Your move on a deal",
    "Composer submissions at the taste gate",
    "Worth a look (REVIEW-tier)",
    "Reels awaiting your verdict",
    "Supply-side floor gaps",
    "Intelligence housekeeping",
)


def card_key(kind: str, url: str) -> str:
    """A card's stable identity. Cards are COMPUTED — they have no row — so the only
    thing a snooze can be keyed by is what the card points at plus what kind of
    decision it is. Two cards that share both are the same decision."""
    return f"{kind}:{url}"


def _card(urgency: int, kind: str, title: str, detail: str, url: str,
          age_key: str = "", evidence: str = "", post: bool = False) -> dict:
    return {"urgency": urgency, "kind": kind, "title": title, "detail": detail,
            "url": url, "age_key": age_key or "9999-12-31", "evidence": evidence,
            "post": post, "key": card_key(kind, url)}


def compute_queue(conn, db, *, include_snoozed: bool = False) -> List[dict]:
    """Every pending decision, ranked. Pure reads; safe to call on any request."""
    cards: List[dict] = []

    # 0 — a client asked for a discovery call and nobody has answered yet.
    for r in db.list_discovery_requests(conn, status="new"):
        who = (r["name"] or r["email"] or "Someone").strip()
        company = (r["company"] or "").strip()
        cards.append(_card(
            0, "discovery",
            f"{who}{' — ' + company if company else ''} requested a discovery call",
            f"Prefers {r['preferred_type']}. Waiting since {(r['created_at'] or '')[:10]}.",
            f"/opportunity/{r['opp_id']}/schedule" if r["opp_id"] else "/dashboard",
            age_key=r["created_at"] or ""))

    # 1 — issued invoices that haven't been paid (deposit or final).
    for prow in db.list_projects(conn):
        for inv in db.list_invoices(conn, prow["id"]):
            if (inv["status"] or "") != "Issued":
                continue
            cards.append(_card(
                1, "invoice",
                f"{inv['kind'] or 'Invoice'} unpaid — {prow['client']}",
                f"${(inv['amount'] or 0):,.0f} issued {(inv['created_at'] or '')[:10]} "
                f"({prow['need']}).",
                f"/project/{prow['id']}/proposal",
                age_key=inv["created_at"] or "",
                evidence=f"invoice #{inv['id']}"))

    # 2 — payouts owed to collaborators (pay from landed cash; W-9 first).
    for po in db.list_payouts(conn, "Owed"):
        w9 = (po["w9_received_at"] if "w9_received_at" in po.keys() else None)
        extra = "" if w9 else " ⚠ W-9 not on file — collect it before paying."
        cards.append(_card(
            2, "payout",
            f"Payout owed — {po['talent_name'] or 'creator'} ({po['role'] or 'crew'})",
            f"${(po['amount'] or 0):,.0f}.{extra}",
            "/payouts", age_key=po["created_at"] if "created_at" in po.keys() else "",
            evidence=f"payout #{po['id']}"))

    # 3 — somebody signed and is waiting on US. A composer signs their agreement and is
    #     assignable but not bound on both sides; a client signs a proposal and is waiting
    #     to be countersigned before anything starts. Both were only ever an email, and an
    #     email is not a queue — reported live: "when the talent signs the composer
    #     agreement and sends it back the chordential dashboard needs to get a
    #     notification." A signature is a pending DECISION, which is what this surface is.
    #     BOTH standing agreements are asked for (ADR-0082) — the Composer Agreement and
    #     the Service Agreement the mixers and editors sign. Querying only the composer's
    #     kind would have left every engineer's signature waiting on a countersignature
    #     nobody was ever told about.
    from .. import agreements as _agreements, signing as _signing
    for _kind in (_agreements.COMPOSER, _agreements.SERVICE):
        _label = _agreements.LABELS[_kind]
        for r in conn.execute(
                """SELECT s.talent_id, s.typed_name, s.signed_at, t.name AS talent_name
                   FROM signature s JOIN talent t ON t.id = s.talent_id
                   WHERE s.doc_kind = ? AND s.voided_at IS NULL AND s.talent_id > 0
                     AND NOT EXISTS (SELECT 1 FROM signature c
                                     WHERE c.talent_id = s.talent_id
                                       AND c.doc_kind = ? AND c.voided_at IS NULL)
                   ORDER BY s.signed_at ASC LIMIT 25""",
                (_agreements.DOC_KINDS[_kind], _agreements.COUNTERSIGN_KINDS[_kind])
        ).fetchall():
            cards.append(_card(
                3, "composer_countersign",
                f"Countersign — {r['talent_name'] or r['typed_name']}",
                f"They signed the {_label}. Countersign to bind it both ways.",
                f"/talent/{r['talent_id']}#access", age_key=r["signed_at"] or "",
                evidence=f"signed {(r['signed_at'] or '')[:10]}"))
    for r in conn.execute(
            """SELECT s.opportunity_id, s.typed_name, s.signed_at,
                      o.client AS client, o.need AS need
               FROM signature s JOIN opportunities o ON o.id = s.opportunity_id
               WHERE s.doc_kind = ? AND s.voided_at IS NULL AND s.opportunity_id > 0
                 AND NOT EXISTS (SELECT 1 FROM signature c
                                 WHERE c.opportunity_id = s.opportunity_id
                                   AND c.doc_kind = ? AND c.voided_at IS NULL)
               ORDER BY s.signed_at ASC LIMIT 25""",
            (_signing.DOC_PROPOSAL, _signing.DOC_PROPOSAL_COUNTERSIGN)
    ).fetchall():
        cards.append(_card(
            3, "proposal_countersign",
            f"Countersign — {r['client']}",
            f"{r['typed_name']} signed the proposal for {r['need']}. "
            f"Countersign, then start production.",
            f"/opportunity/{r['opportunity_id']}#agreement",
            age_key=r["signed_at"] or "",
            evidence=f"signed {(r['signed_at'] or '')[:10]}"))

    # 4 — follow-ups due on/before today.
    for r in db.followups_due(conn, limit=25):
        cards.append(_card(
            4, "followup",
            f"Follow up — {r['client']}",
            f"{(r['next_action'] or 'Next touch').strip()} (due {r['next_action_due']}).",
            f"/opportunity/{r['id']}", age_key=r["next_action_due"] or ""))

    # 4 — every active deal whose next move is the operator's (court == 'you'),
    #     computed by the same pure function the dashboard trusts.
    seen_opps = set()
    for prow in db.list_projects(conn):
        opp = db.get_opportunity(conn, prow["opp_id"]) if prow["opp_id"] else None
        if opp is None or opp["id"] in seen_opps:
            continue
        seen_opps.add(opp["id"])
        pv = db.get_delivery(conn, prow["id"]).get("pending_version")
        na = next_action.compute(conn, db, opp, prow)
        if na["court"] == "you" and na.get("url") and not pv:
            cards.append(_card(
                5, "next_action", f"{na['label']} — {opp['client']}",
                f"{na.get('detail', '')} ({opp['need']})", na["url"],
                age_key=na.get("since") or "", post=bool(na.get("post"))))

    # 5 — creator work waiting at the taste gate (publish gate): the TAKE, and the
    #     DELIVERABLES. Both wait for the same press and only the take had a card, so a
    #     stem package sat in the building with nothing on any page saying so.
    for prow in db.list_projects(conn):
        delivery = db.get_delivery(conn, prow["id"])
        pv = delivery.get("pending_version")
        if pv:
            cards.append(_card(
                6, "submission",
                f"Submission to vet — {prow['client']}",
                f"{pv.get('by') or 'A composer'} uploaded a version on "
                f"{(pv.get('at') or '')[:10]}. Publish it or send it back — the "
                "client never sees unvetted work.",
                f"/project/{prow['id']}/delivery", age_key=pv.get("at") or ""))
        # A DELIVERY NOBODY CAN BE BILLED FOR. Signed off, packaged, download locked —
        # and no invoice to unlock it with. It is the end of a job with the money still
        # out, and it had no card and no badge: *"that did not show up in my dashboard
        # to do with a red badge"* (operator, 2026-08-19).
        if (delivery.get("state") or "") in ("Delivered", "Released"):
            why = billing.final_invoice_block(conn, prow["id"])
            if why:
                cards.append(_card(
                    2, "money",
                    f"The client cannot pay — {prow['client']}",
                    billing.INVOICE_BLOCK_OPERATOR.get(why, "The balance cannot be raised."),
                    f"/project/{prow['id']}/delivery#assets",
                    age_key=delivery.get("released_at") or ""))
        # A DELIVERED package whose Clearance Certificate still reads DRAFT. The client
        # has it in hand; the grant it is supposed to certify was never asserted.
        if (delivery.get("state") or "") in ("Delivered", "Released"):
            held = delivery_ops.delivery_held_by(delivery, prow)
            if held == "licence":
                cards.append(_card(
                    2, "money",
                    f"Clearance certificate says DRAFT — {prow['client']}",
                    delivery_ops.DELIVERY_HELD["licence"],
                    f"/project/{prow['id']}/delivery#delivery",
                    age_key=delivery.get("released_at") or ""))
        zip_obj = delivery.get("delivery_zip") or {}
        if zip_obj.get("referenced_count"):
            cards.append(_card(
                1, "money",
                f"The package has no audio in it — {prow['client']}",
                f"{zip_obj['referenced_count']} of {zip_obj.get('asset_count') or '?'} "
                "files are not on the server, so the ZIP holds only documents. Rebuild it; "
                "anything the mirror has lost has to be re-uploaded.",
                f"/project/{prow['id']}/delivery#delivery",
                age_key=zip_obj.get("built_at") or ""))
        pending_assets = delivery.get("pending_assets") or []
        if pending_assets:
            lanes = {}
            for a in pending_assets:
                lanes.setdefault((a.get("label") or "a deliverable"), []).append(a)
            who = next((a.get("by") for a in pending_assets if a.get("by")), "A creator")
            newest = max((a.get("at") or "") for a in pending_assets)
            what = ", ".join(f"{label} ({len(items)})" for label, items in lanes.items())
            cards.append(_card(
                6, "submission",
                f"{len(pending_assets)} deliverable file"
                f"{'s' if len(pending_assets) != 1 else ''} to vet — {prow['client']}",
                f"{who} delivered {what}. Publish each to the client or send it back — "
                "the same gate the master gets.",
                f"/project/{prow['id']}/delivery#assets", age_key=newest))

    # 6 — REVIEW-tier opportunities: qualified-enough volume the precision-biased
    #     alert tier deliberately keeps quiet (funnel audit, Finding 1).
    rows = conn.execute(
        """SELECT * FROM opportunities
           WHERE needs_review = 1 AND status NOT IN ('Won','Lost','Passed')
           ORDER BY score DESC, created_at ASC LIMIT 15""").fetchall()
    for r in rows:
        cards.append(_card(
            7, "review_opp",
            f"Worth a look — {r['client'] or r['title'] or 'opportunity'}",
            f"Alignment {r['alignment'] or r['score'] or '?'} — routed REVIEW, "
            "never alerted. Confirm or pass.",
            f"/opportunity/{r['id']}", age_key=r["created_at"] or ""))

    # 7 — reels awaiting the founder's verdict (the talent quality gate).
    for row in conn.execute(
            "SELECT id, name, created_at FROM talent WHERE review_status = 'Pending' "
            "ORDER BY created_at ASC LIMIT 25").fetchall():
        cards.append(_card(
            8, "reel", f"Reel review — {row['name']}",
            "Approve or decline; approved creators become matchable.",
            f"/talent/{row['id']}", age_key=row["created_at"] or ""))

    # 8 — ADR-0024 floor gaps: approved (matchable-intent) creators who can't be
    #     assigned until the agreement/rate lands.
    for row in conn.execute(
            "SELECT * FROM talent WHERE review_status = 'Approved' "
            "ORDER BY created_at ASC LIMIT 25").fetchall():
        blockers = db.talent_assignment_blockers(row)
        if blockers:
            missing = " + ".join(
                {"agreement": "executed agreement", "rate": "rate"}[b]
                for b in blockers)
            cards.append(_card(
                9, "floor_gap", f"Not assignable — {row['name']}",
                f"Approved but missing {missing}. Fix before their next match.",
                f"/talent/{row['id']}#access", age_key=row["created_at"] or ""))

    # 9 — CI housekeeping: conflicts first (machine disagreed with a human-owned
    #     field), then proposed fields awaiting confirmation.
    for r in conn.execute(
            """SELECT f.id, f.ci_id, f.facet, f.key, f.status, f.updated_at,
                      ci.title AS ci_title, ci.opp_id AS opp_id
               FROM campaign_intelligence_field f
               JOIN campaign_intelligence ci ON ci.id = f.ci_id
               WHERE f.status IN ('conflicted', 'needs_review')
               ORDER BY CASE f.status WHEN 'conflicted' THEN 0 ELSE 1 END,
                        f.updated_at ASC LIMIT 25""").fetchall():
        verb = ("Conflict to resolve" if r["status"] == "conflicted"
                else "Proposed fact to confirm")
        url = f"/opportunity/{r['opp_id']}" if r["opp_id"] else "/dashboard"
        cards.append(_card(
            10, "ci", f"{verb} — {r['ci_title'] or 'campaign'}",
            f"{r['facet']}.{r['key']}", url, age_key=r["updated_at"] or ""))

    cards.sort(key=lambda c: (c["urgency"], c["age_key"]))
    # Snoozed cards are withheld, not dropped: the row expires and the decision comes
    # back. `include_snoozed` is how the surface offers to show what it is hiding.
    # Dismissals are hidden ALWAYS — including when the operator asks to see snoozed
    # cards, because those are two different questions ("what did I defer?" vs "what did I
    # decide was not mine?"). Each has its own line on the queue and its own way back.
    dismissed = db.dismissed_queue_keys(conn)
    if dismissed:
        cards = [c for c in cards if c["key"] not in dismissed]
    if not include_snoozed:
        hidden = db.snoozed_queue_keys(conn)
        if hidden:
            cards = [c for c in cards if c["key"] not in hidden]
    return cards


def queue_view(conn, db, *, include_snoozed: bool = False) -> dict:
    """The template's shape: cards grouped by rung, plus honest totals."""
    cards = compute_queue(conn, db, include_snoozed=include_snoozed)
    groups: List[dict] = []
    for i, label in enumerate(RUNGS):
        rows = [c for c in cards if c["urgency"] == i]
        if rows:
            groups.append({"label": label, "cards": rows})
    # How many are being withheld right now — named on the surface, never silent.
    snoozed = 0 if include_snoozed else len(db.snoozed_queue_keys(conn))
    dismissed = len(db.dismissed_queue_keys(conn))
    return {"groups": groups, "total": len(cards), "today": date.today().isoformat(),
            "snoozed": snoozed, "showing_snoozed": include_snoozed,
            "dismissed": dismissed}
