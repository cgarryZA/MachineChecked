"""A declaration that a build has no record of is refused with what is true of that build
(#438). A full assessment keeps no Lean index: its build records the declarations its
inventory's clauses name and those their statements use, so a built project declaration no
clause uses is refused with that reason and what would let a build record it, and a build that
ran no Lean says so. A zero-configuration view without an index keeps its own advice. A
synthetic Lean project (its sources and the build files Lake would write, no Lean run) and
synthetic builds stand in for real ones; tests/contracts/test_workspace_full.py has the toy
example's."""

import json
import re
import shutil

import pytest

from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot, TargetError, resolve_declaration

WHO = rc.parse_reviewer("human:A-Auditor")
SOURCES = {"Ex/Basic.lean": "namespace Ex\ntheorem recorded : True := trivial\n"
                            "theorem helper : True := trivial\nend Ex\n",
           "Ex/Extra.lean": "namespace Ex\ntheorem extra : True := trivial\nend Ex\n"}

UNRECORDED = ("this build records no version of {name}: a full assessment records the "
              "declarations its inventory's clauses name and those their statements use, and "
              "{name} is not among them")


def project(root, modules=("Ex.Basic",)):
    """A Lean project whose modules `Ex.Basic` and `Ex.Extra` are built, with a full
    assessment's configuration beside its working directory that lists `modules`."""
    (root / "lakefile.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    for rel, text in SOURCES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    olean = root / ".lake" / "build" / "lib" / "lean" / "Ex"
    olean.mkdir(parents=True, exist_ok=True)
    for m in ("Basic", "Extra"):
        (olean / f"{m}.olean").write_bytes(b"")
    (root / "claims.json").write_text(json.dumps({"claims": []}))
    (root / "machinechecked.toml").write_text(
        '[project]\nname = "p"\nlean_root = "."\ninventory = "claims.json"\nmodules = '
        + json.dumps(list(modules)) + '\nscope_roots = ["Ex"]\nspec_prefix = "Ex.Spec"\n'
        'accept_prefix = "Ex.Acc"\n[[paper]]\nid = "P"\ntitle = "P"\n'
        'source = { path = "paper" }\nroot = "paper.tex"\n')
    return root / ".machinechecked"


def site(work, simple=False, lean=True):
    """A build of one claim whose clause states `Ex.recorded`, the one declaration it records:
    a full assessment, with or without Lean, or (`simple`) a zero-configuration view whose
    Lean index is missing."""
    data = work / "site" / "data"
    shutil.rmtree(data, ignore_errors=True)
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    (data / "claims" / "thm_main.json").write_text(json.dumps(
        {"id": "P:thm:main", "paper": "P", "number": "Theorem 1", "kind": "theorem",
         "key": "thm:main", "source_sha256": "s-1", "links": [], "suggestions": [],
         "clauses": [], "decls": {"Ex.recorded": "k-recorded"} if lean else {}}))
    if lean:
        (data / "decls" / "k-recorded.json").write_text(json.dumps(
            {"name": "Ex.recorded", "module": "Ex.Basic", "fingerprint": "fp-recorded",
             "kind": "theorem", "uses": []}))
    idx = {"schema": "prooflens/manifest@1", "release": "v-1",
           "project": {"name": "ex", "commit": "abc123"},
           "papers": [{"id": "P", "title": "P", "revision": "abc123"}],
           "lean": {"lean": "4.0.0"} if lean and not simple else None,
           "claims": [{"id": "P:thm:main", "paper": "P", "number": "Theorem 1",
                       "kind": "theorem", "file": "thm_main.json"}]}
    if simple:
        idx["mode"] = "simple"
    (data / "index.json").write_text(json.dumps(idx))
    return Snapshot(data)


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    return root, project(root)


def refusal(name, snap, root, module=None, **kw):
    with pytest.raises(TargetError) as e:
        resolve_declaration(name, snap, root, module, **kw)
    return e.value


def test_a_full_assessment_refuses_a_declaration_it_does_not_record(proj, tmp_path):
    root, work = proj
    snap = site(work)
    # What the build records resolves from its store, with or without the module.
    for module in (None, "Ex.Basic"):
        assert resolve_declaration("Ex.recorded", snap, root, module) == {
            "name": "Ex.recorded", "module": "Ex.Basic", "build": "built"}
    # A declaration of a module the configuration lists, which no clause uses.
    for module in (None, "Ex.Basic"):
        e = refusal("Ex.helper", snap, root, module)
        assert str(e) == (UNRECORDED.format(name="Ex.helper") + ". To cite it, name it in a "
                          "clause or a proof step of the inventory and build again")
        assert (e.kind, e.candidates) == ("unrecorded", [{"name": "Ex.helper",
                                                          "module": "Ex.Basic"}])
    # One of a module it does not list: listing the module is needed too.
    e = refusal("Ex.extra", snap, root, external=True)
    assert str(e) == (UNRECORDED.format(name="Ex.extra") + "; its module Ex.Extra is not "
                      "listed in `modules` of the configuration either. To cite it, name it in "
                      "a clause or a proof step of the inventory, list Ex.Extra in `modules`, "
                      "and build again")
    # Named in another module than the one that declares it: that module is named.
    e = refusal("Ex.extra", snap, root, "Ex.Basic")
    assert str(e) == "Ex.extra is not declared in Ex.Basic; it is declared in Ex.Extra"
    # A configuration elsewhere (here none) lists nothing this build can read: no module note.
    other = tmp_path / "elsewhere"
    project(other)
    (other / "machinechecked.toml").unlink()
    e = refusal("Ex.extra", site(other / ".machinechecked"), other)
    assert "not listed" not in str(e) and "list Ex.Extra" not in str(e)


def test_a_name_no_module_declares_and_a_build_without_lean(proj):
    root, work = proj
    snap = site(work)
    e = refusal("Ex.helpr", snap, root)
    assert str(e) == ("this build records no version of Ex.helpr, and no module of the project "
                      "declares it as far as its source shows (pass --external for one from a "
                      "dependency)")
    # The nearest names the store and the built modules' sources hold, nearest first.
    assert e.candidates[0] == {"name": "Ex.helper"}
    e = refusal("Ex.helpr", snap, root, "Ex.Basic")
    assert str(e) == ("Ex.helpr is not declared in Ex.Basic, nor elsewhere in the project as far "
                      "as its source shows (pass --external for one from a dependency)")
    assert e.candidates[0] == {"name": "Ex.helper"}
    # A dependency's declaration is accepted when it is said to be one.
    assert resolve_declaration("Nat.add_comm", snap, root, external=True) == {
        "name": "Nat.add_comm", "module": None, "build": "external"}
    assert resolve_declaration("Nat.add_comm", snap, root, "Init.Core", external=True) == {
        "name": "Nat.add_comm", "module": "Init.Core", "build": "external"}
    # A full assessment built without Lean records no declaration at all.
    snap = site(work, lean=False)
    for name, module in (("Ex.recorded", None), ("Ex.helper", "Ex.Basic"),
                         ("Nat.add_comm", None)):
        e = refusal(name, snap, root, module, external=True)
        assert str(e) == (f"this build ran no Lean, so it records no version of {name}: build "
                          "again with Lean")
        assert e.kind == "no-build"


def test_a_view_without_a_lean_index_keeps_its_advice(proj):
    root, work = proj
    snap = site(work, simple=True, lean=False)
    e = refusal("Ex.helper", snap, root)
    assert str(e) == ("Ex.helper: this build has no Lean index; run `machinechecked view` after "
                      "`lake build`")
    assert e.kind == "no-build"
    e = refusal("Ex.helper", snap, root, "Ex.Basic")
    assert str(e) == ("Ex.helper: this build has no Lean index to find it in Ex.Basic; run "
                      "`machinechecked view` after `lake build`")
    assert e.kind == "no-build"


def test_workspace_evidence_and_main_results_are_refused_with_the_reason(proj):
    root, work = proj
    snap = site(work)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    before = p.read_bytes()
    expected = re.escape(UNRECORDED.format(name="Ex.helper"))
    for ops in ([{"op": "put", "record": {"kind": "evidence", "claim": "P:thm:main",
                                          "role": "supports", "ref": {"decl": "Ex.helper"}}}],
                [{"op": wsp.MAIN_OP, "main": ["Ex.helper"]}]):
        with pytest.raises(wsp.WorkspaceError, match=expected):
            wsp.update(p, ops, snap, root)
    assert p.read_bytes() == before
    ack = wsp.update(p, [{"op": "put", "record": {
        "id": "e-1", "kind": "evidence", "claim": "P:thm:main", "role": "supports",
        "ref": {"decl": "Ex.recorded"}}}], snap, root)
    assert ack["changed"] == ["e-1"]
    ref = wsp.read(p)["records"]["e-1"]["ref"]
    assert (ref["module"], ref["build"], ref["fingerprint"]) == ("Ex.Basic", "built",
                                                                 "fp-recorded")
