"""The delivery lifecycle lived in the route modules as bare strings.

Eighteen string literals across three files decided the state machine, so the rule
*"publishing a version moves the ball to the client"* was re-decided at each call site
and stated nowhere. That is not a tidiness complaint — it is how the engine's own
declared list drifted out of sync with reality:

    DELIVERY_STATES = ["In production", "In review", "Delivered", "Released"]

`"Approved"` was **missing**, while the routes wrote it and compared against it. Anything
iterating that list — a picker, a progress rail, a validator — would have silently
omitted the state a client's sign-off puts a campaign into. Found by listing every state
the code writes and diffing it against what the engine claims.

Two things changed. The non-obvious transitions are now named functions in
`delivery.py`, and **an invalid state cannot be written at all**. The tautological ones
(`release` → `"Released"`) stay inline on purpose: naming `state_on_released()` would be
ceremony, and the guard covers them anyway.
"""

import importlib

import pytest

from chordential_oia import delivery as engine
from chordential_oia.web import db as db_mod


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "s.db"))
    importlib.reload(db_mod)
    conn = db_mod.connect()
    db_mod.init_db(conn)
    conn.execute("INSERT INTO projects (client, need) VALUES ('Acme', 'Anthem')")
    conn.commit()
    pid = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()["id"]
    yield conn, pid
    conn.close()


# --------------------------------------------------------------------------- #
# The declared states and the real ones
# --------------------------------------------------------------------------- #
def test_every_state_the_code_writes_is_a_declared_state():
    """The defect that started this. `"Approved"` was written by the routes and absent
    from `DELIVERY_STATES`, so the declaration and the behaviour disagreed and nothing
    noticed."""
    import re
    from pathlib import Path
    import chordential_oia.web.app as app_mod
    web = Path(app_mod.__file__).parent
    written = set()
    for path in sorted(web.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        written |= set(re.findall(r'update_delivery\([^)]*"state",\s*"([^"]+)"', src))
    undeclared = sorted(written - set(engine.DELIVERY_STATES))
    assert undeclared == [], (
        f"these states are written but not declared: {undeclared}")


def test_approved_is_a_declared_state():
    """Pinned by name, because it is the one that was missing and the one a client's
    sign-off produces."""
    assert "Approved" in engine.DELIVERY_STATES


def test_the_states_are_in_lifecycle_order():
    """`DELIVERY_STATES[0]` is used as the default state, and anything rendering a
    progress rail reads the order as meaning."""
    assert engine.DELIVERY_STATES == [
        "In production", "In review", "Approved", "Delivered", "Released"]


# --------------------------------------------------------------------------- #
# An invalid state cannot be written
# --------------------------------------------------------------------------- #
def test_an_unknown_delivery_state_is_refused(project):
    """A typo produces a delivery no template branch matches and no engine
    recognises, and nothing anywhere would say so. Same enforcement that caught a real
    bug in `update_meeting` — silence on a bad value is how it survives."""
    conn, pid = project
    with pytest.raises(ValueError):
        db_mod.update_delivery(conn, pid, "state", "In Review")      # wrong case
    with pytest.raises(ValueError):
        db_mod.update_delivery(conn, pid, "state", "Shipped")        # not a state


def test_every_declared_state_can_be_written(project):
    """The control. A guard that rejected a legitimate state would break the product
    in exactly the place it claims to protect."""
    conn, pid = project
    for state in engine.DELIVERY_STATES:
        db_mod.update_delivery(conn, pid, "state", state)
        assert db_mod.get_delivery(conn, pid)["state"] == state


def test_clearing_the_state_is_still_allowed(project):
    """`None` removes the key and `""` sets it empty — both are existing conventions
    and neither is a state."""
    conn, pid = project
    db_mod.update_delivery(conn, pid, "state", "In review")
    db_mod.update_delivery(conn, pid, "state", None)
    assert "state" not in db_mod.get_delivery(conn, pid)


def test_other_keys_are_not_state_checked(project):
    """The guard is for `state` alone — `version_state` has its own vocabulary."""
    conn, pid = project
    db_mod.update_delivery(conn, pid, "version_state", "v2 Direction-lock")
    db_mod.update_delivery(conn, pid, "notes", "anything at all")


# --------------------------------------------------------------------------- #
# The transitions themselves
# --------------------------------------------------------------------------- #
def test_publishing_a_version_always_moves_the_ball_to_the_client():
    """Whatever the state was before. A fresh v1 out of production and a re-open after
    an approval are the same event: there is new work the client has not heard."""
    for before in engine.DELIVERY_STATES:
        assert engine.state_on_version_published({"state": before}) == "In review"


def test_a_client_approval_is_not_a_delivery():
    """Approving the master locks the creative; the package is assembled separately.
    Conflating them is how a sign-off would imply a shipment that has not happened."""
    assert engine.state_on_client_approved({}) == "Approved"
    assert engine.state_on_client_approved({}) != "Delivered"


def test_a_change_request_and_a_reopened_approval_are_different_events():
    """They land in DIFFERENT states, and I conflated them while writing this: a client
    asking for changes sends the work back to the studio ("In production"), while an
    operator reopening an approval asks the client to look again at work that already
    exists ("In review"). Naming them alike is how one gets "corrected" into the other
    by someone reading only the function name."""
    assert engine.state_on_changes_requested({}) == "In production"
    assert engine.state_on_approval_reopened({}) == "In review"
    assert engine.state_on_changes_requested({}) != engine.state_on_approval_reopened({})


def test_every_transition_returns_a_declared_state():
    """A transition function that returned an unknown state would now raise at the
    write, which is late. Catch it here instead."""
    for fn in (engine.state_on_version_published, engine.state_on_client_approved,
               engine.state_on_changes_requested, engine.state_on_approval_reopened):
        assert engine.is_delivery_state(fn({})), fn.__name__


# --------------------------------------------------------------------------- #
# The one transition with a refusal
# --------------------------------------------------------------------------- #
def test_release_is_refused_until_the_licence_is_confirmed():
    """IP3: releasing asserts the grant on the certificate. The reason is the
    operator's, not a log line's."""
    allowed, why = engine.can_release({})
    assert allowed is False
    assert "licence terms have not been confirmed" in why


def test_can_release_agrees_with_the_rule_it_delegates_to():
    """`can_release` calls `license_confirmation` rather than testing
    `license_confirmed` itself. Restating the rule would create a SECOND definition of
    "confirmed" that agreed with the first until the day it didn't — which is the exact
    defect this pass exists to remove. Checked against the awkward shapes."""
    for delivery in ({}, {"license_confirmed": None}, {"license_confirmed": {}},
                     {"license_confirmed": True},
                     {"license_confirmed": {"by": "Jon", "date": "2026-08-06"}}):
        expected = engine.license_confirmation(delivery) is not None
        assert engine.can_release(delivery)[0] is expected, delivery
