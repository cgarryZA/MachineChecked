"""A declaration named with its module (#383) is looked for in that module only: in the build's
index (or, without one, the shared store), in its source when it is not built, and when it could
not be loaded. A name that module does not declare is refused with the modules that do, never
resolved to another module. A synthetic project stands in for Lean: its sources, `.olean` files
and a failed load are written by the test, so no Lean runs."""

import json
import re

import pytest

from test_workspace import WHO, make_build, put

from prooflens import workspace as wsp
from prooflens.targets import Snapshot, TargetError, resolve_declaration

SOURCES = {"Basic": "namespace Ex\ntheorem main : True := trivial\nend Ex\n",
           "Other": "namespace Ex\ntheorem other : True := trivial\nend Ex\n",
           "Later": "namespace Ex\ntheorem later_x : True := trivial\nend Ex\n",
           "Broken": "namespace Ex\ntheorem broken_x : True := trivial\nend Ex\n"}


def lean_project(root):
    """`Ex.Basic` and `Ex.Other` built, `Ex.Later` not built, `Ex.Broken` built but not
    loaded by the last extraction."""
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    (root / "Ex").mkdir()
    for m, text in SOURCES.items():
        (root / "Ex" / f"{m}.lean").write_text(text)
    olean = root / ".lake" / "build" / "lib" / "lean" / "Ex"
    olean.mkdir(parents=True)
    for m in ("Basic", "Other", "Broken"):
        (olean / f"{m}.olean").write_bytes(b"")
    failed = root / ".machinechecked" / "build" / "facts" / "failed"
    failed.mkdir(parents=True)
    (failed / "broken.json").write_text(json.dumps({"key": "Ex.Broken",
                                                     "reason": "a synthetic load failure"}))


@pytest.fixture
def project(tmp_path):
    snap = make_build(tmp_path / ".machinechecked")
    lean_project(tmp_path)
    return tmp_path, snap


def test_an_explicit_module_is_the_only_one_searched(project):
    root, snap = project

    def r(name, module=None, **k):
        return resolve_declaration(name, snap, root, module, **k)

    # Found in the module named: in the index, in its source when it is not built, and in its
    # source when it could not be loaded.
    assert r("Ex.main", "Ex.Basic") == {"name": "Ex.main", "module": "Ex.Basic",
                                        "build": "built"}
    assert r("Ex.later_x", "Ex.Later") == {"name": "Ex.later_x", "module": "Ex.Later",
                                           "build": "unbuilt"}
    assert r("Ex.broken_x", "Ex.Broken") == {"name": "Ex.broken_x", "module": "Ex.Broken",
                                             "build": "not loaded"}
    # Declared in another module than the one named (built, not built or not loaded): refused,
    # with the module that declares it, also when a dependency's declaration would be accepted.
    for name, module, where in (("Ex.main", "Ex.Other", "Ex.Basic"),
                                ("Ex.main", "Ex.Later", "Ex.Basic"),
                                ("Ex.later_x", "Ex.Basic", "Ex.Later"),
                                ("Ex.later_x", "Ex.Broken", "Ex.Later"),
                                ("Ex.broken_x", "Ex.Basic", "Ex.Broken"),
                                ("Ex.broken_x", "Ex.Later", "Ex.Broken")):
        for external in (False, True):
            with pytest.raises(TargetError) as e:
                r(name, module, external=external)
            assert str(e.value) == f"{name} is not declared in {module}; it is declared in {where}"
            assert e.value.candidates == [{"name": name, "module": where}]
    # Declared nowhere in the project: refused, or a dependency's declaration with `external`.
    with pytest.raises(TargetError, match=re.escape(
            "Ex.nothing is not declared in Ex.Basic, nor elsewhere in the project")):
        r("Ex.nothing", "Ex.Basic")
    assert r("Dep.lemma", "Dep.Mod", external=True) == {"name": "Dep.lemma", "module": "Dep.Mod",
                                                         "build": "external"}
    # Without a module every module is searched, as before.
    assert r("Ex.main")["module"] == "Ex.Basic"
    assert r("Ex.later_x") == {"name": "Ex.later_x", "module": "Ex.Later", "build": "unbuilt"}
    assert r("Ex.broken_x") == {"name": "Ex.broken_x", "module": "Ex.Broken",
                                "build": "not loaded"}
    assert r("Dep.lemma", external=True) == {"name": "Dep.lemma", "module": None,
                                             "build": "external"}


def test_without_an_index_the_shared_store_is_searched_in_that_module(tmp_path):
    work = tmp_path / ".machinechecked"
    make_build(work)
    data = work / "site" / "data"
    (data / "lean-index.json").unlink()
    (data / "decls" / "k-stored.json").write_text(json.dumps(
        {"name": "Ex.stored", "module": "Ex.Basic", "fingerprint": "fp:stored", "kind": "def"}))
    snap = Snapshot(data)
    assert resolve_declaration("Ex.stored", snap, None, "Ex.Basic") == {
        "name": "Ex.stored", "module": "Ex.Basic", "build": "built"}
    assert resolve_declaration("Ex.stored", snap, None)["module"] == "Ex.Basic"
    with pytest.raises(TargetError, match=re.escape(
            "Ex.stored is not declared in Ex.Other; it is declared in Ex.Basic")):
        resolve_declaration("Ex.stored", snap, None, "Ex.Other")
    # With the project built and no index, a name the store does not hold cannot be looked for
    # in the module named.
    lean_project(tmp_path)
    with pytest.raises(TargetError) as e:
        resolve_declaration("Ex.main", snap, tmp_path, "Ex.Basic")
    assert e.value.kind == "no-build"


def test_a_reference_to_the_wrong_module_is_refused_and_writes_nothing(project):
    root, snap = project
    p = wsp.open_for(root / ".machinechecked", WHO, "informed", sources=snap.sources())
    wsp.update(p, [put({"id": "q1", "kind": "requirement", "claim": "1", "local_id": "r1",
                        "form": "condition", "text": "a synthetic condition"})], snap, root)
    before = p.read_bytes()
    for ops, why in (
            ([put({"kind": "evidence", "claim": "1",
                   "ref": {"decl": "Ex.later_x", "module": "Ex.Basic"}})],
             "Ex.later_x is not declared in Ex.Basic; it is declared in Ex.Later"),
            ([put({"kind": "alignment", "claim": "1", "requirements": ["r1"],
                   "lean": [{"decl": "Ex.broken_x", "module": "Ex.Basic"}]})],
             "Ex.broken_x is not declared in Ex.Basic; it is declared in Ex.Broken"),
            ([{"op": wsp.MAIN_OP, "main": ["Ex.Other:Ex.later_x"]}],
             "Ex.later_x is not declared in Ex.Other; it is declared in Ex.Later")):
        with pytest.raises(wsp.WorkspaceError, match=re.escape(why)):
            wsp.update(p, ops, snap, root)
    assert p.read_bytes() == before
    # Named in the module that declares it, the reference keeps that module.
    wsp.update(p, [put({"id": "e-later", "kind": "evidence", "claim": "1",
                        "ref": {"decl": "Ex.later_x", "module": "Ex.Later"}})], snap, root)
    ref = wsp.read(p)["records"]["e-later"]["ref"]
    assert (ref["decl"], ref["module"], ref["build"]) == ("Ex.later_x", "Ex.Later", "unbuilt")
