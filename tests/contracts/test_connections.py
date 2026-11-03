"""Connections between objects of different Lean results (#146, #505): saved as workspace
evidence with their exact relation, scope, conditions and support, refused when the support is a
shared type or dependency or when two separate witnesses are joined without evidence, cited by a
composition's identifications (a partial equality used outright leaves its obligation open),
stale on their own pins, shown with the comparison at the informed stage only, and published.
A small synthetic build of Mathlib-free analysis-style declarations stands in for site data, so
these tests run no Lean."""

import json
import shutil

import pytest

from prooflens import compare as cmp
from prooflens import composition as cp
from prooflens import connections as cn
from prooflens import published_work as pw
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.schemas import validate
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
CLOSED = Publish(pdf=False, source_text=False, lean=False, reviews=False)
CLAIM = "P:thm:main"

# What each declaration of the synthetic project is.
KINDS = {"Syn.exists_p": "theorem", "Syn.exists_q": "theorem", "Syn.exists_pq": "theorem",
         "Syn.p_q_unique": "theorem", "Syn.common_step": "theorem", "Syn.P": "def",
         "Syn.Q": "def", "Syn.Profile": "inductive", "Syn.u": "def", "Syn.v": "def",
         "Syn.u_eq_v_on": "theorem", "Syn.regular_v": "theorem", "Syn.f": "def", "Syn.g": "def",
         "Syn.f_ae_g": "theorem", "Syn.f_eq_g": "theorem", "Syn.prepare": "def",
         "Syn.correct": "theorem", "Syn.cut": "def", "Syn.main": "theorem"}


def pp(text, at, *vs):
    """A printed term with identity `at`, mentioning the variables `vs` (`(name, number)`)."""
    return {"id": at, "text": text,
            "segments": [{"t": text}] + [{"t": n, "var": v, "at": f"{at}@{v}"} for n, v in vs],
            "terms": []}


def exists(name, at, ty, body_text, body_at):
    """`∃ name : ty, body`: one witness, numbered 0, with the binder identity `at`."""
    return {"tree": {"op": "exists", "name": name, "var": 0, "id": at, "binder": "explicit",
                     "supplies": "data", "type": pp(ty, at + "0"), "scope": "produced",
                     "within": [], "after": [],
                     "args": [{"leaf": pp(body_text, body_at, (name, 0))}]},
            "binders": [], "exact": pp("…", "/"), "closure": ["Syn.P", "Syn.Q",
                                                              "Syn.common_step"]}


def given(name, at, ty, body_text, body_at):
    """`∀ name : ty, body`, its variable numbered 0."""
    return {"tree": {"op": "forall", "name": name, "var": 0, "id": at, "binder": "explicit",
                     "supplies": "data", "type": pp(ty, at + "0"), "scope": None,
                     "within": [], "after": [],
                     "args": [{"leaf": pp(body_text, body_at, (name, 0))}]},
            "binders": [{"name": name, "role": "forall", "type": pp(ty, at + "0"),
                         "id": at}],
            "exact": pp("…", "/"), "closure": []}


