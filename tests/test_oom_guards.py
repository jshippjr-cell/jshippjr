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
import subprocess
import sys
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
def test_worker_sets_an_address_space_ceiling():
    """Checked in a SUBPROCESS, because importing the worker caps the process it lands in
    and that cap cannot be undone.

    `_enrich_worker` sets RLIMIT_AS soft AND hard together — `(cap,) * 2` — and a lowered
    HARD limit can never be raised again, not even by root. This test used to import the
    module into the pytest process and restore the limit in a `finally`, where the restore
    raised `ValueError: not allowed to raise maximum limit` straight into an
    `except Exception: pass`. Every test that ran afterwards in that process was capped at
    256 MB of address space, and the first one to need a thread stack — a Starlette
    TestClient opening its portal thread — hung in `Thread.start()` for ever, with no
    failure and no message. Whole batches timed out and were written off as slow.

    A subprocess is also the honest place to check it: that module exists to be spawned.
    """
    pytest.importorskip("resource")
    probe = (
        "import importlib, os, resource\n"
        "os.environ['CHORDENTIAL_WORKER_MAX_MB'] = '256'\n"
        "import chordential_oia.web._enrich_worker as w\n"
        "importlib.reload(w)\n"
        "print(resource.getrlimit(resource.RLIMIT_AS)[0])\n"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) == 256 * 1024 * 1024


def test_measuring_the_ceiling_does_not_cap_the_test_process():
    """The guard on the above. If this file ever caps its own process again, everything
    after it in the run hangs instead of failing — so assert the parent is untouched, and
    prove a thread can still start."""
    resource = pytest.importorskip("resource")
    import threading
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    assert hard == resource.RLIM_INFINITY, (
        "a hard address-space cap leaked into the test process and can never be lifted")
    done = threading.Event()
    t = threading.Thread(target=done.set)
    t.start()
    assert done.wait(10), "Thread.start() stalled — the address space is capped"
    t.join(10)
