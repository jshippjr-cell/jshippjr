"""The notation world survives as a real route, with its scene beside it.

The page is one HTML template plus three static assets. The failure this file
exists to prevent is the quiet one: the template ships, the scene does not, and
the page renders a blank cream rectangle that looks deliberate. Every assertion
here ties a reference in the markup to a file on disk.

It also pins the ADR-0040 boundary. This page has no audio, so it is NOT the
front door — `/` must keep serving the Commission until the listening beat is
built. `test_hear_the_work.py` guards the homepage's music; this guards the
assumption that the world page has not quietly taken its place.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from chordential_oia.web.app import app

_WEB = os.path.dirname(os.path.abspath(__import__(
    "chordential_oia.web.public", fromlist=["public"]).__file__))
_STATIC = os.path.join(_WEB, "static", "public")


@pytest.fixture()
def client():
    return TestClient(app)


def test_the_score_page_renders(client):
    r = client.get("/score")
    assert r.status_code == 200
    assert "every part in the air" in r.text


def test_it_carries_the_copy_not_just_the_picture(client):
    """The words say everything the picture does — that is the no-WebGL2 promise."""
    body = client.get("/score").text
    for line in (
        "We compose original music for commercials and brand campaigns",
        "Every campaign begins with understanding.",
        "Everything arrives together.",
        "Start with a brief",
    ):
        assert line in body, line


def test_the_scene_assets_the_page_asks_for_actually_exist(client):
    """The markup names three files. All three must be on disk and non-empty."""
    body = client.get("/score").text
    for name in ("score-gl.js", "score-scene.json", "score-scene.bin"):
        assert name in body, f"{name} is not referenced by the page"
        path = os.path.join(_STATIC, name)
        assert os.path.exists(path), f"{name} is referenced but missing"
        assert os.path.getsize(path) > 0, f"{name} is empty"


def test_the_scene_binary_matches_the_offsets_its_metadata_claims():
    """A truncated buffer draws nothing and raises nothing — check the arithmetic."""
    meta = json.load(open(os.path.join(_STATIC, "score-scene.json")))
    size = os.path.getsize(os.path.join(_STATIC, "score-scene.bin"))
    need = meta["offPieces"] + meta["nPieces"] * 4 * 4
    assert size >= need, f"scene.bin is {size}B, offsets need {need}B"
    assert meta["nPieces"] > 0 and meta["nMarks"] > 0


def test_the_renderer_is_served_by_us(client):
    """Same-origin, like every other asset — nothing on this page comes from a CDN."""
    body = client.get("/score").text
    assert "/static/public/score-gl.js" in body
    assert "http://" not in body.split("<style>")[0]


def test_the_score_page_and_the_front_door_are_one_page(client):
    """`/` and `/score` share one renderer. Two addresses for the front door that
    could drift into showing different pages is exactly the defect this codebase
    keeps removing everywhere else."""
    a, b = client.get("/").text, client.get("/score").text
    assert "scoretracks" in a and "scoretracks" in b
    # asset-version query strings can differ between requests; compare the markup
    import re
    strip = lambda h: re.sub(r"\?v=\d+", "", h)
    assert strip(a) == strip(b), "/ and /score render differently"


# --------------------------------------------------------------------------- #
# The delivery beat lists the package the engine actually assembles
# --------------------------------------------------------------------------- #

def test_the_hero_says_what_the_company_does(client):
    """The first screen states the business in one sentence.

    It used to open on "Every note finds its place." over a paragraph — true to
    the page's character and silent on what is actually being sold. A visitor
    who reads only the first screen should come away knowing both halves of the
    offer: the music is composed, and everything around it is organised.
    """
    body = client.get("/score").text
    assert "We compose original music for commercials and brand campaigns" in body
    for half in ("cue sheet", "rights document", "deliverable"):
        assert half in body, half
    assert "one complete production workflow" in body
    # and it is still the page's one h1 — a statement, not a decorative line
    assert body.count("<h1") == 1


def test_the_wordmark_is_the_mark_not_the_word(client):
    """The brand sits top left as the real logo, on every layout.

    It is served from our own origin like everything else on this page, and it
    carries its own name for anyone who cannot see it.
    """
    body = client.get("/score").text
    assert "/static/public/wordmark-dark.png" in body
    bar = body.split('<header class="bar">')[1].split("</header>")[0]
    assert "wordmark-dark.png" in bar, "the wordmark is not in the top bar"
    assert 'alt="Chordential"' in bar
    assert os.path.getsize(os.path.join(_STATIC, "wordmark-dark.png")) > 0


def test_the_delivery_beat_lists_engine_derived_rows(client):
    """The beat must not describe a package build_manifest would not assemble."""
    import html as _html
    from chordential_oia.web import landing
    # unescaped: Jinja turns "Cue sheet & rights certificate" into "&amp;"
    body = _html.unescape(client.get("/score").text)
    lines = landing.sample_package_lines()
    assert lines, "the package list is empty"
    for line in lines:
        assert line["asset"] in body, f"{line['asset']!r} is not on the page"
        assert line["spec"] in body


def test_the_version_summary_is_derived_not_typed(client):
    """The count and the current label come from the same rows the package page
    renders — a hand-typed '3 versions' is a number that can go stale silently."""
    from chordential_oia.web import landing
    summary = landing.sample_package_lines()[-1]["spec"]
    assert str(len(landing.VERSIONS)) in summary
    assert (landing.VERSIONS[-1]["label"]) in summary


def test_the_delivery_beat_hands_off_to_the_package(client):
    """The scroll is the doorway; the document lives at its own address because it
    is the thing a producer forwards."""
    assert "/delivery-sample" in client.get("/score").text


# --------------------------------------------------------------------------- #
# The review beat: the mechanism, not a paragraph about the mechanism
# --------------------------------------------------------------------------- #

def test_the_review_beat_is_interactive_not_a_screenshot(client):
    """The claim is about a mechanism, and a mechanism is demonstrated by working."""
    body = client.get("/score").text
    for hook in ("revRail", "revMark", "revForm", "revList", "score-note.js"):
        assert hook in body, f"{hook} is missing — the beat is inert"


def test_the_versions_come_from_the_ladder_not_the_template(client):
    """A hand-typed version label on a pin is the same trap as a hand-typed version
    count: the pin is the one place on this page the version must be exactly right."""
    from chordential_oia.web import landing
    body = client.get("/score").text
    for v in landing.review_versions():
        assert f'data-v="{v["label"]}"' in body, f"{v['label']} is not offered"


def test_the_demo_says_nothing_is_sent(client):
    """A public text box that mimes a submit is the thing we do not build. The
    disclosure sits inside the component's own frame so it survives a screenshot
    cropped to the interaction — a footnote does not travel with a Slack paste."""
    body = client.get("/score").text
    frame = body.split('class="rev"')[1].split("</div>")[0] + body.split('id="rev"')[1][:4000]
    assert "Nothing here is sent" in frame
    assert "nothing leaves this browser" in frame


def test_the_review_demo_stores_nothing_on_the_server(client):
    """Anonymous public traffic must never reach review_comments — that table is the
    approval record, carries `verified`, and is joined by person_id. No route, no
    form action, no identity fields."""
    js = open(os.path.join(_STATIC, "score-note.js")).read()
    assert "sessionStorage" in js
    assert "fetch(" not in js and "XMLHttpRequest" not in js
    for field in ('name="email"', 'name="name"', "action="):
        assert field not in client.get("/score").text.split('id="rev"')[1][:4000]


def test_the_review_demo_survives_no_webgl2():
    """score-gl.js returns early with no WebGL2. The claim this beat makes may not
    die with the scene, so the interaction lives in its own file and touches no
    renderer state."""
    js = open(os.path.join(_STATIC, "score-note.js")).read()
    for renderer_thing in ("webgl2", "getContext", "PSTATE", "requestAnimationFrame"):
        assert renderer_thing not in js, f"the review demo reaches into the renderer ({renderer_thing})"


def test_it_never_claims_the_note_is_bound_to_a_recording(client):
    """Nothing hashes the audio. The binding is to a VERSION in the ladder, and a
    version's file can be removed while its comments survive. Say version."""
    body = client.get("/score").text.lower()
    for overstated in ("exact recording", "tamper-proof", "immutable",
                       "locked to that recording"):
        assert overstated not in body, f"'{overstated}' overstates what the product does"


