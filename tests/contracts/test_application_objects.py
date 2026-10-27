"""The objects an application is about, and the scope of further callers (#144), from synthetic
probe records: no Lean runs."""

import pytest

from prooflens import uses as us
from prooflens.simple import ViewError


def record(params, result_depends):
    return {"record": "app", "name": "Syn.lemma", "caller": "Syn.caller", "index": 0,
            "path": "/1", "params": params, "result": {"text": "LEAN-RESULT"},
            "result_depends": result_depends, "open": [], "locals": []}


def binder(i, name, role, depends, origin=None, type_former=False):
    return {"index": i, "binder": name, "role": role, "binder_info": "explicit",
            "type": {"text": f"LEAN-TYPE-{name}"}, "argument": None if role == "premise"
            else {"text": f"LEAN-ARG-{name}"}, "origin": origin or {"kind": "term"},
            "depends": depends, "type_former": type_former}


def test_each_object_receives_the_premises_that_mention_it_and_the_conclusion():
    # (α : Type) (P : α → Prop) (x y : α) (hx : P x) (hxy : R x y) [inst] : Q y
    params = [binder(0, "α", "parameter", [], type_former=True),
              binder(1, "P", "parameter", [0]),
              binder(2, "x", "parameter", [0]),
              binder(3, "y", "parameter", [0]),
              binder(4, "hx", "premise", [0, 1, 2], {"kind": "caller hypothesis", "name": "h"}),
              binder(5, "hxy", "premise", [0, 2, 3], {"kind": "theorem application",
                                                     "name": "Syn.rel"}),
              binder(6, "inst", "instance", [0], {"kind": "instance", "name": "Syn.inst"})]
    a = us.application(record(params, [0, 1, 3]), "Syn.caller", {})
    objs = {o["binder"]: o for o in a["objects"]}
    # A type and an instance are not objects; a predicate is.
    assert list(objs) == ["P", "x", "y"]
    props = {b: [(p["basis"], p.get("binder"), p.get("discharge")) for p in o["properties"]]
             for b, o in objs.items()}
    assert props == {"P": [("premise", "hx", "assumed"), ("conclusion", None, None)],
                     "x": [("premise", "hx", "assumed"), ("premise", "hxy", "proved")],
                     "y": [("premise", "hxy", "proved"), ("conclusion", None, None)]}
    assert objs["y"]["properties"][1]["statement"] == "LEAN-RESULT"
    assert objs["x"]["argument"] == "LEAN-ARG-x"
    t = us.text({"ok": True, "declaration": {"name": "Syn.lemma", "kind": "theorem",
                                             "module": "Syn"},
                 "scope": {"modules": 1, "libraries": ["Syn"], "unbuilt": [], "failed": {}},
                 "answer": "used", "users": [], "applications": [a], "note": "N"})
    assert "premise   hxy : LEAN-TYPE-hxy  (about x, y)" in t
    assert "gives     LEAN-RESULT  (about P, y)" in t


def test_objects_are_not_guessed_when_lean_unfolded_the_type():
    params = [binder(0, "n", "parameter", []), binder(1, "h", "premise", None)]
    a = us.application(record(params, None), "Syn.caller", {})
    assert "objects" not in a and a["objects_note"].startswith("not determined")
    # A record from before the probe read the binders says nothing about objects either.
    old = [{k: v for k, v in p.items() if k not in us.OF_THE_TYPE} for p in params]
    assert "objects" not in us.application(record(old, None), "Syn.caller", {})


def test_an_application_id_names_its_caller():
    assert us.selection("Syn.caller") == ("Syn.caller", None)
    assert us.selection("app:Syn.caller.proof_1:12") == ("Syn.caller.proof_1",
                                                         "app:Syn.caller.proof_1:12")
    assert us.selection(None) == (None, None)
    with pytest.raises(ViewError):
        us.selection("app:Syn.caller")


def test_further_callers_are_read_in_the_modules_that_import_the_declaration():
    graph = {"A.Base": [], "A.Use": ["A.Base"], "A.Top": ["A.Use"], "B.Base": [],
             "B.Use": ["B.Base"]}
    refs = [{"record": "refs", "name": n, "module": m} for n, m in
            [("X.base", "A.Base"), ("A.use", "A.Use"), ("A.top", "A.Top"),
             ("X.base", "B.Base"), ("B.use", "B.Use")]]
    assert [r["module"] for r in us._importing(refs, graph, "A.Base")] == [
        "A.Base", "A.Use", "A.Top"]
    assert [r["module"] for r in us._importing(refs, graph, "B.Base")] == ["B.Base", "B.Use"]
