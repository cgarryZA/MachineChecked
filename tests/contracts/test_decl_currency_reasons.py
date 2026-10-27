"""Why a cited declaration is not known to be current (#434): when the build shows no version of
it, or none was recorded with it, its currency says why and what would let a build check it,
and `workspace show`, `changes --workspace` and the reader show the reason. A synthetic Lean
project (sources and the build files Lake would write, no Lean run) and synthetic builds stand
in for real ones."""

import json

import pytest

from prooflens import changes as chg
from prooflens import cli
from prooflens import dependencies as dp
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.facts import DIR as FACTS
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
SOURCES = {"Ex/Basic.lean": "theorem Ex.built_one : True := trivial\n"
                            "theorem Ex.indexed_only : True := trivial\n"
                            "theorem Ex.recorded : True := trivial\n",
           "Ex/Unbuilt.lean": "theorem Ex.unbuilt_one : True := trivial\n",
           "Ex/Broken.lean": "theorem Ex.broken_one : True := trivial\n"}


def project(root, modules=("Ex.Other",)):
    """A Lean project whose `Ex.Basic` and `Ex.Broken` are built, `Ex.Unbuilt` is not, and whose
    last extraction could not load `Ex.Broken`; with a full assessment's configuration beside
    its working directory that lists `modules`."""
    (root / "lakefile.toml").parent.mkdir(parents=True, exist_ok=True)
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    for rel, text in SOURCES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    olean = root / ".lake" / "build" / "lib" / "lean" / "Ex"
    olean.mkdir(parents=True)
    for m in ("Basic", "Broken"):
        (olean / f"{m}.olean").write_bytes(b"")
    failed = root / ".machinechecked" / "build" / FACTS / "failed"
    failed.mkdir(parents=True)
    (failed / "broken.json").write_text(json.dumps({"key": "Ex.Broken",
                                                    "reason": "unknown identifier 'x'\nmore"}))
    (root / "claims.json").write_text(json.dumps({"claims": []}))
    (root / "machinechecked.toml").write_text(
        '[project]\nname = "p"\nlean_root = "."\ninventory = "claims.json"\nmodules = '
        + json.dumps(list(modules)) + '\nscope_roots = ["Ex"]\nspec_prefix = "Ex.Spec"\n'
        'accept_prefix = "Ex.Acc"\n[[paper]]\nid = "P"\ntitle = "P"\n'
        'source = { path = "paper" }\nroot = "paper.tex"\n')
    return root / ".machinechecked"


def site(work, simple, lean=True, index=("Ex.built_one", "Ex.indexed_only", "Ex.recorded",
                                          "Ex.broken_one")):
    """A build of one claim linked to `Ex.recorded` (the one declaration it records a version
    of): a zero-configuration view (`simple`) with its Lean index of `index`, or a full
    assessment, either one with or without Lean."""
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True, exist_ok=True)
    chunk = {"id": "P:thm:main", "paper": "P", "number": "Theorem 1", "kind": "theorem",
             "key": "thm:main", "source_sha256": "s-1",
             "links": [{"name": "Ex.recorded", "fingerprint": "fp-recorded"}] if lean else [],
             "suggestions": [], "clauses": [], "decls": {}}
    (data / "claims" / "thm_main.json").write_text(json.dumps(chunk))
    idx = {"schema": "prooflens/manifest@1", "release": "v-1",
           "project": {"name": "ex", "commit": "abc123"},
           "papers": [{"id": "P", "title": "P", "revision": "abc123"}],
           "lean": None if simple or not lean else {"lean": "4.0.0"},
           "claims": [{"id": "P:thm:main", "paper": "P", "number": "Theorem 1",
                       "kind": "theorem", "file": "thm_main.json"}]}
    if simple:
        idx["mode"] = "simple"
        (data / "lean-index.json").write_text(json.dumps(
            [{"name": n, "kind": "theorem", "module": "Ex.Basic" if n != "Ex.broken_one"
              else "Ex.Broken"} for n in index] if lean else []))
    (data / "index.json").write_text(json.dumps(idx))
    return Snapshot(data)


def reason(ref, snap, root):
    cur = dp.decl_currency(ref, snap, root)
    assert cur["state"] == "unchecked"
    return cur["reason"]


@pytest.fixture
def proj(tmp_path):
    root = tmp_path / "proj"
    return root, project(root)


def test_no_build_and_a_build_without_lean(proj):
    root, work = proj
    ref = {"decl": "Ex.built_one", "fingerprint": "fp"}
    assert reason(ref, None, root) == ("no build to check it against: run `machinechecked "
                                       "view` or `build`")
    assert reason(ref, site(work, simple=False, lean=False), root) == (
        "this build ran no Lean, so it records no version of Ex.built_one: build again with "
        "Lean")
    assert reason(ref, site(work, simple=True, lean=False), root) == (
        "this build has no Lean index, so it records no version of Ex.built_one: run `lake "
        "build`, then `machinechecked view`")


