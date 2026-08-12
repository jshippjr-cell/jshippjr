"""Cut the landing-page excerpts from the demo masters — no encoder required.

The masters are 163–187 seconds at 192 kbps, so a single press on a landing page
costs up to 4.5 MB, and a media element buffers ahead at its own discretion: a
visitor on cellular who listens for eight seconds and scrolls on can still pay for
the whole file. That is the number that makes this decision.

There is no ffmpeg here and none is needed. An MP3 is a sequence of self-contained
frames, each carrying its own header, so an excerpt is a byte range on frame
boundaries — no decode, no re-encode, no quality loss, and the output is
deterministic, which is what lets a test compare it against its source.

The one honest caveat: MPEG-1 Layer III has a bit reservoir, so the first frame or
two after a cut can reference data that is no longer there. At 26 ms per frame that
is inaudible on a bed, and it is the price of not re-encoding. Cuts start at 0:00,
where the reservoir is empty anyway and where the take actually begins — an offset
would be a small dishonesty about the work.

Run from the repo root:  python scripts/build_demo_excerpts.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "..", "src", "chordential_oia", "web", "static", "public")
STATIC = os.path.normpath(STATIC)

SECONDS = 45          # keep in step with landing.SAMPLE_TAKE_SECONDS
_BITRATES = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0]
_RATES = [44100, 48000, 32000]


def _strip_id3(data: bytes) -> bytes:
    """Drop a leading ID3v2 tag so offsets are into audio, not metadata."""
    if data[:3] != b"ID3":
        return data
    size = ((data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14
            | (data[8] & 0x7F) << 7 | (data[9] & 0x7F))
    return data[10 + size:]


def _frame(data: bytes, i: int):
    """(length, duration) of the MPEG-1 Layer III frame at i, or None."""
    if i + 4 > len(data) or data[i] != 0xFF or (data[i + 1] & 0xE0) != 0xE0:
        return None
    if (data[i + 1] >> 3) & 0x03 != 0x03:      # MPEG-1 only
        return None
    if (data[i + 1] >> 1) & 0x03 != 0x01:      # Layer III only
        return None
    bitrate = _BITRATES[(data[i + 2] >> 4) & 0x0F]
    rate_i = (data[i + 2] >> 2) & 0x03
    if not bitrate or rate_i == 0x03:
        return None
    rate = _RATES[rate_i]
    pad = (data[i + 2] >> 1) & 0x01
    return (144 * bitrate * 1000 // rate) + pad, 1152.0 / rate


def cut(src: str, seconds: int = SECONDS) -> bytes:
    """The first `seconds` of `src`, on frame boundaries, with no ID3 at all."""
    audio = _strip_id3(open(src, "rb").read())
    i, kept, elapsed = 0, [], 0.0
    # find the first sync
    while i < len(audio) and _frame(audio, i) is None:
        i += 1
    # An MP3's first frame may be a Xing/Info header: no audio, but it declares the
    # TOTAL frame count of the file it came from. Copy it into a 45-second cut and
    # every player reports the master's 3:06 over a 45-second excerpt — the control
    # lies about what it is holding. Drop it; for CBR the browser derives duration
    # from the file size, which is exact.
    first = _frame(audio, i)
    if first and b"Xing" in audio[i:i + first[0]][:64] or (
            first and b"Info" in audio[i:i + first[0]][:64]):
        i += first[0]

    while i < len(audio) and elapsed < seconds:
        f = _frame(audio, i)
        if f is None:
            break
        length, dur = f
        kept.append(audio[i:i + length])
        elapsed += dur
        i += length
    if elapsed < seconds * 0.5:
        raise SystemExit(f"{os.path.basename(src)}: only parsed {elapsed:.1f}s — "
                         f"not a CBR MPEG-1 Layer III file?")
    return b"".join(kept), elapsed


def main() -> int:
    from chordential_oia.web.showcase import get_showcase
    rows = []
    for demo in get_showcase().demos:
        url = (demo.audio_url or "").strip()
        if not url:
            continue
        name = os.path.basename(url)
        src = os.path.join(STATIC, name)
        if not os.path.exists(src):
            print(f"  ! missing {name}")
            continue
        data, elapsed = cut(src)
        out_name = "ex-" + name
        open(os.path.join(STATIC, out_name), "wb").write(data)
        rows.append({
            "src": name,
            "src_sha256": hashlib.sha256(_strip_id3(open(src, "rb").read())).hexdigest(),
            "out": out_name,
            "seconds": round(elapsed, 2),
            "bytes": len(data),
        })
        print(f"  {name} -> {out_name}  {elapsed:.1f}s  {len(data)/1048576:.2f} MB")

    # the sidecar exists so a test can catch the rot: a master can be swapped with
    # a one-file commit, and an excerpt cut from a track we no longer ship 404s
    # nothing and throws nothing — it just quietly plays the wrong music
    with open(os.path.join(STATIC, "excerpts.json"), "w") as fh:
        json.dump(rows, fh, indent=2, sort_keys=True)
    print(f"wrote excerpts.json ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "src")))
    raise SystemExit(main())
