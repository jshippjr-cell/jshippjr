"""The keyboard belongs to the picture, and a range is a thing you can see.

Three reports from inside the room, on the same day (operator, 2026-08-19):

  *"when an item is clicked on (for example a note, or the range button or anything
  similar) the space bar activate the thing. space bar should only start and stop the
  playback not activate other buttons or notes."*

  *"if i press N for the notes window to pop up, only clicking out or pressing N again
  should close it not escape, same thing with V and B."*

  *"User clicks range, the playback starts to highlight, user ends range, highlighted
  part stays highlighted, user inputs comment, user clicks add note to range. user
  should also be able to highlight a range as the scrub with their mouse."*

All three are the same species of defect: a control that answers to the wrong gesture.
The space bar deferred to whatever had focus, so the last thing you *clicked* kept
firing. Escape closed the sheets, so three unrelated gestures all dismissed a layer and
none of them was the one that opened it. And a range had no state in which it was
DECIDED — the band chased the playhead forever, which meant you could never stop, look
at what you had marked, and write about it.

These are behaviours of a keymap and a pointer, so what a test can hold is the source of
the room: which key reaches the transport, which key does not reach the sheets, and that
the range has an end mark that stays put.
"""
import pathlib
import re

import pytest

ROOM = (pathlib.Path(__file__).resolve().parent.parent / "src" / "chordential_oia"
        / "web" / "templates" / "creator_portal.html")


@pytest.fixture(scope="module")
def room() -> str:
    return ROOM.read_text(encoding="utf-8")


def _code(block: str) -> str:
    """The block with its comments stripped — a rule about what the code reads must not
    be satisfied, or broken, by prose describing the bug."""
    out = []
    for ln in block.splitlines():
        s = ln.lstrip()
        if s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        out.append(ln)
    return "\n".join(out)


def _keymap(room: str) -> str:
    """The room's global keydown handler."""
    start = room.index('addEventListener("keydown", function(e){\n'
                       "    if (e.metaKey")
    return _code(room[start:room.index("});", room.index("toggleSheet(\"takes\")", start))])


def _notebar(room: str) -> str:
    start = room.index('var bar = root.querySelector(".sr-notebar")')
    return _code(room[start:room.index("rooms.push({", start)])


# ── the space bar is the transport ──────────────────────────────────────────────────
def test_space_reaches_the_transport_before_anything_else(room):
    km = _keymap(room)
    space = km.index('e.code === "Space"')
    assert "r.toggle()" in km[space:space + 400], (
        "Space no longer reaches the transport")
    assert "return" in km[space:space + 400], (
        "Space must end the handler — falling through lets a later branch fire too")


def test_space_is_never_handed_to_whatever_has_focus(room):
    """The exact defect: an early return that let a focused button keep the key.
    A focused note or the Range button then swallowed every press."""
    km = _keymap(room)
    guard = re.search(
        r'closest\("button, a, summary, \[contenteditable\]"\)[^;]*', km)
    assert guard, "the focus guard is gone entirely — check this test still describes the room"
    assert "Space" not in guard.group(0), (
        "the focused-element guard covers Space again; the last thing clicked will "
        "swallow the transport key")
    # …and the guard must sit BELOW the Space branch, or it returns before Space is read.
    assert km.index('e.code === "Space"') < km.index(guard.group(0)), (
        "the focus guard runs before Space is handled, which is the bug itself")


def test_space_lets_go_of_the_control_that_had_focus(room):
    """preventDefault stops the synthetic click; blurring stops the NEXT press from
    needing to be prevented at all."""
    km = _keymap(room)
    space = km.index('e.code === "Space"')
    assert ".blur()" in km[space:space + 400], (
        "the focused control keeps focus after Space, so it stays armed")


# ── escape does not close a sheet ───────────────────────────────────────────────────
def test_escape_does_not_close_the_sheets(room):
    km = _keymap(room)
    esc = km.index('e.key === "Escape"')
    branch = km[esc:esc + 200]
    assert "closeAllSheets" not in branch, (
        "Escape closes the sheets again — B/N/V are toggles, and only the same key or "
        "a click outside may dismiss them")
    assert "cancelPendingDrop" in branch, "Escape must still cancel a pending drop"


def test_bnv_are_toggles(room):
    km = _keymap(room)
    for key, sheet in (("b", "brief"), ("n", "notes"), ("v", "takes")):
        assert f'r.toggleSheet("{sheet}")' in km, (
            f"{key.upper()} still only opens {sheet}; pressing it again must close it")


