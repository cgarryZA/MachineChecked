"""The objects of a statement and what the statement says about each, by where it stands (#98):
the properties an object's type carries, the premises and conclusions that mention it, the
definitions applied to it and the results cited for it, each with its basis; a structure's
fields grouped into those it inherits and those it adds. Synthetic records in the probe's form;
no Lean is run."""

import json

import pytest

from prooflens import compare as cmp
from prooflens import objects as ob
from prooflens import workspace as wsp
from prooflens import review_cli as rc
from prooflens.targets import Snapshot


def pp(text, at, *vs):
    """A printed term with identity `at`, mentioning the variables `vs` (`(name, number)`)."""
    return {"id": at, "text": text,
            "segments": [{"t": text}] + [{"t": n, "var": v, "at": f"{at}@{v}"} for n, v in vs],
            "terms": []}


def prop(field, text, at, *vs, structure="Syn.Solution", declared_in=None, kind="proposition"):
    declared_in = declared_in or structure
    return {"field": field, "kind": kind, "basis": "type", "structure": structure,
            "declared_in": declared_in, "inherited": declared_in != structure,
            "via": [] if declared_in == structure else [f"{structure}.toBase"],
            "projection": f"{declared_in}.{field}", "term": f"s.{field}",
            "depends": [v for _, v in vs], "type": pp(text, f"{at}#{field}:/", *vs)}


def binder(op, name, var, at, ty, body, scope="given", within=(), supplies="data", **kw):
    return {"op": op, "name": name, "var": var, "id": at, "binder": "explicit",
            "supplies": supplies, "type": ty, "scope": scope, "within": list(within),
            "after": [], "args": [body], **kw}


def solution(name, var, at, d=("d", 0)):
    """The properties of a solution `name` (number `var`) over the datum `d`."""
    s = (name, var)
    vs = [x for x in (s, d) if x[1] is not None]
    return [prop("path", "Nat → Nat", at, kind="data", declared_in="Syn.Base"),
            prop("start", f"{name}.path 0 = {d[0]}", at, *vs, declared_in="Syn.Base"),
            prop("bound", "Nat", at, kind="data"),
            prop("le_bound", f"∀ n, {name}.path n ≤ {name}.bound", at, s)]


def record(tree, n_binders):
    return {"tree": tree, "binders": [{}] * n_binders, "exact": pp("…", "/")}


# ∀ (d : Nat) (s : Solution d), s.bound ≤ 5 → s.path 0 ≤ 5
SUPPLIED = record(
    binder("forall", "d", 0, "/", pp("Nat", "/0"),
           binder("forall", "s", 1, "/1", pp("Syn.Solution d", "/1/0", ("d", 0)),
                  binder("hypothesis", "h", 2, "/1/1", pp("s.bound ≤ 5", "/1/1/0", ("s", 1)),
                         {"leaf": pp("s.path 0 ≤ 5", "/1/1/1", ("s", 1))},
                         supplies="proposition"),
                  properties=solution("s", 1, "/1"))), 3)

# (∀ d, Admissible d → ∃ s : Solution d, Good s) → ∃ s : Solution 0, Good s
ASSUMED = record(
    binder("hypothesis", "h", 0, "/", pp("∀ d, Syn.Admissible d → ∃ s, Syn.Good s", "/0"),
           binder("exists", "s", 1, "/1/1", pp("Syn.Solution 0", "/1/1/0"),
                  {"leaf": {**pp("Syn.Good s", "/1/1/1", ("s", 1)),
                            "expansions": [{"at": "/1/1/1", "id": "/1/1/1=",
                                            "name": "Syn.Good", "key": "k" * 24}]}},
                  scope="produced", properties=solution("s", 1, "/1/1", d=("0", None))),
           supplies="proposition",
           logic=binder("forall", "d", 2, "/0", pp("Nat", "/0/0"),
                        {"op": "implies", "id": "/0/1", "args": [
                            {"leaf": pp("Syn.Admissible d", "/0/1/0", ("d", 2))},
                            binder("exists", "s", 3, "/0/1/1/1",
                                   pp("Syn.Solution d", "/0/1/1/1/0", ("d", 2)),
                                   {"leaf": pp("Syn.Good s", "/0/1/1/1/1", ("s", 3))},
                                   scope="assumed", within=("assume", "then"),
                                   properties=solution("s", 3, "/0/1/1/1", d=("d", 2)))]},
                        scope="assumed", within=("assume",))), 2)