# --------------------------------------------------------------------------- #
# The listening beat
# --------------------------------------------------------------------------- #

def test_the_page_offers_four_distinct_recordings(client):
    """ADR-0040: the front door of a music company has to let you hear music, and
    this page becomes the front door. The tracks ride in a JSON payload the lit
    notes read from — there is no player until a note is pressed, because a page
    that wants to make noise reads as a page that will make noise unasked."""
    import json
    html = client.get("/score").text
    payload = html.split('id="scoretracks"', 1)[1].split(">", 1)[1].split("</script>")[0]
    tracks = json.loads(payload)
    assert len(tracks) >= 4, f"only {len(tracks)} tracks"
    urls = [t["url"] for t in tracks]
    assert len(set(urls)) == len(urls), "two notes point at the same recording"
    for u in urls:
        assert u.startswith("/static/public/"), f"{u} is not served by us"
        assert client.get(u).status_code == 200


def test_the_notes_are_the_affordance(client):
    """The music is reached by pressing a lit piece of the score, not by a row of
    controls stapled into the reading column."""
    html = client.get("/score").text
    for hook in ("livelayer", "score-listen.js", "plAudio"):
        assert hook in html, f"{hook} is missing"


def test_the_listen_script_runs_before_the_renderer(client):
    """The renderer reads __SCORE_TRACKS to know how many notes to light. Load it
    the other way round and the scene lights nothing."""
    html = client.get("/score").text
    assert html.index("score-listen.js") < html.index("score-gl.js")


