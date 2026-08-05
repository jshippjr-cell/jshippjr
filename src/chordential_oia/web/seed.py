"""Populate the dashboard database with opportunities.

Pulls from every registered source plus any sample alert emails, de-duplicates
on (client, need), evaluates each through the engines, and stores it. Safe to
call repeatedly — existing rows are skipped.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import List

from ..delivery import build_delivery_zip, version_label, version_name
from .estimate import estimate_for
from ..intake import parse_email_path
from ..models import MusicDiscipline, Opportunity
from ..sources import AVAILABLE_SOURCES
from ..talent import InviteStatus, ReviewStatus, Talent
from ..talent_sources import AVAILABLE_TALENT_SOURCES
from . import db
from . import showcase as _showcase  # demo audio URLs (review players play)
from .evaluate import evaluate

# A small starter roster so the supply side isn't empty on first run, and so the
# matcher (next cycle) has real profiles to rank. Mix of disciplines, review
# states, and funnel stages.
_TALENT_SEED = [
    Talent(
        name="Maya Okafor", email="maya@okaforsound.com",
        disciplines=[MusicDiscipline.COMPOSITION, MusicDiscipline.ARRANGEMENT],
        credits="Composer on 2 national auto spots; orchestral arranger for a Netflix doc.",
        location="Los Angeles, CA", demo_reel_url="https://example.com/reels/maya-okafor",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED,
        rate=95.0, rate_unit="hourly",
    ),
    Talent(
        name="Devin Park", email="devin@parkaudio.io",
        disciplines=[MusicDiscipline.SOUND_DESIGN, MusicDiscipline.COMPOSITION],
        credits="Sound designer for indie games; hybrid score for a brand campaign.",
        location="Brooklyn, NY", demo_reel_url="https://example.com/reels/devin-park",
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.INVITED,
        rate=80.0, rate_unit="hourly",
    ),
    Talent(
        name="Sofia Marin", email="sofia@marinmusic.com",
        disciplines=[MusicDiscipline.SONIC_BRANDING, MusicDiscipline.COMPOSITION],
        credits="Sonic logo for a fintech launch; mnemonic system for a retail brand.",
        location="Austin, TX", demo_reel_url="https://example.com/reels/sofia-marin",
        review_status=ReviewStatus.PENDING, invite_status=InviteStatus.PROSPECT,
    ),
    Talent(
        name="Theo Nguyen",
        disciplines=[MusicDiscipline.SUPERVISION],
        credits="Music supervisor; cleared sync for branded content and trailers.",
        location="Remote", review_status=ReviewStatus.PENDING,
        invite_status=InviteStatus.PROSPECT,
    ),
]

_SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "samples",
)


def gather_opportunities() -> List[Opportunity]:
    opps: List[Opportunity] = []
    for cls in AVAILABLE_SOURCES.values():
        opps.extend(cls().fetch(limit=50))
    if os.path.isdir(_SAMPLES_DIR):
        try:
            opps.extend(parse_email_path(_SAMPLES_DIR))
        except Exception:
            pass
    return opps


def seed(conn: sqlite3.Connection) -> int:
    """Insert any not-yet-stored opportunities. Returns the number added."""
    db.init_db(conn)
    added = 0
    for opp in gather_opportunities():
        if not db.opportunity_exists(conn, opp.client, opp.need):
            db.insert_opportunity(conn, opp)
            added += 1
    return added


def seed_talent(conn: sqlite3.Connection) -> int:
    """Populate the starter talent roster if it's empty. Returns the number added.

    Approved members model the ADR-0024 compliant state (executed agreement +
    rate) so the demo shows what "assignable" looks like; pending prospects stay
    unsigned — the assignment gate refusing them is part of the demo's honesty."""
    db.init_db(conn)
    if db.talent_count(conn) > 0:
        return 0
    for t in _TALENT_SEED:
        tid = db.insert_talent(conn, t)
        if t.review_status == ReviewStatus.APPROVED:
            db.set_talent_agreement(
                conn, tid, date.today().isoformat(), "Standing Composer Agreement (demo)")
    return len(_TALENT_SEED)


