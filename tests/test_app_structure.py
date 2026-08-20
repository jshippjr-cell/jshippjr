"""`app.py` is being taken apart, one measured slice at a time.

It reached **9,133 lines and 251 routes** — the launch review's Phase 3 finding. The
obstacle to moving any route out was that `render` and the Jinja environment lived in
`app.py`, so a router importing them and `app.py` importing the router formed a cycle.
`shell.py` breaks that: it *creates* the environment, `app.py` still *decorates* it.

`/agencies` went first on measurement rather than taste — 26 routes (10% of the file)
touching only four `app.py` helpers, against 23 and 29 for `/opportunity` and
`/project`, with no route-pattern collision against any other group.

These tests exist so the next slices stay honest: the direction of imports must not
reverse, a moved module must not reach back into `app.py`, and every URL that existed
before a move must still answer afterwards.
"""

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from chordential_oia.web import app as app_mod  # noqa: E402

WEB = Path(app_mod.__file__).parent
ROUTERS = ["agencies_routes.py", "discovery_routes.py",
           "talent_routes.py", "opportunity_routes.py",
           "project_routes.py", "creator_routes.py", "contributor_routes.py",
           "room_routes.py",
           "campaign_routes.py", "simulator_routes.py",
           "workspace_routes.py", "console_routes.py",
           "billing_routes.py", "meetings_routes.py",
           "auth_routes.py"]                             # the whole route layer

# The helper layer (ADR-0044). Measured, not chosen: of the 46 helpers `/opportunity`
# and `/project` reach for, 16 are called by two or more route groups, and the
# transitive closure of those 16 is 31 functions. Those 31 are what could not stay in
# `app.py` if either group is ever to move; the single-group helpers travel with their
# own routes later. The closure fell into these four files on its own — its dependency
# graph has ten components and none of them straddles a file boundary.
HELPERS = ["uploads.py", "billing.py", "delivery_ops.py", "opportunity_ops.py"]

MODULES = ROUTERS + HELPERS


def _module_paths(name):
    """Every (method, path) a route module registers, in its own order."""
    src = (WEB / name).read_text(encoding="utf-8")
    return re.findall(r'^@router\.([a-z]+)\("([^"]*)"', src, re.M)


