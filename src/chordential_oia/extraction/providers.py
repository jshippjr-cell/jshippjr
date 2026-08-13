"""The extraction engine's model-provider seam (ADR-0005 pattern, ADR-0023).

Null by default, real when configured — exactly like payments/ and mailer.py. With no
key (or the kill switch thrown) ``get_provider()`` returns the NullProvider and the
engine steps aside entirely: intake falls back to the existing single-prompt seam or the
deterministic heuristics, so the product keeps working offline and free. Providers are
best-effort with bounded retry and NEVER raise out — a model failure must never break a
capture (the transcript is permanent; extraction can always re-run).
"""
from __future__ import annotations

import os
import time
from typing import Optional


class NullProvider:
    """No model configured — the engine declines and intake's fallbacks run."""
    name = "null"
    available = False

    def complete(self, prompt: str, *, max_tokens: int = 4000) -> Optional[str]:
        return None


# A one-minute discovery call is ~200 words. Reading it with ten specialists on the
# flagship model, then two recall rounds looking for what they missed, is the same
# machinery a forty-page RFP needs — and it is why a one-minute call was estimated at
# $0.30-0.50. The crew size is what gives coverage, so it is kept; the MODEL and the
# recall rounds are what scale to the size of the thing being read.
SMALL_INPUT_CHARS = 2500          # ≈ 400 words: a short call, a note, an email
ECONOMY_MODEL = "claude-haiku-4-5-20251001"
FLAGSHIP_MODEL = "claude-sonnet-5"


def explicit_model() -> str:
    """A model the operator named. Always wins — this sizing is a default, not a policy."""
    return (os.environ.get("CHORDENTIAL_EXTRACTION_MODEL")
            or os.environ.get("CHORDENTIAL_INTAKE_MODEL") or "").strip()


def economy_model() -> str:
    return (os.environ.get("CHORDENTIAL_EXTRACTION_ECONOMY_MODEL") or "").strip() \
        or ECONOMY_MODEL


def model_for(total_chars: int) -> str:
    """The right model for the amount of text. Small input, small model."""
    named = explicit_model()
    if named:
        return named
    return economy_model() if total_chars < SMALL_INPUT_CHARS else FLAGSHIP_MODEL


class AnthropicProvider:
    """The real extraction model. Lazy import (the ``ai`` extra), bounded retry with
    backoff for transient failures, and a hard never-raise guarantee."""
    name = "anthropic"
    available = True

    def __init__(self, model: str = "", *, retries: int = 2, backoff_s: float = 1.5):
        self.model = model or explicit_model() or FLAGSHIP_MODEL
        self.retries = max(1, retries)
        self.backoff_s = backoff_s
        # The last failure reason, so a silent decline can still be DIAGNOSED (surfaced on
        # the run report → the Evidence page). Best-effort must not mean invisible.
        self.last_error = ""
        # Real token usage, accumulated across every call this run — the basis for the
        # honest cost estimate + the durable monthly spend cap.
        self.usage = {"in": 0, "out": 0, "calls": 0}

    def complete(self, prompt: str, *, max_tokens: int = 4000) -> Optional[str]:  # pragma: no cover - networked
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception as exc:  # noqa: BLE001 — extra not installed / bad env → decline
            self.last_error = f"{type(exc).__name__}: {str(exc)[:280]}"
            return None
        for attempt in range(self.retries):
            try:
                resp = client.messages.create(
                    model=self.model, max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}])
                u = getattr(resp, "usage", None)
                if u is not None:
                    self.usage["in"] += int(getattr(u, "input_tokens", 0) or 0)
                    self.usage["out"] += int(getattr(u, "output_tokens", 0) or 0)
                    self.usage["calls"] += 1
                self.last_error = ""
                return next((b.text for b in resp.content if b.type == "text"), "")
            except Exception as exc:  # noqa: BLE001 — transient or terminal → retry then decline
                self.last_error = f"{type(exc).__name__}: {str(exc)[:280]}"
                if attempt + 1 < self.retries:
                    time.sleep(self.backoff_s * (attempt + 1))
        return None


def is_enabled() -> bool:
    """The orchestrated engine runs when a key is present and neither the intake-LLM
    kill switch (CHORDENTIAL_INTAKE_LLM=0) nor the engine's own kill switch
    (CHORDENTIAL_EXTRACTION_ENGINE=0) is thrown."""
    if os.environ.get("CHORDENTIAL_EXTRACTION_ENGINE", "1").strip().lower() in (
            "0", "false", "off", "no"):
        return False
    if os.environ.get("CHORDENTIAL_INTAKE_LLM", "1").strip().lower() in (
            "0", "false", "off", "no", ""):
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def get_provider():
    """The env-selected provider: Anthropic when enabled, Null otherwise."""
    return AnthropicProvider() if is_enabled() else NullProvider()


# Per-million-token published rates (USD), keyed by a coarse model family. Used only for
# the ESTIMATE that drives the operator's spend meter + the cap — the real bill is
# Anthropic's; this errs slightly high so the cap is conservative.
_RATES = {
    "opus": (15.0, 75.0), "sonnet": (3.0, 15.0), "haiku": (0.80, 4.0),
}


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    """A conservative USD estimate for a run's token usage (input, output)."""
    m = (model or "").lower()
    rate_in, rate_out = _RATES["sonnet"]
    for fam, rates in _RATES.items():
        if fam in m:
            rate_in, rate_out = rates
            break
    return round((in_tokens / 1_000_000) * rate_in + (out_tokens / 1_000_000) * rate_out, 4)


def monthly_cap_usd() -> float:
    """The operator's hard monthly ceiling on AI spend (USD). Default $10 — a deliberate,
    low, safe default so the tool can never quietly run up a bill; 0 = no cap."""
    try:
        return max(0.0, float(os.environ.get("CHORDENTIAL_EXTRACTION_MONTHLY_CAP", "10")))
    except (TypeError, ValueError):
        return 10.0