def ingest_talent_prospects(conn: sqlite3.Connection) -> int:
    """Pull candidates from the registered talent sources into the roster.

    Each source yields Pending/Prospect creators (the review gate); we stamp the
    source key as provenance and de-dupe on name+email so repeated boots don't
    create duplicates. Sources fail soft — a broken one is skipped, never fatal.
    In the sandbox/CI only the demo source is registered (no network).
    """
    db.init_db(conn)
    added = 0
    for key, factory in AVAILABLE_TALENT_SOURCES.items():
        try:
            candidates = factory().fetch()
        except Exception:  # fail soft — a dead source never blocks startup
            continue
        for t in candidates:
            if db.talent_exists(conn, t.name, t.email):
                continue
            t.source = t.source or key
            db.insert_talent(conn, t)
            added += 1
    return added


def _suggested_price(opp: Opportunity) -> float:
    """Suggested price via the one estimate path (ADR-0033), so a seeded deal's
    recorded value matches what the estimate page shows for the same deal."""
    return estimate_for(opp).suggested_price


def seed_demo_pipeline(conn: sqlite3.Connection) -> bool:
    """Stage one tentative bid and one closed win so the Executive Summary's
    pipeline columns show live data on a fresh database.

    Mirrors what Jon would do by hand (submit a bid; mark a deal Won; spin up a
    project and assign approved crew) — it adds nothing the normal flow can't.
    Idempotent: a no-op once any ``Submitted``/``Won`` deal already exists.
    """
    db.init_db(conn)
    if conn.execute(
        "SELECT COUNT(*) FROM opportunities WHERE status IN ('Submitted','Won')"
    ).fetchone()[0]:
        return False
    rows = conn.execute(
        "SELECT * FROM opportunities WHERE qualified = 1 ORDER BY alignment DESC"
    ).fetchall()
    if len(rows) < 2:
        return False
    bid_row, won_row = rows[0], rows[1]

    # 1) Tentative — a bid that's out for decision.
    bid_price = _suggested_price(db.opportunity_from_row(bid_row))
    db.update_status(conn, bid_row["id"], "Submitted", round(bid_price))
    db.update_outreach(
        conn, bid_row["id"],
        next_action="Awaiting decision on submitted bid",
        next_action_due=(date.today() + timedelta(days=5)).isoformat(),
    )

    # 2) Won — a closed deal spun up into a project with assigned crew.
    won_opp = db.opportunity_from_row(won_row)
    q, _ = evaluate(won_opp)
    won_price = estimate_for(won_opp, qual=q).suggested_price
    db.update_status(conn, won_row["id"], "Won", round(won_price))
    roles = q.team_shape or ["Composer", "Mixer"]
    pid = db.insert_project(
        conn, won_row["id"], won_row["client"], won_row["need"],
        won_row["budget_min"], won_row["budget_max"], roles,
    )
    matchable = [t for t in db.load_talent(conn) if t.matchable]
    for role, t in zip(roles, matchable):
        db.add_assignment(conn, pid, role, t.id)
    return True


# --------------------------------------------------------------------------- #
# Delivery OS (Phase 5) — seed fictional campaigns at different lifecycle stages
#
# Three invented-but-realistic campaigns so the whole delivery experience is
# walkable end to end: a just-briefed one (brief, no comments yet), an in-review
# one (the Frame.io-for-music portal: two versions, timestamped agency comments, a
# change request, Round 2 of 3), and an approved+delivered one (FINAL locked, the
# delivery ZIP built, full timeline). HONESTY: invented brands only — never real
# trademarks (see docs/capability-demos-council.md). The version/asset audio reuse
# the showcase Cloudinary mp3s so the review players actually PLAY in the demo.
# --------------------------------------------------------------------------- #
# A marker so the seed is idempotent and identifiable as demo data.
_DELIVERY_DEMO_CLIENTS = ("Lumen Health", "Vance Athletic", "Northwind Coffee")