# --------------------------------------------------------------------------- #
# The direction of dependency
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", MODULES)
def test_a_route_module_never_imports_app(name):
    """The cycle this whole structure exists to avoid. `app.py` imports the routers;
    a router that imports `app.py` back would make the split cosmetic and the import
    order load-bearing."""
    tree = ast.parse((WEB / name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("app"):
            pytest.fail(f"{name} imports app.py — the cycle is back")
        if isinstance(node, ast.Import):
            for a in node.names:
                assert not a.name.endswith(".app"), f"{name} imports app.py"


@pytest.mark.parametrize("name", MODULES)
def test_a_route_module_resolves_every_name_it_uses(name):
    """The failure mode this move actually hit: two module-level constants
    (`AGENCIES_PAGE_SIZE`, `_COMPLETE_MARKER`) stayed behind, so the module imported
    cleanly and then raised NameError on the first request. Import success is not
    evidence; this is."""
    import builtins

    tree = ast.parse((WEB / name).read_text(encoding="utf-8"))
    bound = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
        elif isinstance(n, ast.Assign):
            for t in n.targets:
                for x in ast.walk(t):
                    if isinstance(x, ast.Name):
                        bound.add(x.id)

    unresolved = set()
    # TOP-LEVEL functions only. A nested `def` is analysed as part of its parent, where
    # the enclosing function's parameters are already in `local`; analysing it again on
    # its own reports every closed-over name as unresolved. `client_pay`'s inner `_back`
    # reads the route's `k` that way, and it is correct code.
    fns = [n for n in tree.body
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for fn in fns:
        local = {a.arg for a in fn.args.args + fn.args.kwonlyargs}
        if fn.args.vararg:
            local.add(fn.args.vararg.arg)
        if fn.args.kwarg:
            local.add(fn.args.kwarg.arg)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                local.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    local.add((a.asname or a.name).split(".")[0])
            elif isinstance(n, ast.ExceptHandler) and n.name:
                local.add(n.name)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(n.name)
                # a nested def's parameters are bound inside it
                local |= {a.arg for a in n.args.args + n.args.kwonlyargs}
            elif isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                for g in n.generators:
                    for x in ast.walk(g.target):
                        if isinstance(x, ast.Name):
                            local.add(x.id)
            elif isinstance(n, ast.Lambda):
                local |= {a.arg for a in n.args.args + n.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                if n.id not in local and n.id not in bound:
                    unresolved.add(n.id)
    assert unresolved == set(), (
        f"{name} uses names it neither defines nor imports — these raise NameError on "
        f"the first request, not at import: {sorted(unresolved)}")


def test_the_shell_knows_nothing_about_routes_or_domain():
    """`shell.py` is shared by every future slice, so it has to stay small. If it
    starts importing engines it becomes the new `app.py`."""
    tree = ast.parse((WEB / "shell.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert not any(
                isinstance(d, ast.Attribute) and d.attr in ("get", "post", "put", "delete")
                for d in node.decorator_list), "shell.py declares a route"
    src = (WEB / "shell.py").read_text(encoding="utf-8")
    for engine in ("estimation", "qualification", "delivery", "capabilities", "outreach"):
        assert f"import {engine}" not in src, f"shell.py reaches into {engine}"


# --------------------------------------------------------------------------- #
# The move changed nothing a user can see
# --------------------------------------------------------------------------- #
def test_every_moved_route_still_answers():
    """The point of the exercise: the same URLs, served by the same handlers."""
    with TestClient(app_mod.app) as c:
        for method, path in _module_paths("agencies_routes.py"):
            if "{" in path or method != "get":
                continue                    # parameterised/mutating: covered elsewhere
            assert c.get(path, follow_redirects=False).status_code == 200, path


@pytest.mark.parametrize("prefix,module", [
    ("/agencies", "agencies_routes.py"),
    ("/signals", "discovery_routes.py"),
    ("/discovery", "discovery_routes.py"),
    ("/sources", "discovery_routes.py"),
    ("/leads", "discovery_routes.py"),
    ("/talent", "talent_routes.py"),
    ("/payouts", "talent_routes.py"),
    ("/opportunity", "opportunity_routes.py"),
    ("/project", "project_routes.py"),
    ("/creator", "creator_routes.py"),
    ("/campaign", "campaign_routes.py"),
    ("/simulator", "simulator_routes.py"),
    ("/workspace", "workspace_routes.py"),
    ("/dashboard", "console_routes.py"),
    ("/matchboard", "console_routes.py"),
    ("/revenue", "console_routes.py"),
    ("/invoice", "billing_routes.py"),
    ("/proposal", "billing_routes.py"),
    ("/meet", "meetings_routes.py"),
    ("/meeting", "meetings_routes.py"),
])
def test_a_moved_group_is_declared_in_exactly_one_place(prefix, module):
    """Declared in both files would register duplicates: the first wins and the
    module becomes dead weight that still looks maintained."""
    app_src = (WEB / "app.py").read_text(encoding="utf-8")
    # The prefix must end at a path boundary: "/projects" is its own group and is NOT
    # part of "/project".
    pat = re.escape(prefix) + r'(?=["/])'
    assert not re.search(r'^@app\.[a-z]+\("' + pat, app_src, re.M), (
        f"{prefix} routes are still declared in app.py")
    assert re.search(r'^@router\.[a-z]+\("' + pat,
                     (WEB / module).read_text(encoding="utf-8"), re.M)


def test_the_agencies_group_left_app_py():
    """If the routes are declared in both places the app would register duplicates —
    the first would win and the module would be dead weight."""
    src = (WEB / "app.py").read_text(encoding="utf-8")
    assert not re.search(r'^@app\.[a-z]+\("/agencies', src, re.M), (
        "/agencies routes are still declared in app.py")
    assert "include_router(agencies_router)" in src


def test_app_py_is_getting_smaller_not_larger():
    """A guard rail, not a target. 8,600 leaves room to work while making it obvious
    if a slice is put back or a new surface is grown in the wrong file.

    Raised 750 → 760 (2026-08-18) for the contributor-release surface. What app.py holds
    now is the application object and THE ADMIN GATE, and a new token-gated public
    surface legitimately costs a regex plus an exemption line — that is the gate doing
    its job, not logic creeping back. The alternative on offer was deleting the comments
    explaining why each exemption exists, and those comments are load-bearing: a missing
    exemption silently 303s a real client to the internal login, which has now happened
    twice in production.

    If this needs raising again, extract the gate (`_is_public_path` and its regexes)
    into its own module instead. That is a real shrink; another +10 is not.
    """
    n = len((WEB / "app.py").read_text(encoding="utf-8").splitlines())
    assert n < 760, (
        f"app.py is {n} lines — it was 9,133 before the first slice and should only "
        f"shrink from here")


def test_the_router_carries_the_whole_group():
    paths = _module_paths("agencies_routes.py")
    assert len(paths) == 26
    assert all(p.startswith("/agencies") for _m, p in paths)


@pytest.mark.parametrize("module,prefix,count", [
    ("agencies_routes.py", "/agencies", 26),
    ("talent_routes.py", None, 17),          # two prefixes: /talent + /payouts
    ("discovery_routes.py", None, 25),       # four: /signals /discovery /sources /leads
    ("opportunity_routes.py", "/opportunity", 65),   # +2: fetch a transcript, re-read a
                                                     # capture; +1: the call prep sheet;
                                                     # +2: add a deal by hand (form + post)
    # +1: /project/{id}/review/address — marking a note addressed moved off the
    # creator portal's door, because the room serves three roles and only one of them
    # holds a creator token (see test_addressed_is_ours_not_theirs.py).
    ("project_routes.py", "/project", 69),
    ("creator_routes.py", "/creator", 11),
    # A session player has no portal, no assignments and no reason to come back — not
    # a creator, so not in that router. The group tripwire is what said so.
    ("contributor_routes.py", "/contributor", 2),
    ("campaign_routes.py", "/campaign", 7),
    ("simulator_routes.py", "/simulator", 7),
    ("workspace_routes.py", "/workspace", 6),
])
def test_a_router_carries_its_whole_group_and_nothing_else(module, prefix, count):
    """A route module holds one group. A stray path from somewhere else means a
    decorator landed on the wrong function during the move — which is exactly the shape
    of the bug this slice hit: `ast` puts `.lineno` on the `def`, not on the decorators
    above it, so slicing by `.lineno` leaves `@app.post(...)` behind, bound to whatever
    definition follows it."""
    paths = _module_paths(module)
    assert len(paths) == count
    if prefix:
        assert all(p.startswith(prefix) for _m, p in paths), (
            f"{module} declares paths outside {prefix}: "
            f"{[p for _m, p in paths if not p.startswith(prefix)]}")


def test_no_route_was_lost_or_duplicated_by_any_slice():
    """The invariant the whole breakup rests on: moving code changes no URL. Every
    slice removes declarations from `app.py` and adds the same ones to a router, so the
    total is conserved and no (method, path) is declared twice. A duplicate would
    register two handlers for one URL — the first wins silently and the second becomes
    dead code that still looks maintained.

    268 is pinned deliberately: 251 when the breakup began, +1 for share-token
    rotation, +3 for the storage console (`/settings/storage` and its two buttons),
    +1 for the CORS probe that asks the bucket what it returns to a browser, +2 for
    signing the Clearance Certificate and voiding a signature (ADR-0059), +3 for
    delegated access and the two operator controls over a link's life (ADR-0060),
    +2 for snoozing a Disposition Queue card and bringing them all back, +1 for
    fetching a call's transcript by hand instead of only via the background poller,
    +1 for the call prep sheet (Phase 0 of the Call Copilot, docs/discovery-copilot-plan.md),
    +1 for the rehearsal deal, because the client's half of the product could only be
    tested by walking a real funnel or practising on a real buyer,
    +1 for handing over the client's cut and references in ONE act, because two submit
    buttons on one card threw away whichever file the other was holding,
    +1 for THE room (ADR-0068) — one capability-gated surface for creator, client and
    studio, where there had been three templates rendering one engagement,
    +1 for pricing a client note before it becomes work (ADR-0069) — conform / revision /
    out-of-scope, because a note cost nothing and was actioned anyway,
    +1 for conforming a parked cut (ADR-0069) — a re-cut moves every note with the
    picture instead of leaving them pointing at frames that moved,
    +2 for adding a deal by hand — a form and its post, and until they existed there was no
    way to create an opportunity at all except promoting an inbound lead.
    Retiring
    /samples and /capabilities did NOT change it — both stayed as 301s so no indexed
    link dies. Change this number only when you mean to add or remove a URL, never to
    make a refactor pass."""
    decls = []
    for name, dec in [("app.py", "app")] + [(r, "router") for r in ROUTERS]:
        src = (WEB / name).read_text(encoding="utf-8")
        decls += re.findall(r'^@' + dec + r'\.([a-z]+)\("([^"]*)"', src, re.M)
    dupes = sorted({d for d in decls if decls.count(d) > 1})
    assert dupes == [], f"declared more than once: {dupes}"
    assert len(decls) == 289, (
        f"{len(decls)} route declarations across app.py + the routers, expected 289 — "
        f"a slice lost or gained a URL")


# --------------------------------------------------------------------------- #
# The helper layer
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", HELPERS)
def test_a_helper_module_declares_no_routes(name):
    """These exist so routes can leave. A helper module that starts serving URLs is
    a second `app.py` beginning, and the next slice would be blocked on it in exactly
    the way this one was blocked on `app.py`."""
    src = (WEB / name).read_text(encoding="utf-8")
    assert not re.search(r'^@(app|router)\.[a-z]+\(', src, re.M), (
        f"{name} declares a route — it is a helper module")


def test_the_helper_layer_flows_one_way():
    """`delivery_ops` may call `billing` and `uploads`; nothing may call back. A cycle
    here would not be caught by the import check — Python resolves it at call time —
    it would just make the load order load-bearing again."""
    allowed = {
        "uploads.py": set(),
        "billing.py": set(),
        "delivery_ops.py": {"billing", "uploads"},
        "opportunity_ops.py": set(),
    }
    helper_names = {h[:-3] for h in HELPERS}
    for name in HELPERS:
        tree = ast.parse((WEB / name).read_text(encoding="utf-8"))
        reached = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.module:
                reached.add(node.module.split(".")[-1])
            if isinstance(node, ast.ImportFrom) and node.level and node.module is None:
                reached |= {a.name for a in node.names}
        assert (reached & helper_names) <= allowed[name], (
            f"{name} imports {sorted((reached & helper_names) - allowed[name])} — "
            f"the helper layer has to stay a DAG")
        assert not any(r.endswith("_routes") for r in reached), (
            f"{name} imports a route module — helpers sit below routes, not beside them")


# name -> the module that OWNS it. This replaced a list of names asserted to be
# reachable as `app.<name>`, which was right while `app.py` still held 186 routes and
# the point was that no handler had to be edited. With the route layer fully moved that
# premise expired: `app.py` was left importing 55 names it does not use, purely so tests
# could reach them through it. The invariant that survives is the useful one — each
# helper is defined exactly once, in the module that owns it, and not in `app.py`.
MOVED_HELPERS = {
    # shell.py exports the public spelling; app.py imports it as `_admin_authed`.
    "admin_authed": "shell",
    "_apply_invoice_payment": "billing",
    "_client_portal_url": "billing",
    "_ensure_final_invoice_issued": "billing",
    "_invoice_from_proposal_row": "billing",
    "_proposal_from_row": "billing",
    "_send_invoice_pay_link": "billing",
    "_approve_version_core": "delivery_ops",
    "_build_delivery_package": "delivery_ops",
    "_campaign_label": "delivery_ops",
    "_current_version_tag": "delivery_ops",
    "_gate_banner": "delivery_ops",
    "_maybe_finalize_delivery": "delivery_ops",
    "_notify_assigned_creators": "delivery_ops",
    "_notify_operator_review": "delivery_ops",
    "_project_estimate": "delivery_ops",
    "_sync_role_milestones": "delivery_ops",
    "_brief_ci_context": "opportunity_ops",
    "_buyer_context": "opportunity_ops",
    "_ensure_project_for_opp": "opportunity_ops",
    "_load": "opportunity_ops",
    "_quote_band_for": "opportunity_ops",
    "_reconcile_opp_status": "opportunity_ops",
    "_to_utc_iso": "opportunity_ops",
    "_persist_upload": "uploads",
    "_read_capped": "uploads",
    "_store_pending_submission": "uploads",
}


@pytest.mark.parametrize("helper,owner", sorted(MOVED_HELPERS.items()))
def test_a_moved_helper_lives_in_exactly_one_place(helper, owner):
    """Defined once, in the module that owns it, and NOT in `app.py`.

    The second half matters as much as the first: a copy left behind in `app.py` would
    be dead weight that still looks maintained, and — worse — a test patching the
    `app.py` copy would silently stop affecting the route that reads the real one.
    """
    import importlib

    tree = ast.parse((WEB / "app.py").read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert helper not in defined, f"{helper} is still defined in app.py"
    # Whether `app.py` also *imports* it is not asserted here — the gate middleware
    # legitimately uses `_admin_authed`. `test_app_py_imports_only_what_it_uses` is the
    # instrument for re-exports, and it is exact: an unused import IS a re-export.
    mod = importlib.import_module(f"chordential_oia.web.{owner}")
    assert callable(getattr(mod, helper, None)), f"{helper} is not in web.{owner}"


def test_app_py_imports_only_what_it_uses():
    """The count that made the re-export problem visible: 55 unused imports in a
    655-line file, every one of them there so a test could use `app.py` as a namespace.
    Pyflakes is not available everywhere, so this is an AST check."""
    import builtins

    src = (WEB / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name != "*":
                    imported[(a.asname or a.name).split(".")[0]] = n.lineno
    used = {x.id for x in ast.walk(tree) if isinstance(x, ast.Name)}
    used |= {x.attr for x in ast.walk(tree) if isinstance(x, ast.Attribute)}
    for x in ast.walk(tree):
        if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name):
            used.add(x.value.id)
    unused = sorted(n for n in imported
                    if n not in used and n not in dir(builtins) and n != "annotations")
    assert unused == [], f"app.py imports names it does not use: {unused}"


def test_the_upload_directory_still_follows_the_environment(monkeypatch, tmp_path):
    """The trap this move walked into. A dozen test modules set
    `CHORDENTIAL_UPLOAD_DIR` and then reload only `db` and `app`. Had `UPLOAD_DIR`
    moved into `uploads.py` as a module-level constant, reloading `app` would not
    re-execute that file and every one of those tests would have written to the
    previous directory. `upload_dir()` reads the environment per call; `app.UPLOAD_DIR`
    is computed from it at app-import time, which is what makes the reload work."""
    import importlib

    from chordential_oia.web import uploads as uploads_mod

    target = tmp_path / "elsewhere"
    monkeypatch.setenv("CHORDENTIAL_UPLOAD_DIR", str(target))
    assert uploads_mod.upload_dir() == str(target)
    reloaded = importlib.reload(app_mod)
    try:
        assert reloaded.UPLOAD_DIR == str(target), (
            "app.UPLOAD_DIR ignored the environment on reload")
    finally:
        monkeypatch.undo()
        importlib.reload(app_mod)


def test_a_literal_path_is_still_declared_before_the_parameter_that_shadows_it():
    """Declaration order is load-bearing in exactly one place, and moving a group is
    exactly when it gets lost.

    `GET /simulator/library` and `GET /simulator/{session_id}` both match the URL
    /simulator/library. Starlette takes the first match, so the literal only wins
    because it is registered first. Reorder them and the library page silently becomes
    a session lookup for a session named "library" — a 404 or, worse, a rendered page
    for the wrong thing. Nothing else in the app has this shape; this test exists so
    that if a later pass reshuffles the module, it fails here rather than in the UI.
    """
    paths = [p for m, p in _module_paths("simulator_routes.py") if m == "get"]
    assert "/simulator/library" in paths and "/simulator/{session_id}" in paths
    assert paths.index("/simulator/library") < paths.index("/simulator/{session_id}"), (
        "/simulator/{session_id} is declared before /simulator/library and now shadows it")

    with TestClient(app_mod.app) as c:
        r = c.get("/simulator/library", follow_redirects=False)
        assert r.status_code == 200
        # the library page, not a session view rendered for a session called "library"
        assert "objection" in r.text.lower()