# ∀ d, Admissible d → ∃ s : Solution d, Good s
PRODUCED = record(
    binder("forall", "d", 0, "/", pp("Nat", "/0"),
           binder("hypothesis", "h1", 1, "/1", pp("Syn.Admissible d", "/1/0", ("d", 0)),
                  binder("exists", "s", 2, "/1/1/1", pp("Syn.Solution d", "/1/1/1/0", ("d", 0)),
                         {"leaf": pp("Syn.Good s", "/1/1/1/1", ("s", 2))},
                         scope="produced", properties=solution("s", 2, "/1/1/1")),
                  supplies="proposition")), 3)

# ¬ ∃ s : Solution 0, s.bound < 0
DENIED = record({"op": "not", "id": "/", "args": [
    binder("exists", "s", 0, "/1", pp("Syn.Solution 0", "/1/0"),
           {"leaf": pp("s.bound < 0", "/1/1", ("s", 0))}, scope="denied", within=("not",),
           properties=solution("s", 0, "/1", d=("0", None)))]}, 0)


def test_the_three_forms_keep_their_objects_where_they_stand():
    [d, s] = ob.objects(SUPPLIED, "Syn.supplied")
    assert (s["name"], s["position"], s["type"]) == ("s", "given", "Syn.Solution d")
    assert "part of that input" in s["reading"]
    # Its fields (one inherited) are included in its type; the extra hypothesis stays an
    # explicit premise of its own, and the conclusion is what is established of it.
    assert [(p["basis"], p.get("field"), p["statement"]) for p in s["properties"]] == [
        ("type", "start", "s.path 0 = d"), ("type", "le_bound", "∀ n, s.path n ≤ s.bound"),
        ("premise", None, "s.bound ≤ 5"), ("conclusion", None, "s.path 0 ≤ 5")]
    start = s["properties"][0]
    assert (start["declared_in"], start["inherited"], start["via"], start["id"]) == \
        ("Syn.Base", True, ["Syn.Solution.toBase"], "/1#start:/")
    assert s["properties"][2]["hypothesis"] == "h"
    assert [x["field"] for x in s["data"]] == ["path", "bound"]
    assert d["properties"] == [] and d["instances"] == []

    # An assumed existence: the inner solution and its properties stay inside the assumption;
    # the solution of the conclusion is produced, with its conclusion and the definition it
    # unfolds by.
    objs = {o["var"]: o for o in ob.objects(ASSUMED, "Syn.assumed")}
    inner, outer, dd = objs[3], objs[1], objs[2]
    assert (inner["position"], dd["position"]) == ("assumed", "assumed")
    assert "inside an assumption" in inner["reading"] and inner["reading"].startswith("A witness")
    assert dd["reading"].startswith("Bound inside an assumption")
    assert [(p["basis"], p["statement"]) for p in inner["properties"] if p["basis"] != "type"] \
        == [("premise", "Syn.Good s")]
    assert [p["basis"] for p in dd["properties"]] == ["premise"]
    assert outer["position"] == "produced" and "establishes" in outer["reading"]
    assert [(p["basis"], p.get("definition")) for p in outer["properties"]
            if p["basis"] != "type"] == [("conclusion", None), ("definition", "Syn.Good")]
    assert outer["properties"][-1]["key"] == "k" * 24
    assert outer["properties"][0]["statement"] == "s.path 0 = 0"

    # An established existence: the solution is produced under the condition on d, which is a
    # premise of d, not of s.
    objs = {o["name"]: o for o in ob.objects(PRODUCED, "Syn.produced")}
    assert objs["s"]["position"] == "produced"
    assert [p["basis"] for p in objs["s"]["properties"]] == ["type", "type", "conclusion"]
    assert [(p["basis"], p["hypothesis"]) for p in objs["d"]["properties"]] == \
        [("premise", "h1")]

    # Inside a negation the solution is the negated claim's.
    [s] = ob.objects(DENIED, "Syn.none")
    assert s["position"] == "denied" and "no such object" in s["reading"]
    assert {p["basis"] for p in s["properties"]} <= set(ob.BASES)