def make_build(work, *, witnesses=("x", "y"), fp=None, pq_id="/", cut_at="/1",
               release="v-1"):
    """Site data for a synthetic paper with one theorem whose Lean is linked to existence
    results, an equality on a domain, a classes equality and a corrected profile. `witnesses`
    names the witnesses of the two separate existence results; `fp` overrides fingerprints;
    `pq_id` is the binder identity of the joint existence result's witness, `cut_at` the
    identity of the sub-term of `Syn.correct` that is the cut-off."""
    fps = {n: f"fp:{n}-1" for n in KINDS} | (fp or {})
    data = work / "site" / "data"
    statements = {
        "Syn.exists_p": exists(witnesses[0], "/", "Nat", f"Syn.P {witnesses[0]}", "/1"),
        "Syn.exists_q": exists(witnesses[1], "/", "Nat", f"Syn.Q {witnesses[1]}", "/1"),
        "Syn.exists_pq": exists("x", pq_id, "Nat", "Syn.P x ∧ Syn.Q x", "/1"),
        "Syn.correct": given("W", "/", "Syn.Profile", "Syn.cut W ≤ 1", cut_at),
    }
    links = [{"name": n, "fingerprint": fps[n], "statement": st}
             for n, st in statements.items()]
    chunk = {"id": CLAIM, "paper": "P", "number": "Theorem 1", "kind": "theorem",
             "key": "thm:main", "source_sha256": "s-main", "links": links, "suggestions": [],
             "clauses": [], "decls": {}}
    (data / "claims").mkdir(parents=True, exist_ok=True)
    (data / "decls").mkdir(parents=True, exist_ok=True)
    (data / "claims" / "thm_main.json").write_text(json.dumps(chunk))
    for i, (n, kind) in enumerate(sorted(KINDS.items())):
        (data / "decls" / f"{i:024x}.json").write_text(json.dumps(
            {"name": n, "fingerprint": fps[n], "kind": kind, "uses": []}))
    index = {"schema": "prooflens/manifest@1", "release": release,
             "project": {"name": "syn", "commit": "abc123"},
             "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123",
                         "pdf_sha256": "pdf-1"}],
             "claims": [{"id": CLAIM, "paper": "P", "number": "Theorem 1", "kind": "theorem",
                         "file": "thm_main.json"}]}
    (data / "index.json").write_text(json.dumps(index))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": k, "module": "Syn.Basic"} for n, k in KINDS.items()]))
    return Snapshot(data)


def put(rec, base=None, repin=False):
    return {"op": "put", "record": {**rec, **({"repin": True} if repin else {})},
            **({"base_rev": base} if base is not None else {})}


def evidence(eid, connection, role="supports", **kw):
    return {"id": eid, "kind": "evidence", "claim": CLAIM, "role": role,
            "ref": {"connection": connection}, **kw}


def setup(tmp_path, **kw):
    work = tmp_path / ".machinechecked"
    snap = make_build(work, **kw)
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    return work, snap, p


# The connections of these tests.
ON_DOMAIN = {"from": {"decl": "Syn.u"}, "to": {"decl": "Syn.v"}, "relation": "equal on a domain",
             "domain": "the interval [0, T]", "conditions": ["T > 0"],
             "support": [{"decl": "Syn.u_eq_v_on"}]}
ONE_WITNESS = {"from": {"decl": "Syn.exists_pq", "var": 0},
               "to": {"decl": "Syn.exists_pq", "var": "x"}, "relation": "shared witness"}
CLASSES = {"from": {"decl": "Syn.f"}, "to": {"decl": "Syn.g"}, "relation": "equal as classes",
           "modulo": "equality almost everywhere for the measure μ",
           "support": [{"decl": "Syn.f_ae_g"}]}
PROJECTION = {"from": {"decl": "Syn.prepare"}, "to": {"decl": "Syn.correct", "var": "W"},
              "relation": "projection", "field": "Syn.Profile.W"}
SEPARATE = {"from": {"decl": "Syn.exists_p", "var": 0}, "to": {"decl": "Syn.exists_q", "var": 0},
            "relation": "shared witness"}


