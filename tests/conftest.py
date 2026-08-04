"""Shared test config.

Tests assert against the demo dataset, so enable demo seeding for the whole test
session. Production leaves CHORDENTIAL_SEED_DEMO unset → a clean slate.
"""
import os

os.environ.setdefault("CHORDENTIAL_SEED_DEMO", "1")


def registered_routes(app):
    """Every (path, methods) the app will actually serve, INCLUDING routes that came
    in through `include_router`.

    Walking `app.routes` alone is not enough and silently under-reports. This FastAPI
    version wraps an included router in an `_IncludedRouter` object that has no `.path`
    — so as ADR-0044 moved route groups into `*_routes.py` modules, any test looping
    over `app.routes` quietly stopped seeing them. Two admin-gate drift guards and the
    duplicate-webhook guard were written against `app.routes`; without this they go
    blind exactly when a group moves, which is exactly when a gate exemption is most
    likely to drift.
    """
    out = []
    stack = list(app.routes)
    while stack:
        r = stack.pop()
        inner = getattr(r, "original_router", None)
        if inner is not None:
            stack.extend(inner.routes)
            continue
        path = getattr(r, "path", None)
        if path is not None:
            out.append((path, getattr(r, "methods", set()) or set()))
    return out