def test_a_cited_derivation_stays_with_its_own_object():
    """Two objects of one type, and two of one printed name: a derivation names its object by
    declaration, number and binder identity, so neither of the others inherits it."""
    two = record(binder("forall", "s", 0, "/", pp("Syn.Solution 0", "/0"),
                        binder("forall", "t", 1, "/1", pp("Syn.Solution 0", "/1/0"),
                               {"leaf": pp("s.path 0 = t.path 0", "/1/1", ("s", 0), ("t", 1))},
                               properties=solution("t", 1, "/1", d=("0", None))),
                        properties=solution("s", 0, "/", d=("0", None))), 2)
    twin = record({"op": "and", "id": "/", "args": [
        binder("exists", "x", 0, "/1/1", pp("Nat", "/1/1/0"),
               {"leaf": pp("x = 1", "/1/1/1", ("x", 0))}, scope="produced"),
        binder("exists", "x", 1, "/1/1", pp("Nat", "/1/1/0"),
               {"leaf": pp("x = 2", "/2/1/1", ("x", 1))}, scope="produced")]}, 0)
    twin["tree"]["args"][1]["id"] = "/2/1"
    cite = {"object": {"decl": "Syn.two", "var": 0, "id": "/"}, "ref": {"decl": "Syn.rec"},
            "statement": "s.path 1 = s.path 0", "evidence": "e-1", "by": "human:A"}
    objs = ob.objects(two, "Syn.two", [cite])
    theorem = {o["name"]: [p for p in o["properties"] if p["basis"] == "theorem"] for o in objs}
    assert [p["ref"] for p in theorem["s"]] == [{"decl": "Syn.rec"}] and theorem["t"] == []
    assert theorem["s"][0]["evidence"] == "e-1"
    # Another declaration's variable 0, or a binder that is no longer the one cited, has none.
    assert all(p["basis"] != "theorem" for o in ob.objects(two, "Syn.other", [cite])
               for p in o["properties"])
    moved = {**cite, "object": {**cite["object"], "id": "/1"}}
    assert all(p["basis"] != "theorem" for o in ob.objects(two, "Syn.two", [moved])
               for p in o["properties"])
    on_x = {**cite, "object": {"decl": "Syn.twin", "var": 1, "id": "/2/1"}}
    xs = ob.objects(twin, "Syn.twin", [on_x])
    assert [[p["basis"] for p in o["properties"]] for o in xs] == \
        [["conclusion"], ["conclusion", "theorem"]]


def test_a_measure_space_is_supplied_structure_and_a_probability_an_assumption():
    """`[MeasureData Ω]` supplies structure on Ω, an object with laws of its own; that Ω is a
    probability space is an additional assumption, whose field is what it states."""
    measure = [prop("measure", "(Ω → Prop) → Nat", "/1", ("Ω", 0),
                    structure="Syn.MeasureData", kind="data"),
               prop("measure_empty", "measure ∅ = 0", "/1", ("Ω", 0),
                    structure="Syn.MeasureData")]
    prob = [{**prop("measure_univ", "measure univ = 1", "/1/1", ("Ω", 0),
                    structure="Syn.IsProbability"), "basis": "premise"}]
    rec = record(binder("forall", "Ω", 0, "/", pp("Type", "/0"),
                        {**binder("instance", "inst", 1, "/1", pp("Syn.MeasureData Ω", "/1/0",
                                                                    ("Ω", 0)),
                                  {**binder("instance", "h1", 2, "/1/1",
                                            pp("Syn.IsProbability Ω", "/1/1/0", ("Ω", 0)),
                                            {"leaf": pp("measure univ = 1", "/1/1/1", ("Ω", 0))},
                                            supplies="proposition"), "properties": prob},
                                  properties=measure)}), 3)
    omega, inst = ob.objects(rec, "Syn.probability")
    assert [i["type"] for i in omega["instances"]] == ["Syn.MeasureData Ω"]
    [premise, concl] = omega["properties"]
    assert (premise["basis"], premise["statement"], premise["hypothesis"]) == \
        ("premise", "Syn.IsProbability Ω", "h1")
    assert [(x["basis"], x["field"]) for x in premise["states"]] == [("premise", "measure_univ")]
    assert concl["basis"] == "conclusion"
    assert (inst["op"], inst["position"]) == ("instance", "given")
    assert [(p["basis"], p["field"]) for p in inst["properties"]] == [("type", "measure_empty")]
    assert [x["field"] for x in inst["data"]] == ["measure"]
    text = "\n".join(ob.object_lines([omega, inst]))
    assert "structure on it      [Syn.MeasureData Ω]" in text
    assert "object [Syn.MeasureData Ω]  (given)" in text and "which states" in text


