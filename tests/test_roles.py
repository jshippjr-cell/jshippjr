"""What each account may do.

`user_account.role` existed and nothing read it. With one account that is harmless;
with two it is the whole problem — a hire could release a delivery, confirm a licence
or delete an opportunity, and the only thing in the way was that they had not thought
to try.

Three roles, because a business this size has three kinds of person: **owner** (the
founder — everything, including what costs money or asserts a licence), **operator** (a
hire who runs campaigns), **viewer** (read-only).

The two invariants matter more than the rules:

1. **The shared passphrase keeps full access.** It is the break-glass (ADR-0054), and a
   break-glass that lands you in a permission error is not one. Restricting it would
   also be theatre — anyone holding it can change the environment variable.
2. **With no accounts, nothing changes at all.** A single-operator instance that never
   made an account must behave exactly as it did before roles existed.

Enforced in the gate rather than at forty routes, for the reason the decision log is:
a rule applied at forty places is a rule missing from the forty-first.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import accounts, roles  # noqa: E402
from chordential_oia.web import db as db_mod  # noqa: E402

PASSPHRASE = "the-shared-passphrase"
PASSWORD = "a-real-password-123"


@pytest.fixture()
def app_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "r.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_ADMIN_TOKEN", PASSPHRASE)
    monkeypatch.setenv("CHORDENTIAL_SEED_DEMO", "1")
    monkeypatch.delenv("CHORDENTIAL_FIRST_USER", raising=False)
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    return mod


def _signed_in(app_mod, role):
    conn = db_mod.connect()
    email = f"{role}@chordential.com"
    accounts.create_account(conn, email, role.title(), PASSWORD, role=role)
    conn.close()
    c = TestClient(app_mod.app)
    c.__enter__()
    r = c.post("/admin/login", data={"email": email, "password": PASSWORD},
               follow_redirects=False)
    assert r.status_code == 303, "the fixture account could not sign in"
    return c


def _project(app_mod):
    conn = db_mod.connect()
    row = conn.execute("SELECT id FROM projects LIMIT 1").fetchone()
    conn.close()
    return row["id"]


# --------------------------------------------------------------------------- #
# The invariants
# --------------------------------------------------------------------------- #
def test_with_no_accounts_nothing_changes(app_mod):
    """A single-operator instance that never made an account behaves exactly as it did
    before this file existed."""
    pid = _project(app_mod)
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"password": PASSPHRASE}, follow_redirects=False)
        r = c.post(f"/project/{pid}/delivery/release", follow_redirects=False)
        assert r.status_code != 403


def test_the_passphrase_keeps_full_access(app_mod):
    """Break-glass. Restricting it would be theatre — whoever holds it can change the
    environment variable — and a break-glass that 403s is not one."""
    pid = _project(app_mod)
    conn = db_mod.connect()
    accounts.create_account(conn, "viewer@x.com", "V", PASSWORD, role="viewer")
    conn.close()
    with TestClient(app_mod.app) as c:
        c.post("/admin/login", data={"password": PASSPHRASE}, follow_redirects=False)
        assert c.post(f"/project/{pid}/delivery/release",
                      follow_redirects=False).status_code != 403


# --------------------------------------------------------------------------- #
# Viewer
# --------------------------------------------------------------------------- #
def test_a_viewer_can_look(app_mod):
    c = _signed_in(app_mod, "viewer")
    try:
        assert c.get("/dashboard", follow_redirects=False).status_code == 200
        assert c.get("/projects", follow_redirects=False).status_code == 200
    finally:
        c.__exit__(None, None, None)


def test_a_viewer_cannot_change_anything(app_mod):
    """Read-only has to mean it. An advisor shown around the console must not be able
    to move a deal by clicking the wrong button."""
    pid = _project(app_mod)
    c = _signed_in(app_mod, "viewer")
    try:
        assert c.post("/opportunity/1/status", data={"status": "Won"},
                      follow_redirects=False).status_code == 403
        assert c.post(f"/project/{pid}/delivery/release",
                      follow_redirects=False).status_code == 403
    finally:
        c.__exit__(None, None, None)


# --------------------------------------------------------------------------- #
# Operator — the first hire
# --------------------------------------------------------------------------- #
def test_an_operator_can_do_the_days_work(app_mod):
    """The point of hiring someone. If the role cannot run a campaign it is not a role,
    it is an obstacle."""
    c = _signed_in(app_mod, "operator")
    try:
        r = c.post("/opportunity/1/status", data={"status": "Pursuing"},
                   follow_redirects=False)
        assert r.status_code != 403
    finally:
        c.__exit__(None, None, None)


def test_an_operator_cannot_assert_a_licence_or_move_money(app_mod):
    """The two irreversible ones. Releasing puts a grant on the certificate a client
    signs against; the rest is someone's money."""
    pid = _project(app_mod)
    c = _signed_in(app_mod, "operator")
    try:
        assert c.post(f"/project/{pid}/delivery/release",
                      follow_redirects=False).status_code == 403
        assert c.post(f"/project/{pid}/delivery/license/confirm",
                      follow_redirects=False).status_code == 403
        assert c.post("/opportunity/1/delete",
                      follow_redirects=False).status_code == 403
    finally:
        c.__exit__(None, None, None)