# Standard license terms for the delivered demo (Chordential's own defaults).
# NOTE (showcase honesty): no ``content_id`` override here — the delivered demo's
# clearance certificate uses the engine's honest IP3 default ("Registrable with
# Content ID"), never the bare "Content-ID-safe" claim the engine was rebuilt to kill.
_DELIVERY_DEMO_LICENSE = {
    "type": "Buyout of master + perpetual sync licence",
    "publishing": "Composition publishing retained by Chordential Music",
    "media": "All campaign media — broadcast, digital, social, OOH, in-store",
    "territory": "Worldwide",
    "term": "Perpetuity",
    "exclusivity": "Exclusive to client for the campaign category",
}

# Cloudinary mp3s from the showcase — real, playable, copyright-clean demo audio.
_DEMO_AUDIO = [d.audio_url for d in _showcase.DEMOS if d.audio_url]

# A small, copyright-clean demo master committed into the repo (a soft two-note
# pad rendered once with ffmpeg). It's bundled into UPLOAD_DIR so the delivered
# demo's "Download everything" ZIP contains a REAL local audio file, not just docs.
_BUNDLED_DEMO_AUDIO = os.path.join(
    os.path.dirname(__file__), "static", "public", "demo-anthem.mp3"
)


def _demo_audio(i: int) -> str:
    """A playable showcase mp3 URL (cycles through the four demos)."""
    return _DEMO_AUDIO[i % len(_DEMO_AUDIO)] if _DEMO_AUDIO else ""


def _stage_bundled_master(conn, upload_dir: str, filename: str) -> bool:
    """Copy the committed demo master into ``upload_dir`` under ``filename``.

    Lets ``build_delivery_zip`` bundle a REAL local audio file (it only packages
    on-disk files with a real ``filename``). Returns True on success. Fail-soft:
    a missing source or a copy error returns False and never raises, so seeding
    never crashes if the bundle is absent.

    Goes through ``_persist_upload`` — the write door — rather than calling the store
    directly. Calling the store directly is what broke this in production: the demo
    master landed on the ephemeral disk and in whatever store was active *at seed time*,
    never in the SQLite mirror. Seeding is idempotent, so it never ran again; the first
    redeploy wiped the disk and the demo campaign's ":60 master" and "Download
    everything" have been dead ever since. Found by the /settings/storage audit, which
    named this file and the ZIP built from it as the only two the database references
    and no store holds.
    """
    try:
        if not os.path.isfile(_BUNDLED_DEMO_AUDIO):
            return False
        with open(_BUNDLED_DEMO_AUDIO, "rb") as fh:
            data = fh.read()
        from .uploads import _persist_upload
        _persist_upload(conn, filename, data, "audio/mpeg")
        # The local copy is separate from durability: build_delivery_zip packages
        # files off the filesystem, so it needs one whatever the active store is.
        import shutil
        os.makedirs(upload_dir, exist_ok=True)
        shutil.copyfile(_BUNDLED_DEMO_AUDIO, os.path.join(upload_dir, filename))
        return True
    except Exception:
        return False


def _demo_talent_id(conn: sqlite3.Connection, name: str, email: str,
                    disciplines, credits: str) -> int:
    """Find-or-create a named demo creator; return their talent id."""
    row = conn.execute(
        "SELECT id FROM talent WHERE name = ? LIMIT 1", (name,)
    ).fetchone()
    if row is not None:
        return int(row[0])
    tid = db.insert_talent(conn, Talent(
        name=name, email=email, disciplines=disciplines, credits=credits,
        review_status=ReviewStatus.APPROVED, invite_status=InviteStatus.JOINED,
        source="demo_delivery", rate=90.0, rate_unit="hourly",
    ))
    # Demo creators get assigned to demo projects — they must clear the ADR-0024
    # assignment gate the same way a real creator would.
    db.set_talent_agreement(
        conn, tid, date.today().isoformat(), "Standing Composer Agreement (demo)")
    return tid


def _iso(days_ago: int, *, hour: int = 12, minute: int = 0) -> str:
    """An ISO-8601 UTC timestamp ``days_ago`` days before now (deterministic-ish)."""
    when = datetime.now(timezone.utc).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    ) - timedelta(days=days_ago)
    return when.isoformat()