def test_a_connection_records_its_exact_relation_scope_conditions_and_support(tmp_path):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(evidence("e-dom", ON_DOMAIN, note="u and v agree on the horizon")),
                   put(evidence("e-one", ONE_WITNESS)),
                   put(evidence("e-proj", PROJECTION))], snap)
    recs = wsp.read(p)["records"]
    c = recs["e-dom"]["ref"]["connection"]
    assert (c["relation"], c["domain"], c["conditions"]) == \
        ("equal on a domain", "the interval [0, T]", ["T > 0"])
    # Each end and each support is pinned to the version the build shows.
    assert (c["from"]["decl"], c["from"]["fingerprint"]) == ("Syn.u", "fp:Syn.u-1")
    assert c["support"][0]["decl"] == "Syn.u_eq_v_on" and c["support"][0]["digest"]
    # An end at a variable is pinned to its binder's identity, name and type: by number or name.
    w = recs["e-one"]["ref"]["connection"]
    assert w["from"] == w["to"] | {} and \
        {k: w["to"][k] for k in ("var", "id", "name", "type", "op")} == \
        {"var": 0, "id": "/", "name": "x", "type": "Nat", "op": "exists"}
    assert recs["e-proj"]["ref"]["connection"]["to"]["name"] == "W"
    assert wsp.ref_text(recs["e-dom"]["ref"]) == \
        "Syn.u and Syn.v are equal on the interval [0, T], when T > 0, by Syn.u_eq_v_on"
    assert wsp.ref_text(recs["e-proj"]["ref"]) == \
        "W of Syn.correct is the field Syn.Profile.W of Syn.prepare"
    v = wsp.view(wsp.read(p), snap)
    ev = {e["id"]: e for e in v["claims"][CLAIM]["evidence"]}
    assert {k: e["currency"]["state"] for k, e in ev.items()} == \
        {"e-dom": "current", "e-one": "current", "e-proj": "current"}


@pytest.mark.parametrize("connection, why", [
    # A shared type or a shared dependency is not support.
    ({**ON_DOMAIN, "support": [{"type": "Syn.Profile"}]}, "a shared type is not evidence"),
    ({**ON_DOMAIN, "support": [{"dependency": "Syn.P"}]}, "a shared dependency is not"),
    ({**ON_DOMAIN, "support": [{"decl": "Syn.Profile"}]}, "Syn.Profile is a type"),
    ({**ON_DOMAIN, "support": [{"decl": "Syn.P"}]}, "Syn.P is a definition"),
    ({**SEPARATE, "support": [{"decl": "Syn.common_step"}]}, "statements of both ends use"),
    ({**ON_DOMAIN, "support": [{"paper": {"claim": CLAIM, "quote": "u = v"}}]},
     "rests on Lean results"),
    # Each relation states its scope, and rests on a result that states it.
    ({**ON_DOMAIN, "domain": None}, r"states the domain it holds on \(`domain`\)"),
    ({**CLASSES, "modulo": ""}, "the equivalence the classes are taken modulo"),
    ({**ON_DOMAIN, "support": []}, "rests on a result that states it"),
    ({**ON_DOMAIN, "relation": "equal"}, "`domain` belongs to a connection that is"),
    ({**PROJECTION, "field": None}, "the field or constructor argument"),
    ({"from": {"decl": "Syn.u"}, "to": {"decl": "Syn.v"}, "relation": "transformation",
      "support": [{"decl": "Syn.u_eq_v_on"}]}, "the property the transformation preserves"),
    ({"from": {"decl": "Syn.u"}, "to": {"decl": "Syn.v"}, "relation": "definitional"},
     "names the definitions that unfold"),
    ({"from": {"decl": "Syn.u"}, "to": {"decl": "Syn.v"}, "relation": "definitional",
      "unfolds": ["Syn.u_eq_v_on"]}, "Syn.u_eq_v_on is a theorem"),
    ({**ON_DOMAIN, "relation": "sameish"}, "relation 'sameish' is not one of"),
    # Ends name objects of Lean results, by identity.
    ({**ONE_WITNESS, "to": {"decl": "Syn.exists_pq", "var": 3}}, "no object number 3"),
    ({**ONE_WITNESS, "to": {"decl": "Syn.exists_pq", "var": 0, "id": "/9"}},
     "no binder '/9' in this build"),
    ({**ONE_WITNESS, "to": {"decl": "Syn.u", "var": 0}}, "holds no statement of Syn.u"),
    ({**ONE_WITNESS, "to": {"decl": "Syn.correct", "at": "/7"}}, "no sub-term"),
    ({**ONE_WITNESS, "to": {"decl": "Syn.correct", "var": "W"}},
     "W of Syn.correct is not the witness"),
    ({**ONE_WITNESS, "to": {"decl": "Syn.exists_q"}}, "name each by its variable"),
    ({**ONE_WITNESS, "to": {"name": "x"}}, "is an object of a Lean result"),
])
def test_a_connection_is_refused_without_evidence_of_its_relation(tmp_path, connection, why):
    work, snap, p = setup(tmp_path)
    before = p.read_bytes()
    with pytest.raises(wsp.WorkspaceError, match=why):
        wsp.update(p, [put(evidence("e-bad", connection))], snap)
    assert p.read_bytes() == before