def test_the_player_never_taps_the_audio_element():
    """ADR-0043, fourth amendment: createMediaElementSource CAPTURES the element,
    and its failure is inaudible — playing, paused=false, no MediaError, peak 0.
    Not on the page where audio is the pitch."""
    import re
    js = open(os.path.join(_STATIC, "score-listen.js")).read()
    # strip comments: the file EXPLAINS why it does not tap, and the explanation
    # must not be what trips the test
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert "createMediaElementSource" not in code
    assert "AudioContext" not in code


def test_there_is_a_way_in_without_webgl2():
    """No WebGL2 means no lit notes. The words are not a substitute for the work,
    so the tracks stay reachable as a plain list."""
    js = open(os.path.join(_STATIC, "score-listen.js")).read()
    assert "lt-fallback" in js, "the music is unreachable when the scene does not draw"


def test_the_excerpts_are_a_tenth_of_the_master(client):
    """The masters are 163-187s at 192kbps — up to 4.5 MB a press, and a media
    element buffers ahead at its own discretion. A landing page does not get to
    spend a producer's cellular data like that."""
    import json
    rows = json.load(open(os.path.join(_STATIC, "excerpts.json")))
    assert rows, "no excerpts were cut"
    for r in rows:
        out = os.path.join(_STATIC, r["out"])
        assert os.path.exists(out), f"{r['out']} is referenced but missing"
        assert os.path.getsize(out) < 1_500_000, f"{r['out']} is too heavy for a press"


