"""The glow ran ahead of the playhead, and there was no way to go back to the top.

Reported live, from the composer's session room: *"The waveform animation glowing as the
playback head is scrolling is way off and distracting, make sure the animation keeps up
with the playback head."* And: *"make it to where pressing 'enter' starts the track over
and the playhead goes back to the beginning."*

Three causes, and the first two both had to go:

1. **Two clocks.** The playhead is placed from the MASTER clock — the client's cut, when
   there is one — while the waveform lit its bars from the take's own
   ``audio.currentTime``. The take is a follower, re-aligned only when drift passes
   0.12s, so the two agreed only while that window happened to be closed.
2. **The canvas was reallocated every frame.** ``drawWave`` assigned ``canvas.width`` on
   every call, which wipes and re-allocates the backing store. At 60fps that is the
   stutter that made the edge visibly lag the head.
3. **No transport key for the top.** Space toggled, arrows nudged; going back to the
   beginning meant reaching for the scrubber, in the one room where the same eight bars
   get looped against a hit dozens of times.

These are behaviours of a canvas and a keymap, so what a test can hold is the source of
the room itself: that the lit edge is derived from the same numbers as the head, that the
canvas is only resized when its size changed, and that Enter is bound to a real restart.
"""
import pathlib
import re

import pytest

ROOM = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
        / "web" / "templates" / "creator_portal.html")


@pytest.fixture(scope="module")
def room() -> str:
    return ROOM.read_text(encoding="utf-8")


def _draw_wave(room: str) -> str:
    start = room.index("function drawWave()")
    return room[start:room.index("function drawPoster()", start)]


def _code(block: str) -> str:
    """The block with its comments stripped — a rule about what the code reads must not
    be satisfied, or broken, by prose describing the bug."""
    return "\n".join(ln for ln in block.splitlines()
                     if not ln.lstrip().startswith("//"))


# ── one clock ───────────────────────────────────────────────────────────────────────
def test_the_lit_edge_is_derived_from_the_playheads_own_numbers(room):
    body = _code(_draw_wave(room))
    assert "headX" in body, "the lit boundary is not derived from the head's position"
    assert re.search(r"headX\s*=.*mTime\(\).*mDur\(\)", body, re.S), (
        "headX must come from the master clock — the same mTime()/mDur() that places "
        "the playhead")


def test_the_waveform_never_reads_the_takes_own_clock(room):
    """`audio.currentTime` is the FOLLOWER when there is picture. Reading it here is
    exactly the drift that was reported."""
    body = _code(_draw_wave(room))
    assert "audio.currentTime" not in body, (
        "drawWave is back on the take's own clock; the glow will drift from the head "
        "again by up to the 0.12s sync window")


def test_the_playhead_still_reads_the_master_clock(room):
    """The other half of the pair. If the HEAD moves to another clock the same bug
    returns from the opposite side."""
    update = room[room.index("function update()"):]
    update = update[:update.index("\n    }") + 6]
    assert "mTime()" in update and "mDur()" in update
    assert "playhead.style.left" in update


# ── and it can keep up ──────────────────────────────────────────────────────────────
def test_the_canvas_is_only_resized_when_its_size_changed(room):
    """Assigning canvas.width wipes and reallocates the backing store. Doing it inside
    a 60fps draw is what made the edge stutter behind the head."""
    body = _code(_draw_wave(room))
    assert re.search(r"if \(waveCv\.width !== w \|\| waveCv\.height !== h\)", body), (
        "the canvas is resized unconditionally every frame")
    # The assignment must live INSIDE that guard, not before it.
    guard = body.index("if (waveCv.width !== w")
    assert "waveCv.width =" not in body[:guard], (
        "the canvas is still being reallocated before the size check")


# ── back to the top ─────────────────────────────────────────────────────────────────
def test_enter_restarts_the_room(room):
    keys = room[room.index('addEventListener("keydown"'):]
    keys = keys[:keys.index("});")]
    assert re.search(r'e\.key === "Enter".*r\.restart\(\)', keys), (
        "Enter is not bound to a restart")


def test_restart_returns_to_zero_and_rolls(room):
    fn = room[room.index("function restart()"):]
    fn = fn[:fn.index("\n    }") + 6]
    assert "seek(0)" in fn, "restart must put the head back at the beginning"
    assert "play()" in fn, "it must start the track over, not merely rewind it"


def test_enter_still_belongs_to_a_focused_control(room):
    """A button under focus keeps its native Enter — the transport must not steal it."""
    keys = room[room.index('addEventListener("keydown"'):]
    keys = keys[:keys.index("});")]
    guard = keys.index('e.key === "Enter"')
    assert "closest" in keys[:guard], (
        "the interactive-element guard must come before the transport keys")
    assert 'return;' in keys[:guard]


def test_the_nudge_keys_share_the_master_clock_too(room):
    keys = room[room.index('addEventListener("keydown"'):]
    keys = keys[:keys.index("});")]
    arrows = [ln for ln in keys.splitlines() if "Arrow" in ln]
    assert arrows, "the nudge keys vanished"
    for ln in arrows:
        assert "r.audio.currentTime" not in ln, (
            "a nudge read the follower clock, walking the picture further out of true "
            "on every press")
        assert "r.time()" in ln


def test_the_room_publishes_what_the_keymap_calls(room):
    """The keymap talks to rooms through their published surface; a missing name is a
    silent no-op on a keypress."""
    reg = room[room.index("rooms.push({"):]
    reg = reg[:reg.index("});") + 3]
    for name in ("restart:", "time:", "toggle:", "seek:", "openSheet:"):
        assert name in reg, f"the room does not publish {name}"


def test_the_grammar_on_screen_names_the_key(room):
    """The room states its own keys; a transport key nobody is told about is one nobody
    presses."""
    assert "↵" in room and "t-keys" in room