def test_the_toggle_actually_closes_an_open_sheet(room):
    body = _code(room[room.index("function toggleSheet(name)"):][:400])
    assert 'classList.contains("on")' in body and "closeAllSheets()" in body, (
        "toggleSheet does not close a sheet that is already open")


def test_clicking_outside_closes_a_sheet_even_with_no_veil(room):
    """A sheet opened during playback deliberately has no veil (it sits beside the
    picture). Without a document-level handler, clicking out did nothing — and Escape,
    the only other way out, is now correctly inert."""
    assert re.search(r'document\.addEventListener\("click",.{0,200}?\.sr-sheet\.on',
                     room, re.S), "no outside-click dismissal for an open sheet"


# ── a range you can see, and hold ───────────────────────────────────────────────────
def test_a_range_has_an_end_that_stays(room):
    nb = _notebar(room)
    assert re.search(r"var from = null, to = null", nb), (
        "the range still has only a start; there is no state in which it is decided")
    assert "function closeRange(" in nb, "no way to CLOSE a range and leave it there"


def test_the_band_stops_following_the_playhead_once_the_range_is_closed(room):
    nb = _notebar(room)
    assert re.search(r"function edge\(\)\{\s*return \(to === null\) \? \(mTime\(\)", nb), (
        "the range's end is not derived from one place; the label, the hidden fields "
        "and the highlight can drift apart")
    # paintBand must use edge(), not the raw clock — that is what makes it stay put.
    band = nb[nb.index("function paintBand()"):]
    band = band[:band.index("function clearRange")]
    assert "edge()" in band and "mTime()" not in band, (
        "the highlight still chases the playhead after the range is closed")


def test_the_send_button_says_what_it_will_do(room):
    nb = _notebar(room)
    assert "Add note to range" in nb, (
        "the button never becomes 'Add note to range', so a held range looks the same "
        "as a point note")


def test_a_range_is_drawn_across_the_waveform(room):
    """Not the Notes lane. You find a passage by LOOKING at the music, and the Notes
    lane is full of pins and spans that own their own clicks (operator, 2026-08-19)."""
    nb = _notebar(room)
    assert 'musicLane.addEventListener("mousedown"' in nb, (
        "no drag-to-mark on the waveform")
    assert 'noteLane.addEventListener("mousedown"' not in nb, (
        "the drag is back on the Notes lane, where it competes with every pin on it")
    assert 'document.addEventListener("mousemove"' in nb and \
           'document.addEventListener("mouseup"' in nb, (
        "the drag must be tracked on the document — a fast drag leaves the lane")
    assert "xToTime(" in nb, "the drag does not convert pointer position to time"


def test_drawing_a_range_does_not_also_seek(room):
    """The spine seeks on click, and a drag ends in one. Marking a passage must not
    throw the playhead to the end of it."""
    nb = _notebar(room)
    assert "suppressSeek" in nb, "the drag never suppresses the spine's seek"
    spine = room[room.index('spine.addEventListener("click"'):]
    spine = _code(spine[:spine.index("});")])
    assert "suppressSeek" in spine, (
        "the spine's click handler does not honour the suppression, so every range "
        "drag jumps the playhead")


def test_a_notes_range_bar_never_moves_the_playhead(room):
    """`.note-span` was `pointer-events:none`, so a click on it fell through to the
    spine and seeked: reaching for the stretch a note covers threw the picture to
    wherever the cursor happened to land inside it."""
    css = room[room.index(".note-span{"):]
    css = css[:css.index("}")]
    assert "pointer-events:none" not in css, (
        "the range bar is transparent to clicks again, so the spine seeks underneath it")
    span = room[room.index('span.className = "note-span"'):]
    span = span[:span.index("noteLane.appendChild(span)")]
    assert "e.stopPropagation()" in span, (
        "the range bar lets its click reach the spine's seek-on-click")
    assert "seek(" not in span, (
        "clicking a note's range moves the playhead — only its pin may do that")
    assert 'openSheet("notes")' in span, (
        "the range bar no longer opens the note it belongs to")


def test_only_the_pin_moves_the_playhead(room):
    """The other half of the pair: the note's own button still seeks to its start."""
    pin = room[room.index('pin.addEventListener("click"'):]
    pin = pin[:pin.index("noteLane.appendChild(pin)")]
    assert "seek(n.t)" in pin, "the note's pin no longer takes you to the note"


def test_a_tap_is_not_a_range(room):
    nb = _notebar(room)
    assert "MIN_RANGE" in nb, (
        "a stray click with no movement becomes a zero-length range")
