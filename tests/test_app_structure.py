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
           "talent_routes.py"]           # grows with each slice

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
    fns = [n for n in ast.walk(tree)
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
])
def test_a_moved_group_is_declared_in_exactly_one_place(prefix, module):
    """Declared in both files would register duplicates: the first wins and the
    module becomes dead weight that still looks maintained."""
    app_src = (WEB / "app.py").read_text(encoding="utf-8")
    assert not re.search(r'^@app\.[a-z]+\("' + re.escape(prefix), app_src, re.M), (
        f"{prefix} routes are still declared in app.py")
    assert re.search(r'^@router\.[a-z]+\("' + re.escape(prefix), 
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
    if a slice is put back or a new surface is grown in the wrong file."""
    n = len((WEB / "app.py").read_text(encoding="utf-8").splitlines())
    assert n < 7000, (
        f"app.py is {n} lines — it was 9,133 before the first slice and should only "
        f"shrink from here")


def test_the_router_carries_the_whole_group():
    paths = _module_paths("agencies_routes.py")
    assert len(paths) == 26
    assert all(p.startswith("/agencies") for _m, p in paths)


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


MOVED_HELPERS = [
    "_admin_authed", "_apply_invoice_payment", "_approve_version_core",
    "_brief_ci_context", "_build_delivery_package", "_buyer_context", "_campaign_label",
    "_client_portal_url", "_ensure_project_for_opp", "_gate_banner",
    "_invoice_from_proposal_row", "_load", "_maybe_finalize_delivery",
    "_notify_assigned_creators", "_notify_operator_review", "_persist_upload",
    "_proposal_from_row", "_reconcile_opp_status", "_send_invoice_pay_link",
    "_store_pending_submission", "_to_utc_iso",
]


@pytest.mark.parametrize("helper", MOVED_HELPERS)
def test_a_moved_helper_is_defined_once_and_still_reachable(helper):
    """Two things at once, because the move is only safe if both hold: the definition
    is gone from `app.py` (otherwise the copy in the helper module is dead weight that
    still looks maintained), and the name still resolves on `app` — 186 routes and a
    dozen test modules call these by their old names, and the whole point of importing
    them back is that no handler had to be edited."""
    tree = ast.parse((WEB / "app.py").read_text(encoding="utf-8"))
    defined = {n.name for n in tree.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert helper not in defined, f"{helper} is still defined in app.py"
    assert callable(getattr(app_mod, helper, None)), (
        f"{helper} is no longer reachable as app.{helper}")


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
