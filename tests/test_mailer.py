"""Outbound-email seam — the pluggable mailer.

Mirrors the payments-seam tests: the default (null) provider must be a pure no-op
log (no SMTP touched), and the smtp provider must build a real EmailMessage with
the right To/Subject/From and hand it to a (monkeypatched) smtplib.SMTP. The mailer
is best-effort and NEVER raises — a send failure returns "error", not an exception.
"""

import importlib

import chordential_oia.mailer as mailer_mod


def _reload(monkeypatch, env):
    """Reload the mailer module under a fresh env (provider chosen at call time,
    so a reload isn't strictly required, but keeps each test hermetic)."""
    for k in ("CHORDENTIAL_MAIL_PROVIDER", "CHORDENTIAL_SMTP_HOST",
              "CHORDENTIAL_SMTP_PORT", "CHORDENTIAL_SMTP_USER",
              "CHORDENTIAL_SMTP_PASS", "CHORDENTIAL_SMTP_FROM",
              "CHORDENTIAL_SMTP_STARTTLS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(mailer_mod)


# --------------------------------------------------------------------------- #
# (a) Default provider → "logged", nothing sent.
# --------------------------------------------------------------------------- #
def test_default_provider_logs_and_sends_nothing(monkeypatch):
    m = _reload(monkeypatch, {})

    # If anything tried to open an SMTP connection, fail loudly.
    import smtplib

    def _boom(*a, **k):  # pragma: no cover - asserts it's never reached
        raise AssertionError("null provider must not touch SMTP")

    monkeypatch.setattr(smtplib, "SMTP", _boom)
    monkeypatch.setattr(smtplib, "SMTP_SSL", _boom, raising=False)

    assert m.send_email("dana@agency.com", "Hi", "body") == "logged"
    assert m.mail_configured() is False


# --------------------------------------------------------------------------- #
# (b) smtp provider → builds the message + "sent".
# --------------------------------------------------------------------------- #
class _CaptureSMTP:
    """A stand-in for smtplib.SMTP that records the message instead of sending."""
    captured = {}

    def __init__(self, host, port, timeout=None):
        _CaptureSMTP.captured["host"] = host
        _CaptureSMTP.captured["port"] = port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        _CaptureSMTP.captured["starttls"] = True

    def login(self, user, password):
        _CaptureSMTP.captured["login"] = (user, password)

    def send_message(self, msg):
        _CaptureSMTP.captured["msg"] = msg


def test_smtp_provider_builds_message_and_sends(monkeypatch):
    m = _reload(monkeypatch, {
        "CHORDENTIAL_MAIL_PROVIDER": "smtp",
        "CHORDENTIAL_SMTP_HOST": "smtp.example.com",
        "CHORDENTIAL_SMTP_PORT": "587",
        "CHORDENTIAL_SMTP_USER": "u",
        "CHORDENTIAL_SMTP_PASS": "p",
        "CHORDENTIAL_SMTP_FROM": "deliveries@chordential.com",
    })
    import smtplib
    _CaptureSMTP.captured = {}
    monkeypatch.setattr(smtplib, "SMTP", _CaptureSMTP)

    link = "https://chordential.com/project/3/delivery-portal?r=tok123"
    status = m.send_email(
        "dana@agency.com", "New version ready — Nike",
        f"Open your link:\n{link}\n", html=f"<a href='{link}'>review</a>",
    )

    assert status == "sent"
    cap = _CaptureSMTP.captured
    assert cap["host"] == "smtp.example.com"
    assert cap["starttls"] is True
    assert cap["login"] == ("u", "p")
    msg = cap["msg"]
    assert msg["To"] == "dana@agency.com"
    assert msg["Subject"] == "New version ready — Nike"
    assert msg["From"] == "deliveries@chordential.com"
    # The personal review link is in the body.
    assert link in msg.get_body(("plain",)).get_content()


# --------------------------------------------------------------------------- #
# (d) mail_configured() reflects env.
# --------------------------------------------------------------------------- #
def test_mail_configured_reflects_env(monkeypatch):
    # null → not configured.
    m = _reload(monkeypatch, {})
    assert m.mail_configured() is False
    # smtp but missing host/from → still not configured.
    m = _reload(monkeypatch, {"CHORDENTIAL_MAIL_PROVIDER": "smtp"})
    assert m.mail_configured() is False
    # smtp with host + from → configured.
    m = _reload(monkeypatch, {
        "CHORDENTIAL_MAIL_PROVIDER": "smtp",
        "CHORDENTIAL_SMTP_HOST": "smtp.example.com",
        "CHORDENTIAL_SMTP_FROM": "deliveries@chordential.com",
    })
    assert m.mail_configured() is True


# --------------------------------------------------------------------------- #
# Best-effort: a crashing SMTP server → "error", no exception escapes.
# --------------------------------------------------------------------------- #
def test_smtp_failure_returns_error_never_raises(monkeypatch):
    m = _reload(monkeypatch, {
        "CHORDENTIAL_MAIL_PROVIDER": "smtp",
        "CHORDENTIAL_SMTP_HOST": "smtp.example.com",
        "CHORDENTIAL_SMTP_FROM": "deliveries@chordential.com",
    })
    import smtplib

    def _boom(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(smtplib, "SMTP", _boom)
    assert m.send_email("dana@agency.com", "Hi", "body") == "error"


def test_empty_recipient_is_error(monkeypatch):
    m = _reload(monkeypatch, {})
    assert m.send_email("", "Hi", "body") == "error"


# --------------------------------------------------------------------------- #
# branded_html — the ONE shell shared by every outbound email (recruiting
# invite, outreach, capabilities doc) so they read as the same studio.
# --------------------------------------------------------------------------- #
def test_branded_html_includes_the_logo_at_an_absolute_url():
    out = mailer_mod.branded_html("https://chordential.com", "Hi there.")
    assert 'src="https://chordential.com/static/public/wordmark-dark.png"' in out


def test_branded_html_escapes_body_and_preserves_line_breaks():
    out = mailer_mod.branded_html("https://chordential.com", "Line one\nLine <two>")
    assert "Line one<br>Line &lt;two&gt;" in out
    assert "<two>" not in out  # never unescaped into real markup


def test_branded_html_strips_trailing_slash_from_base_url():
    out = mailer_mod.branded_html("https://chordential.com/", "Hi.")
    assert "https://chordential.com/static/public/wordmark-dark.png" in out
    assert "chordential.com//static" not in out


# --------------------------------------------------------------------------- #
# Intake acknowledgment — the automated "thanks for reaching out" every inbound
# client intake (questionnaire, book-a-call, discovery request) fires.
# --------------------------------------------------------------------------- #
def test_intake_ack_body_uses_first_name_and_fixed_copy():
    subject, body = mailer_mod.intake_ack_body("Dana Reyes")
    assert subject == "Thanks for reaching out to Chordential"
    assert body.startswith("Hi Dana,")           # first name only
    assert "We've received your request" in body
    assert "a few proposed meeting times" in body
    assert body.rstrip().endswith("Best,\nJon Shipp")


def test_intake_ack_body_falls_back_when_name_blank():
    _subject, body = mailer_mod.intake_ack_body("")
    assert body.startswith("Hi there,")


def test_send_intake_ack_is_noop_but_logged_by_default(monkeypatch):
    m = _reload(monkeypatch, {})                  # null provider
    assert m.send_intake_ack("dana@agency.com", "Dana") == "logged"
    assert m.send_intake_ack("", "Dana") == "error"   # no recipient


def test_send_intake_ack_delivers_when_configured(monkeypatch):
    m = _reload(monkeypatch, {})
    sent = {}

    def fake_send(to, subject, text, html=None):
        sent.update(to=to, subject=subject, text=text, html=html)
        return "sent"

    monkeypatch.setattr(m, "send_email", fake_send)
    assert m.send_intake_ack("dana@agency.com", "Dana Reyes") == "sent"
    assert sent["to"] == "dana@agency.com"
    assert sent["subject"] == "Thanks for reaching out to Chordential"
    assert sent["html"] and "wordmark-dark.png" in sent["html"]