def test_every_excerpt_still_matches_the_master_it_was_cut_from():
    """showcase.py says a track is 'a file swap at the path below'. When someone
    swaps one, the excerpt silently becomes a cut of music we no longer ship —
    nothing 404s, nothing throws, every other test stays green."""
    import hashlib
    import json
    rows = json.load(open(os.path.join(_STATIC, "excerpts.json")))
    for r in rows:
        master = os.path.join(_STATIC, r["src"])
        assert os.path.exists(master), f"{r['src']} is gone; its excerpt is orphaned"
        data = open(master, "rb").read()
        if data[:3] == b"ID3":
            size = ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                    | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
            data = data[10 + size:]
        assert hashlib.sha256(data).hexdigest() == r["src_sha256"], (
            f"{r['src']} changed but {r['out']} was not re-cut — "
            f"run scripts/build_demo_excerpts.py")


def test_the_excerpt_does_not_inherit_the_masters_length():
    """A Xing/Info header declares the frame count of the file it came from. Copied
    into a 45-second cut, every player reports the master's 3:06 — the control lies
    about what it is holding."""
    import json
    for r in json.load(open(os.path.join(_STATIC, "excerpts.json"))):
        head = open(os.path.join(_STATIC, r["out"]), "rb").read(4000)
        assert b"Xing" not in head and b"Info" not in head, (
            f"{r['out']} carries a VBR header from its master")


def test_the_notes_only_wake_after_the_cube_closes(client):
    """Lit from the hero they competed with the convergence the page is built
    around. The renderer holds them until the model is assembled."""
    import re
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    assert "liveOn" in js, "the lit notes are not gated on assembly"
    # the invariant, not a literal: ignition may not begin before the cube lands
    assemble = float(re.search(r"ASSEMBLE_AT\s*=\s*([0-9.]+)", js).group(1))
    ign = float(re.search(r"IGN_FROM\s*=\s*([0-9.]+)", js).group(1))
    span = float(re.search(r"IGN_SPAN\s*=\s*([0-9.]+)", js).group(1))
    stagger = float(re.search(r"IGN_STAGGER\s*=\s*([0-9.]+)", js).group(1))
    assert ign >= assemble - 0.01, (
        f"notes start lighting at {ign} but the cube only lands at {assemble}")
    # and the last one must finish before the visitor runs out of page: a note still
    # at 44% when you hit the bottom reads as unfinished, not as arriving
    last_done = ign + 3 * stagger + span
    assert last_done <= 0.99, f"the fourth note is not lit until {last_done}"
    # The world has a third act now — the cube folds into the delivery package.
    # The notes have to have arrived on a finished cube before it starts moving
    # again, or they ignite in the middle of a fold and read as debris.
    pack_from = float(re.search(r"PACK_FROM\s*=\s*([0-9.]+)", js).group(1))
    pack_to = float(re.search(r"PACK_TO\s*=\s*([0-9.]+)", js).group(1))
    assert last_done <= pack_from, (
        f"the notes are still lighting at {last_done} when the package starts "
        f"folding at {pack_from}")
    assert pack_from > assemble, "the package folds before the cube has closed"
    assert pack_to <= 0.99, (
        f"the package is not sealed until {pack_to} — the visitor runs out of "
        "page before the last thing the page says finishes happening")
    # and the lid shuts last, on a carton that has finished standing itself up
    seal_from = float(re.search(r"SEAL_FROM = ([0-9.]+)", js).group(1))
    seal_to = float(re.search(r"SEAL_TO = ([0-9.]+)", js).group(1))
    assert seal_from > pack_to, (
        f"the lid starts closing at {seal_from} but the carton is not finished "
        f"until {pack_to} — it would shut on a box still building itself")
    assert seal_to <= 0.995, f"the lid is never fully shut ({seal_to})"


