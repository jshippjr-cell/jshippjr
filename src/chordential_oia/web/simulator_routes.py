"""The objection simulator — practice against the buyer you are about to meet.

ADR-0044, slice 9. Seven routes and **no helpers at all**: the whole surface delegates to
:mod:`chordential_oia.web.simulator`, so this module is the thinnest of the series — the
routes open a connection, call the engine, and render.

**Declaration order is load-bearing here and nowhere else in the breakup.**
``/simulator/library`` and ``/simulator/{session_id}`` both match ``GET /simulator/library``;
the literal wins only because it is registered first. The extraction preserved source
order for exactly this reason, and `test_app_structure` pins it — reorder these two and
the library page silently becomes a session lookup for a session named "library".

Honest about what it is: the personas are scripted, and with no API key configured the
replies are deterministic canned lines rather than a model. `simulator.ai_available()`
is rendered into the page so the operator can see which one they are talking to.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db, simulator
from .shell import render

router = APIRouter(tags=["simulator"])


@router.get("/simulator", response_class=HTMLResponse)
def simulator_home(request: Request):
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)      # idempotent; inserts only what's missing
        sessions = db.list_sim_sessions(conn)
        proposed = db.list_objections(conn, status="proposed")
        confirmed = db.list_objections(conn, status="confirmed")
        return render(request, "simulator.html", nav="simulator",
                      personas=simulator.PERSONAS, sessions=sessions,
                      n_confirmed=len(confirmed), n_proposed=len(proposed),
                      ai_on=simulator.ai_available())
    finally:
        conn.close()


@router.post("/simulator/start")
def simulator_start(persona: str = Form(...)):
    if persona not in simulator.PERSONAS:
        return RedirectResponse("/simulator", status_code=303)
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)
        mode = "ai" if simulator.ai_available() else "scripted"
        sid = db.create_sim_session(conn, persona=persona, mode=mode)
        opening = simulator.PERSONAS[persona]["opening"]
        db.update_sim_session(conn, sid, transcript_json=json.dumps(
            [{"who": "buyer", "text": opening}]))
        return RedirectResponse(f"/simulator/{sid}", status_code=303)
    finally:
        conn.close()


@router.get("/simulator/library", response_class=HTMLResponse)
def simulator_library(request: Request):
    conn = db.connect()
    try:
        db.init_db(conn)
        simulator.seed_objections(conn)
        rows = db.list_objections(conn)
        by_family = {}
        for r in rows:
            by_family.setdefault(r["family"], []).append(r)
        return render(request, "simulator_library.html", nav="simulator",
                      by_family=by_family, families=simulator.FAMILIES)
    finally:
        conn.close()


@router.post("/simulator/library/{objection_id}/status")
def simulator_library_status(objection_id: int, status: str = Form(...)):
    conn = db.connect()
    try:
        db.set_objection_status(conn, objection_id, status)
        return RedirectResponse("/simulator/library", status_code=303)
    finally:
        conn.close()


@router.get("/simulator/{session_id}", response_class=HTMLResponse)
def simulator_session(request: Request, session_id: int):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None:
            return RedirectResponse("/simulator", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        scorecard = json.loads(s["scorecard_json"]) if s["scorecard_json"] else None
        coaching = {}
        if scorecard and scorecard.get("coaching"):
            coaching = {c["idx"]: c for c in scorecard["coaching"]}
        return render(request, "simulator_session.html", nav="simulator",
                      s=s, persona=simulator.PERSONAS.get(s["persona"], {}),
                      transcript=transcript, scorecard=scorecard, coaching=coaching)
    finally:
        conn.close()


@router.post("/simulator/{session_id}/say")
def simulator_say(session_id: int, text: str = Form(...)):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None or s["status"] != "live" or not text.strip():
            return RedirectResponse(f"/simulator/{session_id}", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        transcript.append({"who": "seller", "text": text.strip()})
        db.update_sim_session(conn, session_id, transcript_json=json.dumps(transcript))
        s = db.get_sim_session(conn, session_id)
        reply = simulator.buyer_reply(conn, s)
        buyer_turn = {"who": "buyer", "text": reply["text"]}
        if reply.get("objection_id"):
            buyer_turn["objection_id"] = reply["objection_id"]
        transcript.append(buyer_turn)
        used = json.loads(s["objections_used"] or "[]")
        if reply.get("objection_id"):
            used.append(reply["objection_id"])
        db.update_sim_session(conn, session_id, transcript_json=json.dumps(transcript),
                              objections_used=json.dumps(used))
        return RedirectResponse(f"/simulator/{session_id}", status_code=303)
    finally:
        conn.close()


@router.post("/simulator/{session_id}/end")
def simulator_end(session_id: int):
    conn = db.connect()
    try:
        s = db.get_sim_session(conn, session_id)
        if s is None:
            return RedirectResponse("/simulator", status_code=303)
        transcript = json.loads(s["transcript_json"] or "[]")
        used = json.loads(s["objections_used"] or "[]")
        card = simulator.grade(transcript, used)
        card["coaching"] = simulator.coach_turns(conn, transcript)
        from datetime import datetime, timezone
        db.update_sim_session(conn, session_id, status="ended",
                              scorecard_json=json.dumps(card),
                              ended_at=datetime.now(timezone.utc).isoformat())
        return RedirectResponse(f"/simulator/{session_id}", status_code=303)
    finally:
        conn.close()
