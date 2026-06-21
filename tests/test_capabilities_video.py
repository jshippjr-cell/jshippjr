"""Import-safe checks for the Veo generation script.

The script lazily imports google-genai inside main(), so its prompt data and
selector are testable without the SDK (or any network/API key).
"""
import importlib.util
import os

_SPEC = importlib.util.spec_from_file_location(
    "gen_capabilities_film",
    os.path.join(os.path.dirname(__file__), "..", "scripts", "gen_capabilities_film.py"),
)
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


def test_eleven_film_shots_and_four_loop_plates():
    assert len(gen.SHOTS) == 11
    assert len(gen.LOOP_SHOTS) == 4
    # Shot ids are unique across both sets.
    ids = [s[0] for s in gen.SHOTS + gen.LOOP_SHOTS]
    assert len(ids) == len(set(ids))


def test_build_prompt_prepends_brand_style():
    sid, slug, prompt = gen.SHOTS[0]
    full = gen.build_prompt(prompt)
    assert full.startswith(gen.STYLE_PREFIX)
    assert prompt in full
    # Brand hexes carried into the style so every clip grades consistently.
    assert "#E4671F" in full and "#44161E" in full


def test_negative_prompt_blocks_baked_in_text():
    # Typography is added in post — plates must not bake in text/logos.
    for token in ("on-screen text", "captions", "logos", "watermark"):
        assert token in gen.NEGATIVE


def test_selector_resolves_groups_and_lists():
    assert gen.select("all") == gen.SHOTS
    assert gen.select("loop") == gen.LOOP_SHOTS
    assert gen.select("everything") == gen.SHOTS + gen.LOOP_SHOTS
    # Comma list by numeric id (zero-padded or not).
    picked = gen.select("1,2,11")
    assert [s[0] for s in picked] == ["01", "02", "11"]
    # Loop plates selectable by slug-id.
    assert [s[0] for s in gen.select("loop-a")] == ["loop-a"]