def test_each_act_lands_on_the_beat_it_belongs_to(client):
    """The world's acts are pinned to the copy they illustrate.

    These windows were measured in a browser at 1440x900 and 390x844 — a beat
    occupies a different stretch of the scroll on a phone than on a desktop, so
    each act has to fit inside the NARROWER of the pair or it reads against the
    wrong words on one of them. Encoded here because a later nudge to any one
    constant is exactly how a picture drifts off its own sentence.
    """
    import re
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    num = lambda n: float(re.search(n + r" = ([0-9.]+)", js).group(1))
    review = (0.594, 0.705)      # beat 05, "creative review", both layouts
    handoff = (0.770, 0.856)     # beat 06, "one complete handoff", both layouts

    ign = num("IGN_FROM")
    last = ign + 3 * num("IGN_STAGGER") + num("IGN_SPAN")
    assert review[0] <= ign and last <= review[1], (
        f"the notes light over {ign:.3f}–{last:.3f}, outside the review beat "
        f"{review[0]}–{review[1]}")
    assert num("ASSEMBLE_AT") <= review[0], "the cube is still closing at beat 05"
    # The fold is squeezed from both ends: it cannot start while the notes are
    # still lighting on beat 05, and it has to be FINISHED before beat 06 is
    # read. That leaves it beginning as the handoff section rises into view —
    # earlier than the point where that beat becomes the lit one — because a
    # fold with no room to happen in reads as a snap.
    assert num("PACK_FROM") > last, (
        "the cube starts folding while the notes are still lighting on beat 05")
    assert num("PACK_FROM") <= handoff[0], (
        "the fold has not begun by the time the handoff beat is lit")
    assert num("SEAL_FROM") >= handoff[1], (
        "the lid shuts while the handoff beat is still reading — it should be "
        "an open, complete carton for the whole of that section")

    # …and it has to FINISH early in that beat, not at the end of it. The middle
    # of the fold is a transitional cloud, and the words beside it say
    # "everything arrives together" over a manifest of what is in the box. A
    # fold still running when the section is being read is the picture
    # contradicting the sentence for the whole time anyone looks at it.
    early = handoff[0] + (handoff[1] - handoff[0]) * 0.70
    assert num("PACK_TO") <= early, (
        f"the carton is not finished until {num('PACK_TO')}, most of the way "
        f"through the beat that describes it — it should be complete by {early:.3f}")


def test_the_manifest_waits_for_a_package_to_describe(client):
    """The list of what is in the box appears once there is a box.

    It is written from the engine's real manifest, and it is a claim about a
    finished package — so it reveals against the SAME assembly scalar the model
    moves on (ADR-0029: one derivation, many reporters), late enough that the
    thing it describes exists.
    """
    import re
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    m = re.search(r"mk > ([0-9.]+) && beats\[b3\]\.classList\.contains", js)
    assert m, "the manifest is no longer gated on the assembly scalar"
    assert float(m.group(1)) >= 0.5, (
        f"the manifest writes in at {m.group(1)} of the fold, while the package "
        "is still a cloud of parts")
    html = client.get("/score").text
    assert "pack-note" in html, (
        "'One delivery. Nothing missing.' is a claim about the list above it; "
        "it must not appear before that list does")


def test_the_lit_notes_sit_above_the_copy_column(client):
    """#livelayer and #scroll at the same z-index means the copy column wins on DOM
    order and silently eats every click on a lit note."""
    html = client.get("/score").text
    assert "#livelayer{position:fixed;inset:0;z-index:4" in html


def test_the_review_rail_scrubs_a_real_take(client):
    """The rail drives an audio element; scrubbing seeks it and playback moves the
    head. currentTime is the authority for anything that binds to the music."""
    html = client.get("/score").text
    assert 'id="revAudio"' in html and 'id="revPlay"' in html
    js = open(os.path.join(_STATIC, "score-note.js")).read()
    assert "audio.currentTime = pos" in js, "the rail does not seek the take"
    assert "timeupdate" in js, "playback does not move the head"


def test_no_audio_bytes_move_before_a_press(client):
    """Nothing preloads. A visitor who presses nothing pays for no audio at all."""
    import re
    for tag in re.findall(r"<audio[^>]*>", client.get("/score").text):
        assert 'preload="none"' in tag, "an element preloads before anyone asked"
