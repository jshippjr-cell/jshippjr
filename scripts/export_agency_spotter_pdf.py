#!/usr/bin/env python3
"""Export the Agency Spotter Agent's findings from the live database to a PDF.

The Agency Spotter Agent (the discovery crawler's ``agencyspotter`` source) walks
the agency directory and persists each agency as an inbound *crawl* lead — a buyer
to qualify. This script reads those leads straight from the database and renders a
branded findings PDF, the report-side bookend to the agent.

Run it where the real database lives (e.g. on Render, or against a copy):

    CHORDENTIAL_DB=/var/data/chordential.db \
        python scripts/export_agency_spotter_pdf.py --out agency_spotter_findings.pdf

Flags:
    --out PATH        Output PDF path (default ./agency_spotter_findings.pdf)
    --db  URL/PATH    Override CHORDENTIAL_DB for this run (SQLite path or pg URL)
    --all-crawl       Include every crawler-discovered lead, not just agencies
    --status STATUS   Only leads in this status (New/Reviewed/Qualified/…)

Notes / honest limits:
  * Crawl leads store company / need / description / status / discovered-at, but
    NOT the agency's profile URL (the ingest schema has no column for it), so the
    PDF can't link out per agency. Say the word and that's a one-column migration.
  * The selection/normalization logic is import-safe and unit-tested; only the PDF
    rendering needs the optional ``reportlab`` dependency (``pip install '.[pdf]'``),
    imported lazily so this module imports fine without it.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List, Optional


# --------------------------------------------------------------------------- #
# Selection (import-safe — no reportlab, no network)
# --------------------------------------------------------------------------- #
def select_agency_leads(
    conn, *, all_crawl: bool = False, status: Optional[str] = None
) -> List[Dict]:
    """Return crawler-discovered leads as plain dicts, newest first.

    By default keeps only Agency Spotter leads (recognized by the ``need`` text
    its parser stamps — crawl leads don't persist a source key). ``all_crawl``
    widens this to every crawler lead.
    """
    from chordential_oia.web import db
    from chordential_oia.web import crawl_adapters as ca

    rows = db.list_inbound_leads(conn, status=status)
    out: List[Dict] = []
    for r in rows:
        if (r["source"] or "") != "crawl":
            continue
        need = r["project_type"] or ""
        if not all_crawl and not ca.is_agency_need(need):
            continue
        created = (r["created_at"] or "")[:10]          # YYYY-MM-DD
        out.append({
            "company": r["company"] or "(unknown agency)",
            "need": need,
            "description": r["description"] or "",
            "status": r["status"] or "",
            "discovered": created,
        })
    return out


# --------------------------------------------------------------------------- #
# Rendering (lazy reportlab)
# --------------------------------------------------------------------------- #
def build_pdf(leads: List[Dict], out_path: str, *, all_crawl: bool = False) -> str:
    """Render ``leads`` to a PDF at ``out_path``; returns the path. Lazily imports
    reportlab so the rest of the module works without the optional dependency."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer,
                                        Table, TableStyle)
    except ImportError as e:  # pragma: no cover - depends on optional extra
        raise SystemExit(
            "reportlab is required to render the PDF — install it with "
            "`pip install '.[pdf]'` (or `pip install reportlab`)."
        ) from e

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=20, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=9,
                         textColor=colors.HexColor("#666666"), spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12, spaceBefore=10)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.5, leading=11)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")

    doc = SimpleDocTemplate(
        out_path, pagesize=letter, title="Agency Spotter — Findings",
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch)

    scope = "All discovered leads" if all_crawl else "Agency Spotter agencies"
    story = [
        Paragraph("Agency Spotter — Findings", h1),
        Paragraph(f"Chordential discovery crawler &middot; {scope} &middot; "
                  f"{len(leads)} record(s)", sub),
    ]

    if not leads:
        story.append(Paragraph(
            "No matching leads in the database yet. On Render, approve an Agency "
            "Spotter target from a signed-in session so the agent can fetch, then "
            "re-run this export.", cell))
        doc.build(story)
        return out_path

    header = [Paragraph(x, cellb) for x in
              ("#", "Agency", "Need", "Description", "Status", "Found")]
    data = [header]
    for i, l in enumerate(sorted(leads, key=lambda r: r["company"].lower()), 1):
        data.append([
            Paragraph(str(i), cell),
            Paragraph(_esc(l["company"]), cell),
            Paragraph(_esc(l["need"]), cell),
            Paragraph(_esc(l["description"]), cell),
            Paragraph(_esc(l["status"]), cell),
            Paragraph(_esc(l["discovered"]), cell),
        ])
    tbl = Table(
        data,
        colWidths=[0.3 * inch, 1.8 * inch, 1.7 * inch, 2.2 * inch, 0.8 * inch, 0.7 * inch],
        repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#dddddd")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 10))
    story.append(Paragraph(
        "Each agency sits in the inbound-lead review queue as a buyer to qualify "
        "(<i>the machine proposes, Jon disposes</i>).", sub))
    doc.build(story)
    return out_path


def _esc(s: str) -> str:
    """Minimal XML escaping for reportlab Paragraph text."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Export Agency Spotter findings to PDF.")
    ap.add_argument("--out", default="agency_spotter_findings.pdf", help="Output PDF path")
    ap.add_argument("--db", default=None, help="Override CHORDENTIAL_DB for this run")
    ap.add_argument("--all-crawl", action="store_true",
                    help="Include every crawler lead, not just Agency Spotter")
    ap.add_argument("--status", default=None, help="Filter to a single lead status")
    args = ap.parse_args(argv)

    if args.db:
        os.environ["CHORDENTIAL_DB"] = args.db

    from chordential_oia.web import db
    conn = db.connect()
    db.init_db(conn)  # safe/idempotent; no-op on an existing DB
    leads = select_agency_leads(conn, all_crawl=args.all_crawl, status=args.status)

    out = build_pdf(leads, args.out, all_crawl=args.all_crawl)
    print(f"Wrote {len(leads)} record(s) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
