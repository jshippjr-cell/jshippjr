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
  3  the pipeline has a date    (follow-ups due today or earlier)
  4  the deal's next move is yours (per-deal court-state, pointed inward)
  5  a composer is waiting at the taste gate (pending submissions)
  6  qualified-enough to look at (REVIEW-tier opportunities — the funnel
     audit's Finding 1: the volume the precision-biased alert tier hides)
  7  a reel awaits your verdict (talent review queue)
  8  the supply-side floor has a gap (ADR-0024: approved creator, no
     agreement/rate — not assignable until fixed)
  9  intelligence housekeeping  (CI conflicts, then proposed fields)

Age breaks ties within a rung (oldest first). No LLM anywhere.
"""
from __future__ import annotations

from datetime import date
from typing import List

from . import next_action

# The rung labels, indexable by urgency — the template renders these as section
# headings so the queue reads as priorities, not a jumble.
RUNGS = (
    "A client is waiting",
    "Money owed to us",
    "Money we owe our people",
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

    # 3 — follow-ups due on/before today.
    for r in db.followups_due(conn, limit=25):
        cards.append(_card(
            3, "followup",
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
                4, "next_action", f"{na['label']} — {opp['client']}",
                f"{na.get('detail', '')} ({opp['need']})", na["url"],
                age_key=na.get("since") or "", post=bool(na.get("post"))))

    # 5 — composer submissions waiting at the taste gate (publish gate).
    for prow in db.list_projects(conn):
        pv = db.get_delivery(conn, prow["id"]).get("pending_version")
        if pv:
            cards.append(_card(
                5, "submission",
                f"Submission to vet — {prow['client']}",
                f"{pv.get('by') or 'A composer'} uploaded a version on "
                f"{(pv.get('at') or '')[:10]}. Publish it or send it back — the "
                "client never sees unvetted work.",
                f"/project/{prow['id']}/delivery", age_key=pv.get("at") or ""))

    # 6 — REVIEW-tier opportunities: qualified-enough volume the precision-biased
    #     alert tier deliberately keeps quiet (funnel audit, Finding 1).
    rows = conn.execute(
        """SELECT * FROM opportunities
           WHERE needs_review = 1 AND status NOT IN ('Won','Lost','Passed')
           ORDER BY score DESC, created_at ASC LIMIT 15""").fetchall()
    for r in rows:
        cards.append(_card(
            6, "review_opp",
            f"Worth a look — {r['client'] or r['title'] or 'opportunity'}",
            f"Alignment {r['alignment'] or r['score'] or '?'} — routed REVIEW, "
            "never alerted. Confirm or pass.",
            f"/opportunity/{r['id']}", age_key=r["created_at"] or ""))

    # 7 — reels awaiting the founder's verdict (the talent quality gate).
    for row in conn.execute(
            "SELECT id, name, created_at FROM talent WHERE review_status = 'Pending' "
            "ORDER BY created_at ASC LIMIT 25").fetchall():
        cards.append(_card(
            7, "reel", f"Reel review — {row['name']}",
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
                8, "floor_gap", f"Not assignable — {row['name']}",
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
            9, "ci", f"{verb} — {r['ci_title'] or 'campaign'}",
            f"{r['facet']}.{r['key']}", url, age_key=r["updated_at"] or ""))

    cards.sort(key=lambda c: (c["urgency"], c["age_key"]))
    # Snoozed cards are withheld, not dropped: the row expires and the decision comes
    # back. `include_snoozed` is how the surface offers to show what it is hiding.
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
    return {"groups": groups, "total": len(cards), "today": date.today().isoformat(),
            "snoozed": snoozed, "showing_snoozed": include_snoozed}