def seed_delivery_demo(conn: sqlite3.Connection) -> bool:
    """Seed three fictional campaigns at different Delivery OS lifecycle stages.

    (a) Just briefed — a fresh brief, v1 Concept, no comments yet.
    (b) In review, mid-revision — v1 + v2 uploaded, timestamped agency comments,
        one change request, Round 2 of 3, state In review (the review portal).
    (c) Approved & delivered — FINAL locked, the delivery ZIP built + checklist,
        state Released, full timeline.

    Idempotent (a no-op once its campaigns exist) and fail-soft (never blocks
    startup). Returns True only when it created the campaigns this call."""
    db.init_db(conn)
    try:
        existing = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE client IN (?,?,?)",
            _DELIVERY_DEMO_CLIENTS,
        ).fetchone()[0]
        if existing:
            return False  # already seeded — touch nothing

        from datetime import date as _date
        from ..models import MusicDiscipline as _MD

        # Named creators (chain of title on the certificates / cue sheets).
        composer_a = _demo_talent_id(
            conn, "Mara Velez", "mara@velezsound.com",
            [_MD.COMPOSITION, _MD.ARRANGEMENT],
            "Composer for brand campaigns; orchestral-hybrid scores.")
        composer_b = _demo_talent_id(
            conn, "Ezra Cole", "ezra@coleaudio.com",
            [_MD.COMPOSITION, _MD.SONIC_BRANDING],
            "Composer + sonic-branding lead for national spots.")
        mixer = _demo_talent_id(
            conn, "Priya Nair", "priya@nairmix.com",
            [_MD.SOUND_DESIGN, _MD.COMPOSITION],
            "Mix engineer; broadcast masters and stem delivery.")

        # ----------------------------------------------------------------- #
        # (a) Just briefed — Lumen Health — Brand Refresh.
        # ----------------------------------------------------------------- #
        pid_a = db.insert_project(
            conn, None, "Lumen Health", "Brand Refresh",
            12000.0, 18000.0, ["Composer"],
            deadline=(_date.today() + timedelta(days=21)).isoformat(),
        )
        db.add_assignment(conn, pid_a, "Composer", composer_a)
        db.save_delivery(conn, pid_a, {
            "state": "In production",
            "version_state": "v1 Concept",
            "revisions_used": 0,
            "brief": {
                "objective": "A calm, trustworthy sonic identity for Lumen Health's "
                             "brand refresh — to carry across app, explainer, and OOH.",
                "references": "Warm, human, unhurried — modern healthcare without the "
                              "clinical coldness.",
                "tone": "Reassuring, clear, optimistic.",
                "deliverables_needed": ":60 anthem, :30 + :15 cutdowns, sonic logo, stems.",
                "deadline": (_date.today() + timedelta(days=21)).isoformat(),
            },
        })

        # ----------------------------------------------------------------- #
        # (b) In review, mid-revision — Vance Athletic — Summer Launch.
        #     v1 + v2 uploaded (playable showcase audio), timestamped agency
        #     comments + one change request, Round 2 of 3, state In review.
        # ----------------------------------------------------------------- #
        pid_b = db.insert_project(
            conn, None, "Vance Athletic", "Summer Launch",
            22000.0, 30000.0, ["Composer", "Mixer"],
            deadline=(_date.today() + timedelta(days=10)).isoformat(),
        )
        db.add_assignment(conn, pid_b, "Composer", composer_b)
        db.add_assignment(conn, pid_b, "Mixer", mixer)
        versions_b = [
            {
                "n": 1, "label": version_label(1),
                "url": _demo_audio(2), "filename": "",
                "name": version_name("Vance Athletic", "Anthem", 60, "Master", 1, ""),
                "created_at": _iso(6, hour=10),
            },
            {
                "n": 2, "label": version_label(2),
                "url": _demo_audio(0), "filename": "",
                "name": version_name("Vance Athletic", "Anthem", 60, "Master", 2, ""),
                "created_at": _iso(2, hour=15),
            },
        ]
        token_b = db.ensure_project_share_token(conn, pid_b)
        db.save_delivery(conn, pid_b, {
            "state": "In review",
            "version_state": version_label(2),
            "revisions_used": 1,           # Round 2 of 3 (one round used).
            "versions": versions_b,
            "share_token": token_b,
            "assets": [
                {"label": "Anthem :60 (v2)", "url": _demo_audio(0),
                 "filename": "", "kind": "audio"},
            ],
            "brief": {
                "objective": "An energetic :60 anthem for Vance Athletic's Summer "
                             "Launch — broadcast plus social cutdowns.",
                "references": "Driving, optimistic, momentum-forward; organic meets "
                              "modern production.",
                "tone": "Bold, kinetic, confident.",
                "deliverables_needed": ":60 anthem, :30/:15 cutdowns, :06 bumper, stems.",
                "deadline": (_date.today() + timedelta(days=10)).isoformat(),
            },
        })
        # Timestamped review activity from named agency people (the portal tape).
        # The portal tags every comment with the version NUMBER it was made against
        # (anti-chaos — matches the running app's ``_current_version_tag``) and the
        # default portal view filters to the CURRENT version. So the live
        # discussion + change request land on v2 (the current under-review version),
        # appearing by default when the portal opens; one earlier note stays on v1
        # to demonstrate the version-history navigation (?v=1).
        db.add_review_comment(
            conn, pid_b, version="1", t_seconds=12,
            author="Dana Whitfield (Producer)",
            body="Love the energy out of the gate — the :12 lift is exactly the hook "
                 "we pitched. Can we hold it two beats longer?", kind="comment")
        db.add_review_comment(
            conn, pid_b, version="2", t_seconds=34,
            author="Marcus Lindell (Creative Director)",
            body="At 0:34 the drums get a touch busy under the VO bed — pull them "
                 "back so the line breathes.", kind="comment")
        db.add_review_comment(
            conn, pid_b, version="2", t_seconds=48,
            author="Sofia Reyes (Client — Vance Athletic)",
            body="v2 is close. The 0:48 chorus lands much better now. One more pass on "
                 "the ending and I think we're there.", kind="comment")
        db.add_review_comment(
            conn, pid_b, version="2", t_seconds=None,
            author="Marcus Lindell (Creative Director)",
            body="Direction's right. For the next pass: lengthen the hook, thin the "
                 "percussion under the VO, and brighten the final chorus. That gets "
                 "us to lock.", kind="change_request")

        # ----------------------------------------------------------------- #
        # (c) Approved & delivered — Northwind Coffee — Holiday Anthem.
        #     Approved, FINAL locked, the delivery ZIP built + checklist,
        #     state Released, full timeline.
        # ----------------------------------------------------------------- #
        pid_c = db.insert_project(
            conn, None, "Northwind Coffee", "Holiday Anthem",
            16000.0, 24000.0, ["Composer", "Mixer"],
            deadline=(_date.today() - timedelta(days=3)).isoformat(),
        )
        db.add_assignment(conn, pid_c, "Composer", composer_a)
        db.add_assignment(conn, pid_c, "Mixer", mixer)
        versions_c = [
            {
                "n": 1, "label": version_label(1),
                "url": _demo_audio(0), "filename": "",
                "name": version_name("Northwind Coffee", "Anthem", 60, "Master", 1, ""),
                "created_at": _iso(20, hour=11),
            },
            {
                "n": 2, "label": version_label(2),
                "url": _demo_audio(3), "filename": "",
                "name": version_name("Northwind Coffee", "Anthem", 60, "Master", 2, ""),
                "created_at": _iso(14, hour=16),
            },
            {
                "n": 3, "label": version_label(3, final=True),
                "url": _demo_audio(0), "filename": "",
                "name": version_name("Northwind Coffee", "Anthem", 60, "Master", 3, "FINAL"),
                "created_at": _iso(8, hour=13),
            },
        ]
        token_c = db.ensure_project_share_token(conn, pid_c)
        license_c = dict(_DELIVERY_DEMO_LICENSE)

        # Showcase honesty: stage the committed demo master into UPLOAD_DIR under a
        # real filename so build_delivery_zip bundles ACTUAL local audio (it only
        # packages on-disk files with a real ``filename``). Fail-soft — if the copy
        # fails, the asset simply has no local file and is recorded as referenced.
        upload_dir = (os.environ.get("CHORDENTIAL_UPLOAD_DIR")
                      or os.path.join(os.path.dirname(__file__), "uploads"))
        master_filename = "demo-northwind-master.mp3"
        staged = _stage_bundled_master(conn, upload_dir, master_filename)

        assets_c = [
            {"label": "Anthem :30 cutdown", "url": _demo_audio(3),
             "filename": "", "kind": "audio"},
        ]
        # The :60 master — a real local file (when staged) so the ZIP is non-empty.
        assets_c.insert(0, {
            "label": "Anthem :60 master", "url": _demo_audio(0),
            "filename": master_filename if staged else "",
            "kind": "audio", "folder": "Masters",
        })

        delivery_c = {
            "state": "Delivered",          # bumped to Released after the ZIP builds.
            "version_state": version_label(3, final=True),
            "revisions_used": 2,
            "versions": versions_c,
            "share_token": token_c,
            "license": license_c,
            # IP3: a released campaign has its license explicitly confirmed (so the
            # certificate asserts the grant, not a "DRAFT — pending confirmation").
            "license_confirmed": {"by": "Jon Shipp", "date": _iso(7)[:10]},
            "signatory": {"entity": "Chordential Music", "signer": "Jon Shipp",
                          "title": "Founder"},
            "approvals": [{
                "asset": "Anthem :60 — FINAL",
                "approver": "Priya Okonkwo (Creative Director — Northwind Coffee)",
                "date": _iso(7)[:10],
            }],
            "assets": assets_c,
            "brief": {
                "objective": "A warm, nostalgic :60 holiday anthem for Northwind "
                             "Coffee — broadcast plus social cutdowns.",
                "references": "Cozy, cinematic, celebratory; strings and a memorable "
                              "melodic theme without seasonal cliché.",
                "tone": "Warm, generous, hopeful.",
                "deliverables_needed": ":60 anthem, :30/:15 cutdowns, stems, cue sheet.",
                "deadline": (_date.today() - timedelta(days=3)).isoformat(),
            },
        }
        db.save_delivery(conn, pid_c, delivery_c)
        # Review tape: comments → change request → approval → release.
        db.add_review_comment(
            conn, pid_c, version="v1 Concept", t_seconds=8,
            author="Will Hartley (Producer)",
            body="Gorgeous opening — the strings at 0:08 set the whole mood.",
            kind="comment")
        db.add_review_comment(
            conn, pid_c, version="v1 Concept", t_seconds=None,
            author="Priya Okonkwo (Creative Director)",
            body="One round of notes: lift the final chorus and tighten the :30 edit.",
            kind="change_request")
        db.add_review_comment(
            conn, pid_c, version="v3 FINAL", t_seconds=None,
            author="Priya Okonkwo (Creative Director — Northwind Coffee)",
            body="Approved the current version.", kind="approval")

        # Build the real delivery ZIP + checklist (Phase 3 automation). The docs
        # (cue sheet, metadata, rights certificate, manifest) are generated
        # deterministically; the :60 master is a real bundled local file (the
        # cutdown is remote-referenced) so "Download everything" yields real audio.
        # Fail-soft: a packaging hiccup never blocks the seed.
        try:
            os.makedirs(upload_dir, exist_ok=True)
            project_c = db.get_project(conn, pid_c)
            assignments_c = db.list_assignments(conn, pid_c)
            pkg = build_delivery_zip(
                project_c, assignments_c, db.get_delivery(conn, pid_c), upload_dir,
                generated_at=_iso(7),
            )
            # ADR-0043: the built ZIP goes through the write door, so the demo's
            # "Download everything" works whichever backend is configured AND keeps a
            # second copy. It used to call the store directly and skip the mirror —
            # same bug as the master above, and the audit found them together.
            try:
                from .uploads import _persist_upload
                with open(os.path.join(upload_dir, os.path.basename(pkg["filename"])), "rb") as fh:
                    _persist_upload(conn, os.path.basename(pkg["filename"]), fh.read(),
                                    "application/zip")
            except OSError:
                pass
            db.update_delivery(conn, pid_c, "delivery_zip", {
                "filename": pkg["filename"], "url": pkg["url"],
                "built_at": pkg["built_at"],
            })
            db.update_delivery(conn, pid_c, "delivery_checklist", pkg["checklist"])
        except Exception:
            pass  # fail-soft — the campaign is still walkable without the ZIP
        # The hand-off is complete — mark it Released with a release stamp.
        db.update_delivery(conn, pid_c, "state", "Released")
        db.update_delivery(conn, pid_c, "released_at", _iso(6)[:10])
        return True
    except Exception:
        # Never block startup on a demo-seed failure.
        return False