def field(name, kind, declared_in, text, via=()):
    return {"field": name, "kind": kind, "basis": "type", "declared_in": declared_in,
            "inherited": bool(via), "via": list(via), "projection": f"{declared_in}.{name}",
            "type": pp(text, f"self#{name}:/", ("self", 0))}


def test_a_structure_shows_what_it_adds_to_its_parent():
    concrete = {"name": "Syn.Concrete", "kind": "inductive", "structure": {
        "class": False, "params": [], "fields_omitted": 0,
        "parents": [{"structure": "Syn.Profile", "projection": "Syn.Concrete.toProfile",
                     "subobject": True}],
        "fields": [field("f", "data", "Syn.Profile", "Nat → Nat", ["Syn.Concrete.toProfile"]),
                   field("bound", "proposition", "Syn.Profile", "∀ n, self.f n ≤ 1",
                         ["Syn.Concrete.toProfile"]),
                   field("N", "data", "Syn.Concrete", "Nat"),
                   field("support", "proposition", "Syn.Concrete",
                         "∀ n, self.N ≤ n → self.f n = 0")]}}
    v = ob.structure_view(concrete)
    assert v["declares"] == ["N", "support"]
    assert v["inherits"] == [{"parent": "Syn.Profile", "fields": ["f", "bound"]}]
    lines = ob.structure_lines(concrete)
    assert lines[0].startswith("  inherits from Syn.Profile: f : Nat → Nat (data); bound")
    assert lines[1] == "  adds: N : Nat (data); support : ∀ n, self.N ≤ n → self.f n = 0"
    # A diamond: the shared parent's fields come through the first parent, once; the second
    # parent's own fields are copied, and come from it.
    both = {"name": "Syn.Both", "structure": {"parents": [
        {"structure": "Syn.Left", "projection": "Syn.Both.toLeft", "subobject": True},
        {"structure": "Syn.Right", "projection": "Syn.Both.toRight", "subobject": False}],
        "fields": [field("pos", "proposition", "Syn.Anchor", "0 < self.x0",
                         ["Syn.Both.toLeft", "Syn.Left.toAnchor"]),
                   field("r_le", "proposition", "Syn.Right", "self.r ≤ self.x0",
                         ["Syn.Both.toRight"])]}}
    assert ob.structure_view(both)["inherits"] == [
        {"parent": "Syn.Left", "fields": ["pos"]}, {"parent": "Syn.Right", "fields": ["r_le"]}]
    # A construction's value carries the propositions its definition establishes.
    build = {"name": "Syn.build", "kind": "def", "result_properties": [
        {**field("support", "proposition", "Syn.Concrete", "∀ n, (build N).N ≤ n → 0 = 0"),
         "basis": "definition"}]}
    assert ob.structure_lines(build) == [
        "  its value carries, established by this definition: support : ∀ n, (build N).N ≤ n "
        "→ 0 = 0"]
    out = cmp._made_of({**concrete, "structure_error": None})
    assert out["structure"]["declares"] == ["N", "support"]
    assert cmp._made_of(build)["result_properties"][0]["basis"] == "definition"


def test_packets_attach_properties_to_their_objects():
    decls = cmp._with_objects([{"name": "Syn.supplied", "statement": cmp._statement(SUPPLIED)}])
    objs = decls[0]["statement"]["objects"]
    assert [o["name"] for o in objs] == ["d", "s"]
    text = "\n".join(cmp.statement_lines({**decls[0], "statement": {
        **decls[0]["statement"], "binders": []}}))
    assert "object s : Syn.Solution d  (given)" in text
    assert "in its type          s.path 0 = d   [field start of Syn.Solution, from Syn.Base]" \
        in text
    assert "assumed              s.bound ≤ 5   [h]" in text
    text = "\n".join(ob.object_lines(ob.objects(ASSUMED, "Syn.assumed")))
    assert "established with it  s.path 0 = 0" in text and "by definition" in text


