"""Real accounts and real sessions — additively, so nobody can be locked out.

The console has one shared passphrase (`CHORDENTIAL_ADMIN_TOKEN`). It cannot say who
is behind it, which is why the decision log (ADR-0053) has to record a role rather than
a name. This module gives it names.

**THE INVARIANT: the passphrase keeps working, always.** Accounts are an addition, not
a replacement, and the passphrase stays as break-glass. A change that could lock the
operator out of the system running their business is not worth any amount of tidiness —
and the failure would arrive at the worst moment, on a deploy, with no way back in.
Removing the passphrase is a decision for the operator to make deliberately, later,
with an account they have already used.

Passwords are hashed with `hashlib.scrypt` — stdlib, memory-hard, no new dependency
(and this repo has been bitten twice by dependencies production never installed). The
stored form carries its own parameters, so the cost can be raised later without
invalidating existing hashes.

Session tokens are stored as SHA-256 digests, never in the clear. A session table full
of live tokens is a table full of credentials: anyone who can read the database — a
backup, a support query, a leaked dump — could sign in as anyone. The digest verifies
the cookie and is useless on its own.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

MIN_PASSWORD = 9          # operator's call; NIST SP 800-63B's floor is 8
SESSION_COOKIE = "cdl_session"
SESSION_DAYS = 30

# scrypt cost. n=2**14 is ~16 MB and a few tens of ms — enough to make offline guessing
# expensive, cheap enough to run on every sign-in on a small instance.
_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def norm_email(email: str) -> str:
    return (email or "").strip().lower()


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    """``scrypt$n$r$p$salt$hash`` — the parameters travel WITH the hash, so raising
    the cost later does not invalidate every existing password."""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                        n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time. A comparison that returns early leaks the hash one byte at a
    time to anyone willing to measure."""
    try:
        algo, n, r, p, salt_hex, hash_hex = (stored or "").split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                            n=int(n), r=int(r), p=int(p), dklen=len(hash_hex) // 2)
    except (ValueError, AttributeError, TypeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def create_account(conn, email: str, name: str, password: str,
                   role: str = "operator") -> Optional[int]:
    """Returns the new id, or None if that email already has one."""
    key = norm_email(email)
    if not key or "@" not in key or not password:
        raise ValueError("an account needs an email address and a password")
    if len(password) < MIN_PASSWORD:
        # Short enough to brute-force is short enough to refuse. Stated as a rule the
        # caller can show the human, rather than a silent truncation or a weak hash.
        #
        # NINE, set by the operator. It was 10 — my pick, not a standard — and NIST
        # SP 800-63B's actual floor for a user-chosen password is 8, so 9 sits above the
        # published bar. What carries the weight here is not the length anyway: scrypt
        # makes offline guessing expensive, and the shared passphrase is a separate
        # secret. Raising it later costs nothing, because the hash carries its own
        # parameters and existing passwords stay valid.
        raise ValueError(
            f"the password must be at least {MIN_PASSWORD} characters")
    try:
        conn.execute(
            "INSERT INTO user_account (email, name, password_hash, role, created_at) "
            "VALUES (?,?,?,?,?)",
            (key, (name or "").strip(), hash_password(password), role, _now()))
        conn.commit()
    except Exception:                          # noqa: BLE001 — the UNIQUE index
        try: conn.rollback()
        except Exception: pass
        return None
    row = conn.execute("SELECT id FROM user_account WHERE email = ?", (key,)).fetchone()
    return int(row["id"]) if row is not None else None


def get_account(conn, email: str):
    key = norm_email(email)
    if not key:
        return None
    return conn.execute("SELECT * FROM user_account WHERE email = ?", (key,)).fetchone()


def any_accounts(conn) -> bool:
    try:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM user_account").fetchone()["n"] > 0
    except Exception:                          # noqa: BLE001 — table not built yet
        return False


def authenticate(conn, email: str, password: str):
    """The account, or None. A disabled account never authenticates."""
    row = get_account(conn, email)
    if row is None:
        # Hash anyway. Returning instantly for an unknown address tells an attacker
        # which addresses exist, for free, from the response time alone.
        hash_password(password or "x")
        return None
    if row["disabled_at"]:
        return None
    if not verify_password(password or "", row["password_hash"] or ""):
        return None
    conn.execute("UPDATE user_account SET last_login_at = ? WHERE id = ?",
                 (_now(), row["id"]))
    conn.commit()
    return row


# --------------------------------------------------------------------------- #
# Sessions
# --------------------------------------------------------------------------- #
def _digest(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def start_session(conn, user_id: int, user_agent: str = "") -> str:
    """Returns the raw token ONCE — it is never recoverable from the database."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat()
    conn.execute(
        "INSERT INTO user_session (token_hash, user_id, created_at, expires_at, "
        "last_seen_at, user_agent) VALUES (?,?,?,?,?,?)",
        (_digest(token), int(user_id), _now(), expires, _now(), (user_agent or "")[:200]))
    conn.commit()
    return token


def session_user(conn, token: str):
    """The signed-in account for this cookie, or None. Checks revocation and expiry
    on every request — a session you cannot revoke is not a session, it is a password
    you cannot change."""
    if not token:
        return None
    try:
        row = conn.execute(
            "SELECT s.id AS sid, s.expires_at, s.revoked_at, u.* FROM user_session s "
            "JOIN user_account u ON u.id = s.user_id WHERE s.token_hash = ?",
            (_digest(token),)).fetchone()
    except Exception:                          # noqa: BLE001 — table not built yet
        return None
    if row is None or row["revoked_at"] or row["disabled_at"]:
        return None
    if str(row["expires_at"] or "") <= _now():
        return None
    try:
        conn.execute("UPDATE user_session SET last_seen_at = ? WHERE id = ?",
                     (_now(), row["sid"]))
        conn.commit()
    except Exception:                          # noqa: BLE001 — a touch is not worth a 500
        pass
    return row


def end_session(conn, token: str) -> None:
    """Revoke, do not delete: a signed-out session that leaves no trace also leaves no
    answer to "was this token used after I signed out"."""
    if not token:
        return
    try:
        conn.execute("UPDATE user_session SET revoked_at = ? WHERE token_hash = ? "
                     "AND revoked_at IS NULL", (_now(), _digest(token)))
        conn.commit()
    except Exception:                          # noqa: BLE001
        pass


def revoke_all_for(conn, user_id: int) -> int:
    """Every session for one account — the "sign out everywhere" a password change
    has to perform, or changing it protects nothing already logged in."""
    cur = conn.execute("UPDATE user_session SET revoked_at = ? WHERE user_id = ? "
                       "AND revoked_at IS NULL", (_now(), int(user_id)))
    conn.commit()
    return cur.rowcount or 0


def list_sessions(conn, user_id: int):
    return conn.execute(
        "SELECT id, created_at, last_seen_at, expires_at, revoked_at, user_agent "
        "FROM user_session WHERE user_id = ? ORDER BY id DESC", (int(user_id),)).fetchall()


def bootstrap_from_env(conn) -> Optional[int]:
    """Create the first account from `CHORDENTIAL_FIRST_USER` / `_PASSWORD`, once.

    A first account has to come from somewhere, and the two usual answers are both bad
    here: a public sign-up page on an internal console is an open door, and a seeded
    default password is a published one. Environment variables are set by the person who
    already controls the deploy, so they prove nothing new — which is exactly right for
    a bootstrap. It runs once; after that the variables can be removed and the account
    remains.
    """
    email = norm_email(os.environ.get("CHORDENTIAL_FIRST_USER", ""))
    password = os.environ.get("CHORDENTIAL_FIRST_PASSWORD", "")
    name = os.environ.get("CHORDENTIAL_FIRST_NAME", "").strip()
    if not email or not password:
        return None
    if get_account(conn, email) is not None:
        return None                            # already there; never reset a password
    try:
        # OWNER, not the default operator: this is the founder's own account, and an
        # instance whose only account cannot release a delivery is worse than one with
        # no accounts at all.
        return create_account(conn, email, name, password, role="owner")
    except ValueError as e:
        print(f"[auth] first account NOT created: {e}", flush=True)
        return None
