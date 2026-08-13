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
    assert "every part in the air" in r.text.lower()


def test_it_carries_the_copy_not_just_the_picture(client):
    """The words say everything the picture does — that is the no-WebGL2 promise."""
    body = client.get("/score").text
    for line in (
        "Every note",
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
    """The headline carries the character; the line under it carries the offer.

    The page used to open on "Every note finds its place." alone, which is true
    to it and silent on what is actually being sold. A visitor who reads only
    the first screen should come away knowing both halves: the music is
    composed, and everything around it is organised.
    """
    body = client.get("/score").text
    assert "Every note" in body and "finds its" in body
    assert "We compose original music for commercials and brand campaigns" in body
    for half in ("cue sheet", "rights document", "deliverable"):
        assert half in body, half
    assert "one complete production workflow" in body
    assert body.count("<h1") == 1, "the page has more than one first-level heading"


def test_a_shortened_manifest_says_that_it_is_shortened(client):
    """On a short phone the last rows are held back. That has to be admitted.

    Four rows plus a heading and a lede is all an iPhone SE can hold beside the
    package the list describes. Holding rows back is a layout decision; holding
    them back SILENTLY, under "everything arrives together" and above "one
    delivery, nothing missing", is the honesty rule broken. So the page names
    how many it is not showing and links to all of them — and the number is
    derived from the manifest, because a typed one goes stale the first time the
    engine's package changes.
    """
    from chordential_oia.web import landing
    body = client.get("/score").text
    rows = landing.sample_package_lines()
    if len(rows) <= 4:                     # nothing is ever held back
        assert "pack-rest" not in body
        return
    assert "pack-rest" in body, "no rows are marked as the ones held back"
    assert body.count('class="pack-rest"') == len(rows) - 4
    assert "and %d more" % (len(rows) - 4) in body, (
        "the page does not say how many rows it is not showing")
    more = body.split('class="pack-more"')[1].split("</p>")[0]
    assert "/delivery-sample" in more, "the rest of the package is not reachable"
    # every row still ships in the markup — this is a display cut, not a shorter
    # package, and the words beside it promise the whole one
    import html as _html
    plain = _html.unescape(body)
    for r in rows:
        assert r["asset"] in plain


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


def test_the_acts_are_measured_from_the_beats_not_written_down(client):
    """Where each act happens is derived from the beat it illustrates.

    These were constants once, hand-fitted to measured beat windows, and they
    were re-fitted three times: a beat covers a different stretch of scroll on a
    phone than on a desktop, and every change to the copy moves it again. The
    last one left the two layouts sharing a window of 0.039 for four notes to
    light in — not a number worth tuning, but a sign the number should not be
    written down at all.

    So this asserts the DERIVATION, which is the thing that must not regress.
    The fractions themselves are checked in a browser, on real viewports.
    """
    import re as _re
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    assert "function pinActs()" in js, "the acts are no longer measured"
    assert "\npinActs();" in js, "pinActs is never run at boot"
    assert 'addEventListener("resize", pinActs)' in js, (
        "the acts are measured once and never again — a rotated phone re-lays "
        "every beat out and would leave each act on the wrong words")

    body = js[js.index("function pinActs()"):]
    body = body[:body.index("\npinActs();")]
    # ignition and the closing cube belong to the review beat, the carton and its
    # lid to the handoff beat. Reading the wrong window is the whole bug this
    # replaced, and it is invisible until someone looks at a phone.
    for name, want in (("ASSEMBLE_AT", "rv"), ("IGN_FROM", "rv"),
                       ("IGN_STAGGER", "L5"), ("IGN_SPAN", "L5"),
                       ("PACK_FROM", "hd"), ("PACK_TO", "hd"),
                       ("SEAL_FROM", "hd"), ("SEAL_TO", "hd")):
        line = _re.search(name + r"\s*=\s*([^;\n]+)", body)
        assert line, name + " is no longer derived"
        assert want in line.group(1), (
            "%s is derived from %r, not from the beat it belongs to (%s)"
            % (name, line.group(1).strip(), want))


def test_the_acts_find_their_beats_by_what_is_in_them(client):
    """Inserting a section must not silently re-point an act at other words."""
    import re as _re
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    for var, marker in (("REVIEW_BEAT", "rev"), ("PACK_BEAT", "pack")):
        m = _re.search(var + r"\s*=\s*[^;]+?querySelector\(([^)]+)\)", js, _re.S)
        assert m, var + " is not located by content"
        assert marker in m.group(1), (
            "%s looks for %s, which is not the beat it means" % (var, m.group(1)))
        assert not _re.search(var + r"\s*=\s*\d", js), var + " is a hard-coded index"


def test_the_order_of_the_acts_survives_any_layout(client):
    """The acts overlap in ways that read as broken, so the order is enforced.

    Derived numbers come from whatever the page's layout turns out to be, and a
    tall enough section could hand back a window that puts the fold on top of
    notes still lighting. These clamps are what stop a copy edit from producing
    a picture that contradicts itself.
    """
    js = open(os.path.join(_STATIC, "score-gl.js")).read()
    body = js[js.index("function pinActs()"):]
    body = body[:body.index("\npinActs();")]
    assert "lastLit" in body, "nothing checks the notes have finished lighting"
    for guard in ("PACK_FROM <= lastLit", "PACK_TO <= PACK_FROM",
                  "SEAL_FROM <= PACK_TO", "SEAL_TO <= SEAL_FROM"):
        assert guard in body, "the ordering guard %r is gone" % guard


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