def _site(tmp_path):
    """A synthetic build whose claim links `Syn.two`, a statement about two solutions."""
    data = tmp_path / "work" / "site" / "data"
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    st = record(binder("forall", "s", 0, "/", pp("Syn.Solution 0", "/0"),
                       binder("forall", "t", 1, "/1", pp("Syn.Solution 0", "/1/0"),
                              {"leaf": pp("s.path 0 = t.path 0", "/1/1", ("s", 0), ("t", 1))},
                              properties=solution("t", 1, "/1", d=("0", None))),
                       properties=solution("s", 0, "/", d=("0", None))), 2)
    st["binders"] = [{"id": "/", "name": "s", "role": "forall", "supplies": "data",
                      "type": pp("Syn.Solution 0", "/0")},
                     {"id": "/1", "name": "t", "role": "forall", "supplies": "data",
                      "type": pp("Syn.Solution 0", "/1/0")}]
    st["conclusion"] = pp("s.path 0 = t.path 0", "/1/1")
    ch = {"id": "S:thm:two", "key": "thm:two", "paper": "S", "number": "Theorem 1",
          "kind": "theorem", "source_sha256": "sha", "statement_tex": "Two solutions agree.",
          "anchor": {"kind": "exact", "file": "main.tex", "line": 1},
          "links": [{"name": "Syn.two", "kind": "theorem", "fingerprint": "fp-two",
                     "statement": st}],
          "suggestions": [], "clauses": [], "decls": {}}
    (data / "claims" / "S_thm_two.json").write_text(json.dumps(ch))
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "v-1",
        "project": {"name": "syn", "commit": "c" * 40},
        "papers": [{"id": "S", "title": "Synthetic", "revision": "c" * 40}],
        "claims": [{"id": "S:thm:two", "paper": "S", "number": "Theorem 1", "kind": "theorem",
                    "file": "S_thm_two.json"}]}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Syn.Basic"} for n in ("Syn.two", "Syn.rec")]))
    return data


def test_a_workspace_cites_a_result_for_one_object(tmp_path):
    """Evidence that names an object is pinned to that object's binder; the informed packet
    lists it with that object only, and the comparison stage does not show it."""
    data = _site(tmp_path)
    work = data.parent.parent
    snap = Snapshot(data)
    who = rc.parse_reviewer("human:A-Auditor")
    p = wsp.open_for(work, who, "informed", sources=snap.sources())
    put = lambda rec: {"op": "put", "record": rec}
    wsp.update(p, [put({"id": "e-s", "kind": "evidence", "claim": "thm:two",
                        "ref": {"decl": "Syn.rec"}, "role": "supports",
                        "object": {"decl": "Syn.two", "var": "s"}})], snap, None, who["id"])
    ws = wsp.read(p)
    rec = ws["records"]["e-s"]
    assert rec["object"] == {"decl": "Syn.two", "var": 0, "id": "/", "name": "s",
                             "type": "Syn.Solution 0"}
    # Names that do not pick one object are refused, with the objects listed.
    for bad, why in (({"decl": "Syn.two", "var": "u"}, "no object"),
                     ({"decl": "Syn.two", "var": 7}, "no object number 7"),
                     ({"decl": "Syn.nope", "var": 0}, "holds no statement")):
        with pytest.raises(wsp.WorkspaceError, match=why):
            wsp.update(p, [put({"kind": "evidence", "claim": "thm:two", "role": "supports",
                                "ref": {"decl": "Syn.rec"}, "object": bad})], snap, None,
                       who["id"])
    v = wsp.view(wsp.read(p), snap, "S:thm:two")
    derived = ob.derivations(v["claims"]["S:thm:two"]["evidence"])
    assert [(d["object"]["var"], d["evidence"]) for d in derived] == [(0, "e-s")]
    site = cmp.Site(data)
    pk = cmp.claim_packet(site, "thm:two", "informed", reading={"derivations": derived})
    objs = {o["name"]: o for o in pk["lean"]["declarations"][0]["statement"]["objects"]}
    assert [p["ref"]["decl"] for p in objs["s"]["properties"] if p["basis"] == "theorem"] == \
        ["Syn.rec"]
    assert not [p for p in objs["t"]["properties"] if p["basis"] == "theorem"]
    assert pk["interpretations"]["derivations"] == derived
    pk = cmp.claim_packet(site, "thm:two", "compare", reading={"derivations": derived})
    assert all(p["basis"] != "theorem" for o in pk["lean"]["declarations"][0]["statement"]
               ["objects"] for p in o["properties"])
    assert "#98" not in {u["owner"] for u in pk["retrieval"]["unavailable"]}
