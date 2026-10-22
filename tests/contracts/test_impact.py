"""`compare --query impact` (#112) on synthetic records: how each main result uses a
declaration, which claims' Lean uses it, and what the answer says when a record is missing.

The references, as Lean's terms would make them: `Syn.main`'s proof applies `Syn.step`, whose
proof applies `Syn.used`; an auxiliary lemma Lean generated for `Syn.main`'s proof states
something about `Syn.Bound`; `Syn.main`'s statement is stated with `Syn.Jet` and `Syn.Scale`.
`Syn.apart` applies `Syn.used` and no main result uses it. `Syn.second` applies `Syn.gone`,
whose module's references are not recorded. The locked statement `Syn.Spec.main` and its
accepting theorem `Syn.Acc.main` stand for a claim of the full assessment.
"""

import json
from pathlib import Path

import pytest

from prooflens import compare as cmp
from prooflens import impact as im
from prooflens import uses as us


def ref(name, statement=(), value=(), kind="theorem", module="Syn.Main", owner=None):
    return {"record": "refs", "name": name, "owner": owner or name, "module": module,
            "kind": kind, "user_facing": owner is None,
            "value_kind": {"theorem": "proof", "def": "definition body"}.get(kind, "none"),
            "statement": list(statement), "value": list(value)}


RECORDS = [
    ref("Syn.main", ["Syn.Jet", "Syn.Scale"], ["Syn.step", "Syn.main._proof_1"]),
    ref("Syn.main._proof_1", ["Syn.Bound"], [], owner="Syn.main"),
    ref("Syn.step", [], ["Syn.used"]),
    ref("Syn.used", ["Syn.Jet"], []),
    ref("Syn.apart", ["Syn.Jet"], ["Syn.used"]),
    ref("Syn.Jet", [], ["Syn.Base"], kind="def"),
    ref("Syn.Base", kind="def"),
    ref("Syn.Scale", kind="def"),
    ref("Syn.Bound", kind="def"),
    ref("Syn.second", [], ["Syn.gone"], module="Syn.Second"),
    ref("Syn.Spec.main", [], ["Syn.Jet"], kind="def", module="Syn.Spec"),
    ref("Syn.Acc.main", ["Syn.Spec.main"], ["Syn.used"], module="Syn.Acc"),
]
BUILT = ["Syn.Acc", "Syn.Gone", "Syn.Main", "Syn.Second", "Syn.Spec"]

APPLICATION = {"id": "app:Syn.step:0", "callee": "Syn.used", "caller": "Syn.step",
               "available": True, "params": [],
               "premises": [{"binder": "h", "statement": "Syn.Jet 4 n", "discharge": "proved",
                             "supplied": "by Syn.jet_four"}],
               "result": {"text": "Syn.Jet 5 n"}}


def uses_doc(name, module="Syn.Main", kind="theorem", applications=()):
    return {"schema": us.SCHEMA, "name": name, "ok": True, "status": "found",
            "declaration": {"id": f"decl:{name}", "name": name, "module": module,
                            "kind": kind},
            "scope": {"libraries": ["Syn"], "modules": len(BUILT), "unbuilt": [], "failed": {}},
            "complete": True, "answer": "used", "users": [], "further": [],
            "imports_without_use": ["Syn.Other"], "applications": list(applications),
            "applications_complete": True, "applications_note": None,
            "cache": {"hit": True}}


CLAIMS = [
    ("thm:main", "theorem", "Theorem 1", {"links": [{"name": "Syn.main"}]}),
    ("lem:used", "lemma", "Lemma 2", {"links": [{"name": "Syn.used"}]}),
    ("lem:apart", "lemma", "Lemma 3", {"links": [{"name": "Syn.apart"}]}),
    ("def:jet", "definition", "Definition 4", {"links": [{"name": "Syn.Jet"}]}),
    ("thm:second", "theorem", "Theorem 5", {"links": [{"name": "Syn.second"}]}),
    ("thm:locked", "proposition", "Proposition 6",
     {"clauses": [{"name": "as printed", "spec": "Syn.Spec.main", "accept": "Syn.Acc.main"}]}),
    ("lem:none", "lemma", "Lemma 7", {}),
]


def write_site(tmp: Path) -> Path:
    data = tmp / "work" / "site" / "data"
    (data / "claims").mkdir(parents=True)
    index = []
    for key, kind, number, extra in CLAIMS:
        cid = f"S:{key}"
        ch = {"id": cid, "key": key, "paper": "S", "number": number, "kind": kind,
              "status": "linked: Lean proof checked", "status_code": "link.checked",
              "links": [], "clauses": [], "suggestions": [], **extra}
        f = f"S_{key.replace(':', '_')}.json"
        (data / "claims" / f).write_text(json.dumps(ch))
        index.append({"id": cid, "paper": "S", "number": number, "file": f,
                      "status": ch["status"]})
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "v-synthetic",
        "evidence": "e" * 64, "project": {"name": "syn", "commit": "c" * 40},
        "papers": [{"id": "S", "title": "Synthetic"}], "claims": index}))
    return data