def test_a_module_not_built_or_not_loaded_and_a_declaration_outside_the_project(proj):
    root, work = proj
    snap = site(work, simple=True)
    assert reason({"decl": "Ex.unbuilt_one", "fingerprint": "fp"}, snap, root) == (
        "its module Ex.Unbuilt is not built: run `lake build Ex.Unbuilt`, then build again")
    assert reason({"decl": "Ex.broken_one", "fingerprint": "fp"}, snap, root) == (
        "its module Ex.Broken could not be loaded (unknown identifier 'x'): fix it, run `lake "
        "build Ex.Broken`, then build again")
    assert reason({"decl": "Nat.add_comm", "build": "external"}, snap, root) == (
        "Nat.add_comm is not a declaration of the project, and a build records versions only "
        "of the project's declarations")


def test_a_declaration_the_project_no_longer_declares(proj):
    root, work = proj
    snap = site(work, simple=True)
    why = reason({"decl": "Ex.bulit_one", "fingerprint": "fp"}, snap, root)
    assert why.startswith("the project does not declare Ex.bulit_one in this build (did you "
                          "mean Ex.built_one")
    assert why.endswith("?): if it was renamed, cite the new name")
    # Without the Lean project the build alone cannot tell more.
    assert reason({"decl": "Ex.bulit_one", "fingerprint": "fp"}, snap, None) == \
        "this build shows no version of Ex.bulit_one"


def test_a_declaration_the_build_does_not_record(proj, tmp_path):
    root, work = proj
    # The view indexes it, and records versions only of what its claims link and use.
    assert reason({"decl": "Ex.indexed_only", "fingerprint": "fp"}, site(work, simple=True),
                  root) == (
        "Ex.indexed_only is in this build's index, but the build records a version only of "
        "the declarations its claims link and those their statements use")
    assert reason({"decl": "Ex.built_one", "fingerprint": "fp"},
                  site(work, simple=True, index=("Ex.recorded",)), root) == (
        "this build's Lean index does not hold Ex.built_one, which Ex.Basic declares: run "
        "`lake build`, then `machinechecked view`")
    # A full assessment records what its inventory's clauses use; the configuration does not
    # list the module either.
    full = site(work, simple=False)
    expected = ("this build records no version of Ex.built_one: a full assessment records the "
                "declarations its inventory's clauses name and those their statements use, and "
                "Ex.built_one is not among them")
    assert reason({"decl": "Ex.built_one", "fingerprint": "fp"}, full, root) == (
        expected + "; its module Ex.Basic is not listed in `modules` of the configuration "
        "either")
    other = tmp_path / "listed"
    full = site(project(other, modules=("Ex.Basic",)), simple=False)
    assert reason({"decl": "Ex.built_one", "fingerprint": "fp"}, full, other) == expected


def test_a_declaration_cited_without_its_version(proj):
    root, work = proj
    snap = site(work, simple=True)
    ref = {"decl": "Ex.recorded", "module": "Ex.Basic", "build": "unbuilt"}
    assert reason(ref, snap, root) == (
        "Ex.recorded was cited while its module Ex.Basic was not built, so no version of it was "
        "recorded: re-pin the evidence (`\"repin\": true`) to record the version this build "
        "shows")


def test_the_reason_reaches_the_finding_the_terminal_and_changes(proj, monkeypatch, capsys):
    root, work = proj
    snap = site(work, simple=True)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [
        {"op": "put", "record": {"id": "e-1", "kind": "evidence", "claim": "P:thm:main",
                                 "role": "supports", "ref": {"decl": "Ex.recorded"}}},
        {"op": "put", "record": {"id": "q-1", "kind": "requirement", "claim": "P:thm:main",
                                 "local_id": "r1", "form": "statement", "text": "it"}},
        {"op": "put", "record": {"id": "a-1", "kind": "alignment", "claim": "P:thm:main",
                                 "requirements": ["r1"], "lean": [{"decl": "Ex.recorded"}]}},
        {"op": "put", "record": {"id": "f-1", "kind": "finding", "claim": "P:thm:main",
                                 "requirement": "r1", "coverage": "full", "evidence": ["e-1"],
                                 "note": "n"}}], snap)
    # The next build has no Lean index.
    later = site(work, simple=True, lean=False)
    why = ("this build has no Lean index, so it records no version of Ex.recorded: run `lake "
           "build`, then `machinechecked view`")
    cur = wsp.currency(wsp.read(p), later, root)
    assert (cur["e-1"]["state"], cur["e-1"]["reason"]) == ("unchecked", why)
    assert cur["a-1"]["state"] == "unchecked" and cur["a-1"]["reason"] == why
    assert why in {u["why"] for u in cur["f-1"]["unknown"]}
    v = wsp.view(wsp.read(p), later, None, root)
    text = "\n".join(chg.workspace_lines(chg.workspace_due(v, "ws")))
    assert f"  evidence e-1 (P:thm:main): unchecked\n    not known: {why}" in text
    monkeypatch.chdir(root)
    cli.main(["workspace", "show", "--id", wsp.read(p)["id"]])
    out = capsys.readouterr().out
    assert f"           not known to be current: {why}" in out