@pytest.mark.parametrize("names", [("x", "y"), ("x", "x")])
def test_separate_existence_results_keep_separate_witnesses(tmp_path, names):
    """#146 A2: `∃ x, P x` and `∃ y, Q y` leave the obligation for `∃ z, P z ∧ Q z` open, and
    naming both witnesses `x` changes nothing."""
    work, snap, p = setup(tmp_path, witnesses=names)
    # Neither result itself, nor a result both statements use, relates the two witnesses.
    for support in ([], [{"decl": "Syn.exists_p"}], [{"decl": "Syn.exists_q"}],
                    [{"decl": "Syn.exists_p"}, {"decl": "Syn.exists_q"}]):
        with pytest.raises(wsp.WorkspaceError, match="witnesses of separate choices"):
            wsp.update(p, [put(evidence("e-sep", {**SEPARATE, "support": support}))], snap)
    # The ends stay two binders of two declarations, whatever they are called.
    with pytest.raises(wsp.WorkspaceError) as e:
        wsp.update(p, [put(evidence("e-sep", SEPARATE))], snap)
    assert f"{names[0]} of Syn.exists_p and {names[1]} of Syn.exists_q" in str(e.value)
    assert not cn.same_binder({"decl": "Syn.exists_p", "var": 0, "id": "/", "name": "x"},
                              {"decl": "Syn.exists_q", "var": 0, "id": "/", "name": "x"})
    # A composition that combines them keeps its compatible-witnesses obligation open: nothing
    # can discharge it as a connection, so full coverage stays refused.
    wsp.update(p, [
        put({"id": "q1", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
             "form": "there is", "binds": ["z"], "text": "some z with P z and Q z"}),
        put({"id": "e-p", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Syn.exists_p"}}),
        put({"id": "e-q", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Syn.exists_q"}})], snap)
    comp = {"id": "c-sep", "kind": "composition", "claim": CLAIM, "steps": [
        {"id": "s1", "establishes": "some x with P x", "uses": ["e-p"]},
        {"id": "s2", "establishes": "some y with Q y", "uses": ["e-q"]},
        {"id": "s3", "establishes": "some z with P z and Q z", "after": ["s1", "s2"],
         "requirements": ["r1"]}],
        "obligations": [{"id": "o1", "kind": "compatible witnesses",
                         "text": "the two results may choose different witnesses"}]}
    with pytest.raises(wsp.WorkspaceError, match="o1 are open"):
        wsp.update(p, [put({**comp, "coverage": "full"})], snap)
    wsp.update(p, [put({**comp, "coverage": "partial"})], snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    assert c["gaps"]["open"] == ["o1"] and not c["complete"]
    # Evidence that relates the witnesses (a uniqueness theorem) is a connection.
    wsp.update(p, [put(evidence("e-sep", {**SEPARATE,
                                          "support": [{"decl": "Syn.p_q_unique"}]}))], snap)
    assert wsp.read(p)["records"]["e-sep"]["ref"]["connection"]["relation"] == "shared witness"


def test_one_existence_result_gives_one_witness(tmp_path):
    """#146 A3: `∃ x, P x ∧ Q x` gives two facts about one witness and supports the combined
    requirement directly."""
    work, snap, p = setup(tmp_path)
    wsp.update(p, [
        put(evidence("e-one", ONE_WITNESS)),
        put({"id": "q1", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
             "form": "there is", "binds": ["z"], "text": "some z with P z and Q z"}),
        put({"id": "e-pq", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Syn.exists_pq"}}),
        put({"id": "c-one", "kind": "composition", "claim": CLAIM, "coverage": "full",
             "steps": [{"id": "s1", "establishes": "P x for the witness x", "uses": ["e-pq"]},
                       {"id": "s2", "establishes": "Q x for that same x", "uses": ["e-pq"],
                        "requirements": ["r1"]}],
             "identifications": [{"left": {"step": "s1", "object": "x"},
                                  "right": {"step": "s2", "object": "x"},
                                  "relation": "same object", "how": "evidence",
                                  "evidence": ["e-one"]}]}),
        put({"id": "f-direct", "kind": "finding", "claim": CLAIM, "requirement": "r1",
             "coverage": "full", "basis": "direct", "evidence": ["e-pq"],
             "note": "one witness with both properties"})], snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    assert c["complete"] and not c.get("obligations")
    assert c["evidence"] == ["e-pq", "e-one"]
    assert cn.same_binder(*(wsp.read(p)["records"]["e-one"]["ref"]["connection"][s]
                            for s in ("from", "to")))


def _restricted(p, snap, relation, extra=None):
    """A composition that carries the regularity of v to u through the equality on [0, T],
    identifying them with `relation`."""
    return put({"id": "c-reg", "kind": "composition", "claim": CLAIM, "steps": [
        {"id": "s1", "establishes": "v is regular on [0, T]", "uses": ["e-reg"]},
        {"id": "s2", "establishes": "u is regular", "after": ["s1"], "requirements": ["r1"]}],
        "identifications": [{"left": {"step": "s1", "object": "v"},
                             "right": {"step": "s2", "object": "u"},
                             "relation": relation, "how": "evidence",
                             "evidence": ["e-dom"]}], **(extra or {})})


def _reg_setup(p, snap, text):
    wsp.update(p, [
        put({"id": "q1", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
             "form": "conclusion", "text": text}),
        put({"id": "e-reg", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Syn.regular_v"}}),
        put(evidence("e-dom", ON_DOMAIN))], snap)


def test_an_equality_on_a_domain_transfers_only_there(tmp_path):
    """#146 A4: an equality on a subdomain carries a regularity fact there; used globally, the
    composition shows the missing extension step."""
    work, snap, p = setup(tmp_path)
    _reg_setup(p, snap, "u is regular on [0, T]")
    # Used where it holds: a restriction, which leaves nothing open.
    wsp.update(p, [_restricted(p, snap, "restriction", {"coverage": "full"})], snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    assert c["complete"] and "obligations" not in c

    # Used to identify u and v outright: a local-to-global obligation is left open.
    rev = wsp.read(p)["records"]["c-reg"]["rev"]
    with pytest.raises(wsp.WorkspaceError, match=r"obligation\(s\) o1 are open"):
        wsp.update(p, [_restricted(p, snap, "equal", {"coverage": "full"}) | {"base_rev": rev}],
                   snap)
    wsp.update(p, [_restricted(p, snap, "equal", {"coverage": "partial"}) | {"base_rev": rev}],
               snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    o, = c["obligations"]
    assert (o["kind"], o["state"], o["connection"]) == ("local to global", "open", "e-dom")
    assert "holds only on the interval [0, T]" in o["text"]
    assert c["gaps"]["open"] == ["o1"]
    assert "(left by the connection e-dom)" in "\n".join(cp.lines(c))
    # The restricted equality itself does not discharge it; an extension step does.
    rev = wsp.read(p)["records"]["c-reg"]["rev"]
    with pytest.raises(wsp.WorkspaceError, match="does not discharge the step from there"):
        wsp.update(p, [_restricted(p, snap, "equal", {"obligations": [
            {**o, "state": "discharged", "by": {"evidence": ["e-dom"]}}]}) | {"base_rev": rev}],
            snap)
    wsp.update(p, [_restricted(p, snap, "equal", {"obligations": [
        {**o, "state": "discharged", "by": {"steps": ["s2"]}}]}) | {"base_rev": rev}], snap)
    c, = wsp.view(wsp.read(p), snap)["claims"][CLAIM]["compositions"]
    assert c["gaps"]["open"] == [] and len(c["obligations"]) == 1

    # A connection is cited by an identification; a step rests on results.
    with pytest.raises(wsp.WorkspaceError, match="a connection is cited by an identification"):
        wsp.update(p, [put({"kind": "composition", "claim": CLAIM, "steps": [
            {"id": "s1", "establishes": "u = v on [0, T]", "uses": ["e-dom"]}]})], snap)
    # An identification's relation fits the connection's.
    with pytest.raises(wsp.WorkspaceError, match="identify them as same object or equal or "
                                                 "restriction or other"):
        wsp.update(p, [put(_restricted(p, snap, "coercion")["record"] | {"id": "c-x"})], snap)


def test_equal_classes_and_equal_representatives_stay_distinct(tmp_path):
    """#146 A6: equality of classes keeps its equivalence and measure visible, and does not
    become equality of the representatives."""
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(evidence("e-cls", CLASSES)),
                   put(evidence("e-raw", {"from": {"decl": "Syn.f"}, "to": {"decl": "Syn.g"},
                                          "relation": "equal",
                                          "support": [{"decl": "Syn.f_eq_g"}]})),
                   put({"id": "e-fg", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"decl": "Syn.f_ae_g"}})], snap)
    text = wsp.ref_text(wsp.read(p)["records"]["e-cls"]["ref"])
    assert "equal as classes, modulo equality almost everywhere for the measure μ" in text
    comp = {"id": "c-cls", "kind": "composition", "claim": CLAIM, "steps": [
        {"id": "s1", "establishes": "the class of f", "uses": ["e-fg"]},
        {"id": "s2", "establishes": "the class of g", "after": ["s1"]}],
        "identifications": [{"left": {"step": "s1", "object": "f"},
                             "right": {"step": "s2", "object": "g"},
                             "relation": "equal", "how": "evidence", "evidence": ["e-cls"]}]}
    wsp.update(p, [put(comp)], snap)
    o, = wsp.read(p)["records"]["c-cls"]["obligations"]
    assert (o["kind"], o["state"], o["connection"]) == ("equality transport", "open", "e-cls")
    assert "not between their representatives" in o["text"]
    # Identified as classes only (`other`), it leaves nothing; equality of the representatives
    # is a connection of its own, resting on its own theorem.
    wsp.update(p, [put({**comp, "id": "c-other", "identifications": [
        {**comp["identifications"][0], "relation": "other"}]})], snap)
    assert "obligations" not in wsp.read(p)["records"]["c-other"]
    wsp.update(p, [put({**comp, "id": "c-raw", "identifications": [
        {**comp["identifications"][0], "evidence": ["e-raw"]}]})], snap)
    assert "obligations" not in wsp.read(p)["records"]["c-raw"]
    raw = wsp.read(p)["records"]["e-raw"]["ref"]["connection"]
    assert raw["relation"] == "equal" and "modulo" not in raw


def test_each_connection_goes_stale_alone(tmp_path):
    """#146 A7: a changed constructor argument or equality theorem makes the affected
    connection stale; the others stay current, and no end moves to a renumbered binder or
    sub-term."""
    work, snap, p = setup(tmp_path)
    cut = {"from": {"decl": "Syn.correct", "at": "/1"}, "to": {"decl": "Syn.cut"},
           "relation": "definitional", "unfolds": ["Syn.cut"]}
    wsp.update(p, [put(evidence("e-dom", ON_DOMAIN)), put(evidence("e-one", ONE_WITNESS)),
                   put(evidence("e-proj", PROJECTION)), put(evidence("e-cut", cut)),
                   put({"id": "f-dom", "kind": "finding", "claim": CLAIM, "coverage": "partial",
                        "evidence": ["e-dom"], "note": "u is v on the horizon"}),
                   {"op": "submit", "id": "f-dom", "base_rev": 1}], snap)
    deps = wsp.read(p)["records"]["f-dom"]["dependencies"]
    assert "object correspondence" in deps["kinds"]
    item, = [it for it in deps["items"] if it["dependency"] == "connection"]
    assert item["ref"]["connection"]["support"][0]["decl"] == "Syn.u_eq_v_on"

    def states(**kw):
        s = make_build(work, **kw)
        v = wsp.view(wsp.read(p), s)
        c = v["claims"][CLAIM]
        return ({e["id"]: e["currency"] for e in c["evidence"]},
                {f["id"]: f["currency"]["state"] for f in c["findings"]})

    # The equality theorem changed: that connection and the finding resting on it.
    cur, fs = states(fp={"Syn.u_eq_v_on": "fp:changed"}, release="v-2")
    assert {k: v["state"] for k, v in cur.items()} == \
        {"e-dom": "stale", "e-one": "current", "e-proj": "current", "e-cut": "current"}
    assert cur["e-dom"]["changes"][0]["reason"] == "Syn.u_eq_v_on, its support, changed"
    assert fs == {"f-dom": "stale"}
    # The prepared profile's constructor argument changed: the projection only.
    cur, _ = states(fp={"Syn.prepare": "fp:changed"}, release="v-3")
    assert [k for k, v in cur.items() if v["state"] == "stale"] == ["e-proj"]
    # A build that numbers the witness's binder otherwise: the end is not moved to it.
    cur, _ = states(pq_id="/2", release="v-4")
    assert [k for k, v in cur.items() if v["state"] == "stale"] == ["e-one"]
    ch = cur["e-one"]["changes"][0]
    assert ch["reason"] == ("Syn.exists_pq: variable 0 is now x : Nat (binder /2), not x : Nat "
                            "(binder /), the object the connection was recorded at")
    assert (ch["was"]["id"], ch["now"]["id"]) == ("/", "/2")
    # A sub-term identity that now names another expression: stale, never followed.
    cur, _ = states(cut_at="/2", release="v-5")
    assert [k for k, v in cur.items() if v["state"] == "stale"] == ["e-cut"]
    assert "the sub-term /1" in cur["e-cut"]["changes"][0]["reason"]

    # Written again without re-pinning, it keeps the pins it was recorded at; re-pinned, it
    # follows the build (and is refused where its recorded binder is gone).
    snap5 = make_build(work, fp={"Syn.u_eq_v_on": "fp:changed"}, pq_id="/2", release="v-6")
    rec = wsp.read(p)["records"]["e-dom"]
    wsp.update(p, [put({**rec, "note": "edited"}, base=rec["rev"])], snap5)
    assert wsp.read(p)["records"]["e-dom"]["ref"] == rec["ref"]
    wsp.update(p, [put({**rec, "note": "edited"}, base=rec["rev"] + 1, repin=True)], snap5)
    c = wsp.read(p)["records"]["e-dom"]["ref"]["connection"]
    assert c["support"][0]["fingerprint"] == "fp:changed"
    one = wsp.read(p)["records"]["e-one"]
    with pytest.raises(wsp.WorkspaceError, match="no binder '/' in this build"):
        wsp.update(p, [put(one, base=one["rev"], repin=True)], snap5)


def test_the_reader_and_the_comparison_carry_the_same_records_at_the_informed_stage(tmp_path):
    """#146 A8: the browser's workspace view, the informed comparison packet and `compare --query
    connections` give the same connection records; the read and compare stages give none."""
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(evidence("e-dom", ON_DOMAIN)), put(evidence("e-one", ONE_WITNESS)),
                   put({"id": "e-pq", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"decl": "Syn.exists_pq"}})], snap)
    wid = wsp.read(p)["id"]
    shown = cn.records(wsp.view(wsp.read(p), snap)["claims"][CLAIM]["evidence"])
    assert [e["id"] for e in shown] == ["e-dom", "e-one"]
    site = cmp.Site(work / "site" / "data")
    reading = cmp.workspace_reading(site, work, wid, "Theorem 1")
    informed = cmp.claim_packet(site, "Theorem 1", "informed", reading=reading)
    assert informed["interpretations"]["connections"] == shown
    assert "Connections between objects recorded in that workspace" in cmp.packet_text(informed)
    q = cmp.query(site, "connections", "Theorem 1")
    assert q["available"] and q["subject"]["contains"] == ["prior interpretations"]
    assert [{k: v for k, v in r.items() if k not in ("workspace", "reviewer", "mode")}
            for r in q["results"]] == shown
    assert {(r["workspace"], r["reviewer"]) for r in q["results"]} == {(wid, "human:A-Auditor")}
    with pytest.raises(cmp.CompareError, match="no workspace"):
        cmp.query(site, "connections", "Theorem 1", workspace="ws-000000000000")
    for stage in ("read", "compare"):
        pk = cmp.claim_packet(site, "Theorem 1", stage,
                              reading=cmp.workspace_reading(site, work, wid, "Theorem 1"))
        raw = json.dumps(pk)
        assert "interpretations" not in pk and "e-dom" not in raw and "equal on a domain" \
            not in raw, stage
        assert any(w["section"] == "interpretations" and "connections between objects" in
                   w["reason"] for w in pk["retrieval"]["withheld"])


def test_connections_are_published_with_what_cites_them(tmp_path):
    work, snap, p = setup(tmp_path)
    wsp.update(p, [put(evidence("e-dom", ON_DOMAIN)), put(evidence("e-cls", CLASSES)),
                   put(evidence("e-draft", PROJECTION)),
                   put({"id": "q1", "kind": "requirement", "claim": CLAIM, "local_id": "r1",
                        "form": "conclusion", "text": "u is regular"}),
                   put({"id": "e-reg", "kind": "evidence", "claim": CLAIM, "role": "supports",
                        "ref": {"decl": "Syn.regular_v"}}),
                   _restricted(p, snap, "equal"),
                   put({"id": "f1", "kind": "finding", "claim": CLAIM, "coverage": "partial",
                        "basis": "reviewed_composition", "composition": "c-reg",
                        "evidence": ["e-cls"], "note": "NOTE"}),
                   {"op": "submit", "id": "f1", "base_rev": 1}], snap)
    data = tmp_path / "out" / "data"
    shutil.copytree(work / "site" / "data", data)
    pw.write(data, work, lambda cid: EVERYTHING)
    body = json.loads((data / "work" / "thm_main.json").read_text())
    validate(body, "published-work")
    rd, = body["readings"]
    ev = {e["id"]: e for e in rd["evidence"]}
    # Cited by the finding or its composition: published; the uncited one stays in the workspace.
    assert set(ev) == {"e-dom", "e-cls", "e-reg"}
    c = ev["e-dom"]["ref"]["connection"]
    assert (c["relation"], c["domain"], c["conditions"], c["from"]["decl"]) == \
        ("equal on a domain", "the interval [0, T]", ["T > 0"], "Syn.u")
    assert ev["e-cls"]["ref"]["connection"]["modulo"].startswith("equality almost everywhere")
    assert ev["e-dom"]["currency"]["state"] == "current"
    o, = rd["compositions"][0]["obligations"]
    assert (o["kind"], o["connection"]) == ("local to global", "e-dom")
    items = {it["record"]: it for it in rd["findings"][0]["dependencies"]["items"]
             if it["dependency"] == "connection"}
    assert items["e-cls"]["ref"]["connection"]["modulo"] and items["e-dom"]["via"] == ["c-reg"]
    # Without the Lean, a connection keeps its relation, ends and support by identity and pins.
    rd, = pw.readings(work, snap, lambda cid: CLOSED, {CLAIM})[CLAIM]
    raw = json.dumps(rd, ensure_ascii=False)
    for word in ("[0, T]", "T > 0", "almost everywhere", "NOTE"):
        assert word not in raw, word
    ev = {e["id"]: e for e in rd["evidence"]}
    c = ev["e-dom"]["ref"]["connection"]
    assert (c["relation"], c["from"]["decl"], c["support"][0]["decl"]) == \
        ("equal on a domain", "Syn.u", "Syn.u_eq_v_on")
    validate({"schema": pw.SCHEMA, "release": "v-1", "claim": CLAIM, "readings": [rd]},
             "published-work")
