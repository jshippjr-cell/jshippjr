"""Guards against the production OOM crash-loop (July 2026): a worker fetching one
agency's huge page ballooned past the instance's 512MB, the kernel killed the whole
box (supervisor included, so no error mark was written), and on restart the queue
re-picked the same agency — a crash loop every cycle.

Three layers, each tested here:
  1. the fetch is size-capped and skips binary content types;
  2. the supervisor writes the failure mark BEFORE spawning the worker, so an
     instance death cannot forget the attempt;
  3. the worker sets its own address-space ceiling so a runaway dies alone.
"""
import http.server
import importlib
import threading

import pytest


# --------------------------------------------------------------------------- #
# 1 · Fetch cap
# --------------------------------------------------------------------------- #
class _BigHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/huge":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            chunk = b"<p>" + b"x" * 65533
            for _ in range(200):                 # ~13MB if unbounded
                try:
                    self.wfile.write(chunk)
                except BrokenPipeError:
                    return
        elif self.path == "/binary":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(b"%PDF-1.4 not a web page")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body>small page</body></html>")


@pytest.fixture()
def http_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _BigHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_fetch_caps_a_huge_response_instead_of_slurping_it(http_server, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_FETCH_MAX_BYTES", "300000")
    import chordential_oia.web.enrichment as enrichment
    importlib.reload(enrichment)
    text, ok = enrichment._default_fetch(http_server + "/huge", timeout=10)
    assert ok
    # capped near the limit (one chunk of slack), nowhere near the 13MB served
    assert 250_000 <= len(text.encode()) <= 400_000


def test_fetch_skips_binary_content_types(http_server):
    import chordential_oia.web.enrichment as enrichment
    importlib.reload(enrichment)
    text, ok = enrichment._default_fetch(http_server + "/binary", timeout=10)
    assert (text, ok) == ("", False)


def test_fetch_still_returns_normal_pages(http_server):
    import chordential_oia.web.enrichment as enrichment
    importlib.reload(enrichment)
    text, ok = enrichment._default_fetch(http_server + "/page", timeout=10)
    assert ok and "small page" in text


# --------------------------------------------------------------------------- #
# 2 · Write-ahead failure mark — an instance death cannot forget the attempt
# --------------------------------------------------------------------------- #
def test_agency_is_marked_before_the_worker_spawns(tmp_path, monkeypatch):
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    from chordential_oia.web import db, scheduler
    importlib.reload(db)

    conn = db.connect()
    db.init_db(conn)

    marked_before_spawn = []

    class _FakeProc:
        def wait(self, timeout=None):
            return 0

        def kill(self):
            pass

    def fake_popen(args, env=None):
        # the moment the "instance" would be at risk: was the mark already durable?
        marked_before_spawn.append(list(marks))
        return _FakeProc()

    marks = []

    def on_timeout(c, agency_id):
        marks.append(agency_id)

    monkeypatch.setattr(scheduler.subprocess, "Popen", fake_popen)
    ok = scheduler._run_one_supervised(conn, "decision_makers", 9616, timeout=5,
                                       on_timeout=on_timeout, label="test")
    assert ok                                 # clean worker exit
    assert marks == [9616]                    # marked exactly once
    assert marked_before_spawn == [[9616]]    # ...and BEFORE the worker existed
    conn.close()


def test_dm_error_mark_removes_agency_from_the_queue(tmp_path, monkeypatch):
    """The mark the write-ahead writes must actually stop the re-pick loop."""
    monkeypatch.setenv("CHORDENTIAL_DB", str(tmp_path / "web.db"))
    from chordential_oia.web import db, scheduler
    importlib.reload(db)
    conn = db.connect()
    db.init_db(conn)
    db.upsert_agency(conn, "test", {"name": "Loop Agency", "dedup_key": "loop",
                                    "website": "https://loop.example"})
    aid = conn.execute("SELECT id FROM agencies WHERE dedup_key='loop'").fetchone()["id"]
    assert any(r["id"] == aid for r in db.agencies_needing_decision_makers(conn))
    scheduler._mark_dm_error(conn, aid)
    assert not any(r["id"] == aid for r in db.agencies_needing_decision_makers(conn))
    conn.close()


# --------------------------------------------------------------------------- #
# 3 · Worker memory ceiling
# --------------------------------------------------------------------------- #
def test_worker_sets_an_address_space_ceiling(monkeypatch):
    resource = pytest.importorskip("resource")
    monkeypatch.setenv("CHORDENTIAL_WORKER_MAX_MB", "256")
    before = resource.getrlimit(resource.RLIMIT_AS)
    try:
        import chordential_oia.web._enrich_worker as worker
        importlib.reload(worker)
        soft, _hard = resource.getrlimit(resource.RLIMIT_AS)
        assert soft == 256 * 1024 * 1024
    finally:
        try:
            resource.setrlimit(resource.RLIMIT_AS, before)
        except Exception:
            pass