@pytest.fixture
def lean(tmp_path, monkeypatch):
    """A synthetic project: the uses of a declaration, and the references of its modules."""
    root = tmp_path / "lean"
    for m in BUILT:
        p = root / Path(*m.split(".")).with_suffix(".lean")
        p.parent.mkdir(parents=True, exist_ok=True)
    (root / "Syn" / "Gone.lean").write_text("namespace Syn\ntheorem gone : True := trivial\n"
                                            "end Syn\n")
    state = {"records": list(RECORDS), "missing": ["Syn.Gone"], "unbuilt": [], "doc": None}

    def fake_uses(root_, name, module=None, log=None, **k):
        if state["doc"] is not None:
            return state["doc"]
        return uses_doc(name, applications=[APPLICATION] if name == "Syn.used" else [])

    def fake_refs(root_):
        return {"records": state["records"], "built": BUILT, "unbuilt": state["unbuilt"],
                "missing": state["missing"]}

    monkeypatch.setattr(us, "uses", fake_uses)
    monkeypatch.setattr(us, "reference_records", fake_refs)
    state["root"] = root
    return state


@pytest.fixture
def site(tmp_path):
    return cmp.Site(write_site(tmp_path))


def ask(site, lean, target, main=None):
    q = cmp.query(site, "impact", target, root=lean["root"], main=main)
    assert q["available"] and q["provenance"].startswith("Lean")
    (doc,) = q["results"]
    assert doc["schema"] == im.SCHEMA
    return doc


def by_name(doc):
    return {m["name"]: m for m in doc["main_results"]}


def relation(doc):
    return {c["claim"]: c["relation"] for c in doc["claims"]}


def test_a_proof_use_gives_its_path_and_the_application_at_its_end(site, lean):
    doc = ask(site, lean, "Syn.used")
    assert doc["ok"] and doc["linked_to"] == ["S:lem:used"]
    # The suggestion is shown as such: the declarations linked to the paper's theorems.
    sel = doc["selection"]
    assert sel["basis"] == "suggested" and sel["rule"] == im.SUGGESTED and "--main" in sel["edit"]
    mains = by_name(doc)
    assert list(mains) == ["Syn.main", "Syn.second"]
    m = mains["Syn.main"]
    assert m["selected"] == ["S:thm:main"] and m["claims"] == ["S:thm:main"]
    assert m["use"] == "proof" and m["direct"] is False
    assert m["answer"] == "used by its proof, through 1 other declaration"
    steps = m["paths"]["proof"]["steps"]
    assert [(s["from"], s["to"], s["refs"]) for s in steps] == [
        ("Syn.main", "Syn.step", ["proof"]), ("Syn.step", "Syn.used", ["proof"])]
    # The application at the end of the path, with how its premise is supplied.
    assert m["applications"] == ["app:Syn.step:0"]
    assert doc["applications"] == [APPLICATION]
    assert doc["imports_without_use"] == ["Syn.Other"]
    # The claims whose linked Lean uses it, and those whose Lean does not.
    assert relation(doc) == {"S:thm:main": "uses", "S:lem:used": "linked",
                             "S:lem:apart": "uses", "S:def:jet": "none",
                             "S:thm:second": "not traced", "S:thm:locked": "uses"}
    locked = next(c for c in doc["claims"] if c["claim"] == "S:thm:locked")
    assert {d["name"]: d["use"] for d in locked["declarations"]} == {
        "Syn.Spec.main": "none", "Syn.Acc.main": "proof"}
    t = im.text(doc)
    assert "Syn.main -proof-> Syn.step -proof-> Syn.used" in t
    assert "premise h : Syn.Jet 4 n  (proved in the caller: by Syn.jet_four)" in t
    assert "Claims whose Lean does not use it: Definition 4" in t


def test_an_unused_declaration_is_formalized_separately_and_an_incomplete_trace_is_not_traced(
        site, lean):
    doc = ask(site, lean, "Syn.apart")
    mains = by_name(doc)
    assert mains["Syn.main"]["use"] == "none"
    assert mains["Syn.main"]["answer"] == "formalized separately: not used by this main result"
    assert "paths" not in mains["Syn.main"]
    # `Syn.second` reaches a declaration whose module's references are not recorded: it is
    # not traced, never "not used".
    second = mains["Syn.second"]
    assert second["use"] == "not traced" and "Syn.gone" in second["answer"]
    assert "formalized separately" not in second["answer"]
    assert doc["complete"] is False and doc["scope"]["without_references"] == ["Syn.Gone"]
    assert relation(doc)["S:lem:apart"] == "linked"
    t = im.text(doc)
    assert "formalized separately: not used by this main result" in t
    assert "references not recorded: Syn.Gone" in t


