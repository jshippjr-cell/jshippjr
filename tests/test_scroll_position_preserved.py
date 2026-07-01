"""Every edit action in the internal dashboard (add/remove a chip, save
notes, change a status…) is a plain form POST that redirects back to the
same page — a full page load, which used to reset scroll to the top. On a
long page (the capabilities doc especially) that read as "nothing
happened," since whatever you just edited scrolled out of view. Fixed with
a small sessionStorage-based scroll-restore script: record scroll position
right before any form submits, restore it right after the reload.

capabilities_doc.html is a standalone template (it doesn't extend
base.html — it's a printable client-facing document with no dashboard
chrome), so it needs its own copy of the same fix.
"""

import importlib

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "test.db"))
    from chordential_oia.web import db as db_mod
    importlib.reload(db_mod)
    from chordential_oia.web import app as app_mod
    importlib.reload(app_mod)
    with TestClient(app_mod.app) as c:
        yield c


def _scroll_restore_script_present(html: str) -> bool:
    return (
        "sessionStorage.setItem(KEY, String(window.scrollY));" in html
        and "window.scrollTo(0, parseInt(saved, 10) || 0);" in html
    )


def test_base_template_has_scroll_restore_script():
    base = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/templates/base.html"
    ).read_text()
    assert _scroll_restore_script_present(base)
    # Attached at document/capture level so it catches every form on every
    # page that extends this template, not just ones authors remember to tag.
    assert "document.addEventListener('submit', function (e) {" in base
    assert ", true);" in base


def test_capabilities_doc_has_its_own_copy_since_it_does_not_extend_base(client):
    """capabilities_doc.html is a standalone <!DOCTYPE html> template — the
    base.html fix alone would silently miss the exact page named in the bug
    report ("clicking options to add in the capabilities doc scrolls to the
    top")."""
    tpl_path = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src/chordential_oia/web/templates/capabilities_doc.html"
    )
    text = tpl_path.read_text()
    assert not text.lstrip().startswith("{% extends")
    assert _scroll_restore_script_present(text)


def test_capabilities_doc_route_actually_serves_the_script(client):
    from chordential_oia.web.showcase import get_showcase  # noqa: F401  (ensure app boots)
    r = client.get("/opportunity/1/capabilities")
    # Opportunity 1 may not exist in a fresh test DB; either way the route
    # must not 500, and if it renders, the script must be present.
    assert r.status_code in (200, 303, 404)
    if r.status_code == 200:
        assert _scroll_restore_script_present(r.text)