def reset_and_seed(db_path: str = db.DEFAULT_DB_PATH) -> int:
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = db.connect(db_path)
    try:
        return seed(conn)
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Demo data control — seed placeholders for dev/tests, clean slate in production
# --------------------------------------------------------------------------- #
# Opportunities created through the real flow carry these sources; anything else
# in the opportunities table is build/demo placeholder data.
_REAL_OPP_SOURCES = ("signal", "front_of_house", "lead_indicator")


def seed_demo_enabled() -> bool:
    """Seed the demo dataset only when explicitly asked (dev/tests). Off by
    default so production shows a clean slate — your real data only."""
    return os.environ.get("CHORDENTIAL_SEED_DEMO", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def purge_demo_data(conn: sqlite3.Connection) -> int:
    """Remove the build's placeholder opportunities/talent/projects so the
    dashboard shows only real data. Runs only while placeholders are present, and
    never deletes opportunities created through the real flow (signal/lead
    promotes) or talent that applied. Returns how many opportunities were removed."""
    db.init_db(conn)
    keep = ",".join("?" * len(_REAL_OPP_SOURCES))
    demo = [
        r[0] for r in conn.execute(
            f"SELECT id FROM opportunities WHERE IFNULL(source,'') NOT IN ({keep})",
            _REAL_OPP_SOURCES,
        ).fetchall()
    ]
    if not demo:
        return 0  # already clean — touch nothing (protects manually-added rows)
    ph = ",".join("?" * len(demo))
    proj = [r[0] for r in conn.execute(
        f"SELECT id FROM projects WHERE opp_id IN ({ph})", demo).fetchall()]
    if proj:
        pph = ",".join("?" * len(proj))
        for tbl in ("assignments", "milestones", "project_updates", "invoices"):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE project_id IN ({pph})", proj)
            except Exception:
                pass
    for stmt in (
        f"DELETE FROM proposals WHERE opp_id IN ({ph})",
        f"DELETE FROM projects WHERE opp_id IN ({ph})",
        f"DELETE FROM outreach_events WHERE opp_id IN ({ph})",
        f"DELETE FROM brief_progress WHERE opp_id IN ({ph})",
        f"UPDATE inbound_leads SET linked_opp_id = NULL WHERE linked_opp_id IN ({ph})",
    ):
        try:
            conn.execute(stmt, demo)
        except Exception:
            pass
    removed = conn.execute(
        f"DELETE FROM opportunities WHERE id IN ({ph})", demo).rowcount
    # All seeded talent is demo; keep only creators who actually applied — AND
    # anyone still assigned to a surviving project (deleting them would orphan
    # live assignments; Phase-2 watchlist: the seed-idempotency guard).
    try:
        conn.execute(
            "DELETE FROM talent WHERE IFNULL(source,'') != 'applicant' "
            "AND id NOT IN (SELECT talent_id FROM assignments WHERE talent_id IS NOT NULL)")
    except Exception:
        pass
    conn.commit()
    return removed