def test_statement_and_proof_uses_are_kept_apart(site, lean):
    m = by_name(ask(site, lean, "Syn.Scale"))["Syn.main"]
    assert m["use"] == "statement" and list(m["paths"]) == ["statement"]
    assert m["answer"] == "in its statement only, directly: not used by its proof"
    # A lemma Lean generated for the proof is part of the proof, even through its statement.
    m = by_name(ask(site, lean, "Syn.Bound"))["Syn.main"]
    assert m["use"] == "proof" and m["direct"] is True and "statement" not in m["paths"]
    (step,) = m["paths"]["proof"]["steps"]
    assert step == {"from": "Syn.main", "to": "Syn.Bound", "refs": ["proof"],
                    "via": ["Syn.main._proof_1"]}
    # Used both ways: the proof's path and the statement's, each the shortest.
    m = by_name(ask(site, lean, "Syn.Base"))["Syn.main"]
    assert m["use"] == "proof" and set(m["paths"]) == {"proof", "statement"}
    assert m["paths"]["statement"]["length"] == 2 and m["paths"]["proof"]["length"] == 4
    assert m["answer"].endswith("; also in its statement")


def test_main_results_can_be_named_by_declaration_or_claim(site, lean):
    doc = ask(site, lean, "Syn.used", main=["lem:apart", "Syn.step", "Syn.used", "Lemma 7"])
    sel = doc["selection"]
    assert sel["basis"] == "given" and sel["unlinked_claims"] == ["S:lem:none"]
    mains = by_name(doc)
    assert list(mains) == ["Syn.apart", "Syn.step", "Syn.used"]
    assert mains["Syn.apart"]["selected"] == ["S:lem:apart"]
    assert mains["Syn.step"]["selected"] == ["named"] and mains["Syn.step"]["direct"] is True
    assert mains["Syn.used"]["use"] == "itself"
    assert "Lemma 7" not in json.dumps(doc["main_results"])
    # A name that is neither a claim nor a declaration with references is not traced.
    nothing = by_name(ask(site, lean, "Syn.used", main=["Syn.nothing"]))["Syn.nothing"]
    assert nothing["use"] == "not traced" and nothing["selected"] == ["named"]


def test_missing_records_say_not_available_or_not_traced(site, lean):
    # The uses of the declaration are not known: nothing is answered.
    lean["doc"] = {"schema": us.SCHEMA, "name": "Syn.later", "ok": False,
                   "status": "not built", "modules": ["Syn.Later"]}
    doc = ask(site, lean, "Syn.later")
    assert doc["ok"] is False and doc["reason"] == \
        "not available: its module is not built (Syn.Later)"
    assert im.text(doc) == "Syn.later: not available: its module is not built (Syn.Later)"
    lean["doc"] = None
    # No references recorded at all: every trace is "not traced", with the reason.
    lean["records"], lean["missing"] = [], list(BUILT)
    doc = ask(site, lean, "Syn.used")
    for m in doc["main_results"]:
        assert m["use"] == "not traced"
    assert by_name(doc)["Syn.main"]["answer"] == (
        "not traced: no declaration of this name has recorded references in the project's "
        "built modules")
    # A claim linked to the declaration itself still says so; no claim reads as unaffected.
    assert set(relation(doc).values()) == {"linked", "not traced"}
    assert doc["complete"] is False
    # Where the source declares it, the reason names its module.
    (lean["root"] / "Syn" / "Main.lean").write_text(
        "namespace Syn\ntheorem main : True := trivial\nend Syn\n")
    assert by_name(ask(site, lean, "Syn.used"))["Syn.main"]["answer"] == (
        "not traced: the references of its module are not recorded (Syn.Main); "
        "`machinechecked view` or `build` records them")
    # A module not built, reached on the way.
    lean["records"], lean["missing"], lean["unbuilt"] = list(RECORDS), [], ["Syn.Gone"]
    second = by_name(ask(site, lean, "Syn.apart"))["Syn.second"]
    assert second["answer"] == ("not traced: it reaches Syn.gone, and its module is not built "
                                "(Syn.Gone)")


def test_a_name_two_modules_declare_is_not_traced_through(site, lean):
    lean["records"] = RECORDS + [ref("Syn.step", [], [], module="Syn.Twin")]
    m = by_name(ask(site, lean, "Syn.used"))["Syn.main"]
    assert m["use"] == "not traced"
    assert m["answer"] == "not traced: it reaches Syn.step, and several modules declare it"


def test_the_query_needs_the_project_and_changes_nothing(site, lean, monkeypatch):
    before = {p: p.read_bytes() for p in site.data.rglob("*") if p.is_file()}
    statuses = [c["status"] for c in site.claims]
    ask(site, lean, "Syn.used")
    with pytest.raises(cmp.CompareError) as e:
        cmp.query(site, "impact", "Syn.used")
    assert e.value.kind == "no-project"
    from prooflens.simple import ViewError

    def unbuilt(*a, **k):
        raise ViewError("the Lean project is not built (run `lake build`)")

    monkeypatch.setattr(us, "uses", unbuilt)
    with pytest.raises(cmp.CompareError) as e:
        cmp.query(site, "impact", "Syn.used", root=lean["root"])
    assert e.value.kind == "no-project" and "not built" in str(e.value)
    after = {p: p.read_bytes() for p in site.data.rglob("*") if p.is_file()}
    assert before == after and [c["status"] for c in cmp.Site(site.data).claims] == statuses
    assert "impact" not in cmp.NOT_YET
