"""The front door of a music company plays music.

The homepage had a "Hear the score" button in the hero — two lines under the promise
*"written and recorded in house by people — never AI-generated audio"* — and it scrolled
to a player driven by a **WebAudio oscillator**. Four synth voices through lowpass
filters. There was no `<audio>` element and no recording anywhere on the page; the only
match for `.mp3` in 2,000-odd lines was `o.type = t.wave`.

So a visitor who clicked the one button offering to let them hear the product heard a
machine, on the page that had just promised them the opposite.

Meanwhile capability demonstrations existed with audio attached and honest
framing ("demonstrations of approach/craft, not client commissions"), and
`showcase.DEMOS_INTRO` already carried a `home_title` / `home_cta` written for a homepage
section that was never built.

ADR-0040 builds it, and makes the synth say what it is.
"""

import hashlib
import os
import re
from pathlib import Path

import pytest

from chordential_oia.web.showcase import get_showcase

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import app as app_mod  # noqa: E402
from chordential_oia.web import public as _public  # noqa: E402

_STATIC = os.path.join(os.path.dirname(os.path.abspath(_public.__file__)),
                       "static", "public")

HOME = (Path(app_mod.__file__).parent / "templates"
        / "public" / "commission.html").read_text(encoding="utf-8")


@pytest.fixture()
def client():
    with TestClient(app_mod.app) as c:
        yield c


def _home(client):
    """The Commission, which is what every assertion below was written against.

    ADR-0040 was ratified when the Commission WAS the front door. It has since
    moved to /commission and the score page took `/`. These guarantees are about
    the Commission's own markup — its #work section, its #take synth, its hero CTA
    — so they follow it to its address rather than being deleted. The front door's
    equivalent guarantees are asserted separately below, against the page that is
    actually there.
    """
    r = client.get("/commission")
    assert r.status_code == 200
    return r.text


def _front(client):
    r = client.get("/")
    assert r.status_code == 200
    return r.text


# --------------------------------------------------------------------------- #
# There is music
# --------------------------------------------------------------------------- #
def test_the_homepage_has_real_audio(client):
    html = _home(client)
    srcs = re.findall(r'<audio[^>]*src="([^"]+)"', html)
    assert srcs, "the front door of a music company still plays no music"


def test_every_track_actually_serves_audio(client):
    """A player pointing at a 404 is worse than no player."""
    for src in re.findall(r'<audio[^>]*src="([^"]+)"', _home(client)):
        r = client.get(src)
        assert r.status_code == 200, f"{src} does not serve"
        assert r.headers["content-type"].startswith("audio/"), src
        assert len(r.content) > 100_000, f"{src} is too small to be a track"


def test_the_tracks_are_served_by_us_not_a_third_party(client):
    """The front door should not need an external host to make a sound."""
    for src in re.findall(r'<audio[^>]*src="([^"]+)"', _home(client)):
        assert src.startswith("/"), f"{src} is off-site"


def test_they_are_different_recordings(client):
    """Two cards playing one file would be its own dishonesty. Compared on the audio
    payload with the ID3 tag stripped, so different tags on identical audio cannot
    pass as different tracks."""
    import hashlib

    def payload(b):
        if b[:3] == b"ID3":
            n = ((b[6] & 0x7F) << 21) | ((b[7] & 0x7F) << 14) | ((b[8] & 0x7F) << 7) | (b[9] & 0x7F)
            b = b[10 + n:]
        return hashlib.sha256(b).hexdigest()

    srcs = re.findall(r'<audio[^>]*src="([^"]+)"', _home(client))
    hashes = {payload(client.get(s).content) for s in srcs}
    assert len(hashes) == len(srcs), "two cards on the homepage play the same recording"


# --------------------------------------------------------------------------- #
# The hero no longer contradicts itself
# --------------------------------------------------------------------------- #
def test_the_hero_listen_cta_leads_to_recordings(client):
    html = _home(client)
    hero = html.split("<!-- 1b")[0]
    m = re.search(r'<a class="btn" href="(#[^"]+)">([^<]*)</a>', hero)
    assert m, "the hero lost its listen CTA"
    target, label = m.group(1), m.group(2)
    assert target == "#work", f"the listen CTA points at {target}, not the recordings"
    section = html.split('id="work"')[1].split("</section>")[0]
    assert "<audio" in section, "the CTA lands somewhere with no music"
    assert "score" not in label.lower(), (
        "the label still promises 'the score' — the synth is not the score")


def test_no_served_recording_is_machine_made(client):
    """The rule that outlived the placeholders.

    Until 2026-09-10 every recording on this site was AI-generated, said so in its
    own ID3 artist tag ("Generated by ACE Studio"), and was disclosed by a notice
    printed beside every player. The founder's own music replaced them, and the
    notice and the tests that asserted it came out together — as they were written
    to. What survives is the brief's refusal (§7): no machine-made music, anywhere,
    including as a demonstration. So this reads every served recording's own
    metadata and fails the build if one says it was generated — the tag is what a
    producer reads with a right-click, and a page that plays it is the page they
    screenshot.
    """
    from chordential_oia.web.showcase import get_showcase
    checked = 0
    for demo in get_showcase().demos:
        if not (demo.audio_url or "").strip():
            continue
        r = client.get(demo.audio_url)
        assert r.status_code == 200, f"{demo.audio_url} does not serve"
        head = r.content[:8000]
        i = head.find(b"TPE1")
        if i > 0:
            size = int.from_bytes(head[i + 4:i + 8], "big")
            artist = head[i + 10:i + 10 + size].replace(b"\x00", b"")
            assert b"Generated" not in artist and b"ACE" not in artist, (
                f"{demo.audio_url} says in its own tag that it is machine-made")
        checked += 1
    assert checked, "no recording to check — the front door plays no music"
    for path in ("/", "/commission", "/showreel"):
        assert "AI-generated placeholders" not in client.get(path).text, (
            f"{path} still prints the placeholder notice over real music")