# --------------------------------------------------------------------------- #
# Owner
# --------------------------------------------------------------------------- #
def test_an_owner_can_do_everything(app_mod):
    pid = _project(app_mod)
    c = _signed_in(app_mod, "owner")
    try:
        for path in (f"/project/{pid}/delivery/release",
                     f"/project/{pid}/delivery/rotate-link",
                     "/opportunity/1/status"):
            assert c.post(path, data={"status": "Pursuing"},
                          follow_redirects=False).status_code != 403, path
    finally:
        c.__exit__(None, None, None)


def test_the_first_account_is_an_owner(tmp_path, monkeypatch):
    """An instance whose only account cannot release a delivery is worse than one with
    no accounts at all — the founder would be locked out of their own product by a
    default."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "f.db"))
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(tmp_path / "up"))
    monkeypatch.setenv("CHORDENTIAL_FIRST_USER", "jon@chordential.com")
    monkeypatch.setenv("CHORDENTIAL_FIRST_PASSWORD", PASSWORD)
    monkeypatch.setenv("CHORDENTIAL_FIRST_NAME", "Jon Shipp")
    importlib.reload(db_mod)
    from chordential_oia.web import app as mod
    importlib.reload(mod)
    with TestClient(mod.app):
        pass
    conn = db_mod.connect()
    row = accounts.get_account(conn, "jon@chordential.com")
    conn.close()
    assert row["role"] == "owner", row["role"]


# --------------------------------------------------------------------------- #
# The rules themselves
# --------------------------------------------------------------------------- #
def test_a_get_is_a_look_and_a_post_is_a_change():
    assert roles.required_for("GET", "/anything") == roles.VIEWER
    assert roles.required_for("POST", "/anything") == roles.OPERATOR


def test_an_unknown_route_defaults_to_restrictive():
    """The property that makes a path-pattern rule survivable: a route added tomorrow
    is covered by its METHOD, so the failure mode is "too strict", never "wide open"."""
    assert roles.required_for("POST", "/some/route/invented/later") == roles.OPERATOR
    assert roles.required_for("DELETE", "/x") == roles.OPERATOR


def test_the_owner_only_list_is_matched_exactly_not_by_prefix():
    """`/project/1/delivery/release` is owner-only; `/project/1/delivery/releases` (if
    it ever exists) is a different route and must not inherit the rule by accident."""
    assert roles.required_for("POST", "/project/1/delivery/release") == roles.OWNER
    assert roles.required_for("POST", "/project/1/delivery/releasenotes") == roles.OPERATOR


def test_ranks_are_ordered():
    assert roles.satisfies("owner", "operator") and roles.satisfies("owner", "viewer")
    assert roles.satisfies("operator", "viewer")
    assert not roles.satisfies("operator", "owner")
    assert not roles.satisfies("viewer", "operator")


def test_an_unknown_role_gets_the_least_power():
    """A typo in a role name, or a row from a future version, must not grant anything."""
    assert roles.rank("wizard") == 0
    assert not roles.satisfies("wizard", "operator")


def test_a_row_without_a_role_column_still_works():
    """Defensive: an account row from before the column existed must not crash the
    gate, and must not silently become an owner."""
    class Row:
        def __getitem__(self, k): raise KeyError(k)
    assert roles.may(Row(), "POST", "/opportunity/1/status") is True      # operator
    assert roles.may(Row(), "POST", "/project/1/delivery/release") is False


def test_roles_says_nothing_about_a_caller_it_does_not_know():
    """`may(None, ...)` is True on purpose: an unsigned-in caller is the passphrase or a
    token-gated client, both decided elsewhere. Answering False here would quietly turn
    this module into a second gate with different rules."""
    assert roles.may(None, "POST", "/project/1/delivery/release") is True
