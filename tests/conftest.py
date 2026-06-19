"""Shared test config.

Tests assert against the demo dataset, so enable demo seeding for the whole test
session. Production leaves CHORDENTIAL_SEED_DEMO unset → a clean slate.
"""
import os

os.environ.setdefault("CHORDENTIAL_SEED_DEMO", "1")