def test_the_synth_says_it_is_a_demonstration(client):
    """It is a good demo of the note mechanism and a bad impression of our music. It
    may stay, as long as it does not pass for a recording."""
    section = _home(client).split('id="take"')[1].split("</section>")[0]
    assert "generated by your browser" in section, (
        "the synth player still reads as though it were a recording")
    assert 'href="#work"' in section, "no route from the demo to the actual work"


# --------------------------------------------------------------------------- #
# One source for the tracks
# --------------------------------------------------------------------------- #
def test_the_commission_renders_every_showcase_record(client):
    """Two pages describing the same track differently is the drift this session has
    been removing everywhere else. /samples was the second page; it is retired, so the
    guarantee is now that the Commission renders the showcase and hardcodes nothing."""
    demos = [d for d in get_showcase().demos if d.audio_url]
    assert demos, "no demo carries audio"
    home = _home(client)
    for d in demos:
        assert d.audio_url in home, f"{d.title} is missing from the Commission"


def test_the_homepage_does_not_hardcode_a_track():
    """The section renders from showcase; swapping a file must not need a template
    edit. A literal .mp3 in the template is how the two pages would drift."""
    assert ".mp3" not in HOME


def test_the_demos_are_framed_as_demonstrations(client):
    """Honesty rule: never imply real client work. These answer briefs we set
    ourselves, and the page has to say so where the play buttons are."""
    section = _home(client).split('id="work"')[1].split("</section>")[0]
    assert "demonstration" in section.lower()
    assert "not a client" in section.lower() or "not client" in section.lower()


def test_the_section_offers_the_way_deeper(client):
    """The way deeper is the front door's listening beat, where the lit notes play."""
    section = _home(client).split('id="work"')[1].split("</section>")[0]
    assert 'href="/#hear"' in section


def test_it_degrades_without_javascript():
    """The recordings use the native control on purpose — the section's job is to get
    music playing, not to be another mechanism that can fail."""
    work = HOME.split('id="work"')[1].split("</section>")[0]
    assert "controls" in work, "the players depend on custom JS to be operable"
    assert "<script" not in work


# --------------------------------------------------------------------------- #
# ADR-0040 at the NEW front door — same guarantees, expressed for the page that
# is actually there. The score page reaches its recordings by pressing a lit
# piece of the score rather than by a row of controls, so "N <audio> tags" is
# the wrong shape for the assertion; "distinct recordings this page can reach,
# served by us, one lit note each" is the same promise in the shape the page takes.
# --------------------------------------------------------------------------- #

def test_the_front_door_offers_real_recordings(client):
    import json
    html = _front(client)
    payload = html.split('id="scoretracks"', 1)[1].split(">", 1)[1].split("</script>")[0]
    tracks = json.loads(payload)
    assert tracks, "the front door of a music company offers no recordings"
    for t in tracks:
        r = client.get(t["url"])
        assert r.status_code == 200, f"{t['url']} 404s"
        assert r.headers["content-type"].startswith("audio/"), t["url"]
        assert len(r.content) > 100_000, f"{t['url']} is too small to be music"


def test_the_front_doors_tracks_are_served_by_us(client):
    import json
    html = _front(client)
    payload = html.split('id="scoretracks"', 1)[1].split(">", 1)[1].split("</script>")[0]
    for t in json.loads(payload):
        assert t["url"].startswith("/static/public/"), (
            f"{t['url']} is off-site; the front door must not depend on a third party")


def test_the_front_door_plays_different_recordings(client):
    """Compared on the audio payload with any ID3 stripped, so a retag cannot
    disguise a duplicate — a retagged copy of a wired demo once sat beside it and
    would otherwise have sneaked two notes onto one recording."""
    import json
    html = _front(client)
    payload = html.split('id="scoretracks"', 1)[1].split(">", 1)[1].split("</script>")[0]
    seen = {}
    for t in json.loads(payload):
        data = client.get(t["url"]).content
        if data[:3] == b"ID3":
            size = ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
                    | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
            data = data[10 + size:]
        h = hashlib.sha256(data).hexdigest()
        assert h not in seen, f"{t['url']} is the same recording as {seen[h]}"
        seen[h] = t["url"]


def test_the_front_door_does_not_hardcode_a_track():
    """Swapping a track must not need a template edit — that is how two surfaces
    come to tell different stories about the same recording."""
    tpl = os.path.join(os.path.dirname(_STATIC), "..", "templates", "public",
                       "score.html")
    assert ".mp3" not in open(os.path.normpath(tpl)).read()


def test_the_front_door_and_the_commission_render_the_same_records(client):
    """One source of truth for the demos (showcase.DEMOS) — the surfaces cannot
    describe the same track differently. /samples used to be the second surface;
    the Commission's work section is now the one that lists them beside the door."""
    import json
    html = _front(client)
    payload = html.split('id="scoretracks"', 1)[1].split(">", 1)[1].split("</script>")[0]
    commission = client.get("/commission").text
    for t in json.loads(payload):
        assert t["title"] in commission, f"{t['title']} is on / but not on /commission"


def test_the_commission_is_still_reachable(client):
    """It is the reference for what we are rebuilding, and links handed out before
    the cutover still point at it."""
    r = client.get("/commission")
    assert r.status_code == 200
    # 2026-09-10, brief §6: the H1 is "The music arrives finished." — the old
    # "music department" line was retired as a scale overclaim.
    assert "The music arrives" in r.text
