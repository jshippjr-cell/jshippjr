"""Two questions the operator asked, answered in code.

  1. "Is spending money the only way to get the transcript organised?"  No — and the free
     path was far worse than it needed to be. A real discovery call stated a deadline, a
     budget band and a cutdown length in plain English, and the deterministic baseline
     took none of them: the timeline pattern demanded "in 24 days" when the speaker said
     "in the next 24 days", and the deliverables list held ":60" and "cutdown" when the
     speaker said "60 second cut down". Those are free to catch.

  2. "There's no way 10 agents checked this."  Right — and even when they can, ten
     specialists on the flagship model plus two recall rounds is what a forty-page RFP
     needs, not a one-minute call. That is why a 200-word transcript was estimated at
     $0.30-0.50. Crew size is what gives coverage, so it stays; the model and the recall
     rounds scale to the size of the thing being read.
"""
import pytest

# The words actually spoken on the call of 2026-08-13, verbatim from the evidence page.
REAL_CALL = (
    "Hello. Okay, so this is going to be a test to see if the notetaker is able to compile "
    "our objective here. And the objective is to launch delivery product wrapped around a "
    "title sequence in the next 24 days. We have a budget of roughly $10,000. We might be "
    "able to push that to $12,000. But right now we're looking at 10. The timeline. We want "
    "weekly deliverables. We want to check in weekly. The deliverables need to be a 60 second "
    "cut down in a way format. We need all the stems to be available and everything of that "
    "nature. So if you could help us out with that, we, we would appreciate it. Okay, thank you."
)


def _facts(text):
    from chordential_oia.web.campaign_intake import _extract_objective
    return {c["key"]: c["value"] for c in _extract_objective(text)}


def test_the_deadline_is_caught_the_way_people_say_it():
    """"in the next 24 days" — stated plainly, and the Timeline field sat empty."""
    assert "24 days" in _facts(REAL_CALL).get("deadline", "")


@pytest.mark.parametrize("said", [
    "we need it in the next 24 days", "we need it within 3 weeks",
    "delivery in the coming 2 months", "it's 10 days from now",
    "by the end of next month", "in 24 days",
])
def test_the_deadline_survives_how_it_is_phrased(said):
    assert _facts("The objective is a title sequence. " + said).get("deadline")


def test_the_budget_band_is_the_band_not_the_floor():
    """Reading only the first figure states a ceiling the buyer never set."""
    assert _facts(REAL_CALL).get("budget_band") == "$10,000 to $12,000"


def test_a_single_figure_is_still_a_single_figure():
    assert _facts("The budget is $18,000.").get("budget_band") == "$18,000"


def test_a_spoken_length_counts_as_a_deliverable():
    """"a 60 second cut down" — two words where the pattern wanted one, and a length
    written the way nobody says it out loud."""
    d = _facts(REAL_CALL).get("deliverables", "")
    assert ":60" in d, d
    assert "cutdown" in d, d
    assert "stems" in d, d


def test_the_free_read_is_now_worth_having():
    """Before: 2 facts, one of them wrong-ish. This is the whole point of the change."""
    got = _facts(REAL_CALL)
    assert len(got) >= 3
    assert got.get("deadline") and got.get("budget_band") and got.get("deliverables")


def test_it_still_invents_nothing():
    """A stronger baseline must not become a guessing baseline (the honesty rule)."""
    got = _facts("Hi, just checking in about the thing we discussed. Speak soon.")
    assert got == {}, got


# ── the paid path, sized to the work ─────────────────────────────────────────
def test_a_short_call_uses_the_small_model(monkeypatch):
    from chordential_oia.extraction import providers
    monkeypatch.delenv("CHORDENTIAL_EXTRACTION_MODEL", raising=False)
    monkeypatch.delenv("CHORDENTIAL_INTAKE_MODEL", raising=False)
    assert providers.model_for(len(REAL_CALL)) == providers.ECONOMY_MODEL


def test_a_long_document_still_gets_the_flagship(monkeypatch):
    from chordential_oia.extraction import providers
    monkeypatch.delenv("CHORDENTIAL_EXTRACTION_MODEL", raising=False)
    monkeypatch.delenv("CHORDENTIAL_INTAKE_MODEL", raising=False)
    assert providers.model_for(90_000) == providers.FLAGSHIP_MODEL


def test_a_named_model_always_wins(monkeypatch):
    """The sizing is a sensible default, not a policy that overrides the operator."""
    from chordential_oia.extraction import providers
    monkeypatch.setenv("CHORDENTIAL_EXTRACTION_MODEL", "claude-opus-5")
    assert providers.model_for(10) == "claude-opus-5"
    assert providers.model_for(90_000) == "claude-opus-5"


def test_every_specialist_still_reads_a_short_call():
    """Coverage is what the crew is FOR. Cost comes off the model, never the crew —
    dropping specialists would silently stop looking for whole categories of fact."""
    from chordential_oia.extraction.workers import WORKERS
    assert len(WORKERS) >= 10
