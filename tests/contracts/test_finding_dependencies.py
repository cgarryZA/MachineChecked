"""What a saved finding rests on (#143, for #120): each submitted finding records the parts it
used with their content identities (the passage, the requirements and the passages governing
them, alignments, cited declarations with the definitions their statements use and the
expansions they print, applications, facts inside proofs, compositions, bridges and
counterexamples); a later build reopens exactly the findings whose parts changed; a missing or
incomplete part is unknown, never current; and a submitted finding is never rebound to a record
edited or re-pinned after it. A small synthetic build stands in for site data, and Lean's
answers about applications and facts are given by the test, so these tests run no Lean."""

import json

import pytest

from prooflens import changes as chg
from prooflens import cli
from prooflens import dependencies as dp
from prooflens import review_cli as rc
from prooflens import uses as us
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")

# A synthetic paper: the quantifier (line 4) and the constant's dependence (line 8) stand outside
# the display (lines 5-7), which is a claim of its own.
PAPER = "\n".join([
    r"\documentclass{article}",
    r"\begin{document}",
    r"\section{Bounds}",
    r"For every $\varepsilon > 0$,",
    r"\begin{equation}\label{eq:young}",
    r"  |u| \le \varepsilon \|f\| + C/\varepsilon,",
    r"\end{equation}",
    r"with $C$ independent of $\varepsilon$.",
    r"\begin{theorem}\label{thm:main}",
    r"Every solution is bounded.",
    r"\end{theorem}",
    r"\end{document}", ""])

FPS = {"Ex.young": "fp:young-1", "Ex.main": "fp:main-1", "Ex.norm": "fp:norm-1",
       "Ex.Sol": "fp:sol-1", "Ex.helper": "fp:helper-1"}


def _term(text, tid):
    return {"text": text, "segments": [{"t": text}], "terms": [], "id": tid}


def make_build(work, fps=None, young_sha="s-young-1", paper=PAPER, young_uses=None,
               norm_key="k-norm-1"):
    """Two claims: the estimate (linked to `Ex.young`, whose statement uses `Ex.norm` and
    `Ex.Sol` and prints one expansion of `Ex.norm`) and the theorem (linked to `Ex.main`, whose
    statement uses `Ex.Sol`); and `Ex.helper`, a declaration no statement uses."""
    fps = {**FPS, **(fps or {})}
    data = work / "site" / "data"
    for d in ("claims", "decls"):
        (data / d).mkdir(parents=True, exist_ok=True)
    src = work / "sources" / "P"
    src.mkdir(parents=True, exist_ok=True)
    (src / "paper.tex").write_text(paper, encoding="utf-8")
    young = {"binders": [{"id": "/", "name": "ε", "role": "forall", "type": _term("ℝ", "/0")}],
             "conclusion": {**_term("|u| ≤ ε * Ex.norm f + C / ε", "/1"),
                            "expansions": [{"at": "/1/1", "id": "/1/1=", "name": "Ex.norm",
                                            "key": norm_key}]},
             "closure": ["Ex.norm", "Ex.Sol"] if young_uses is None else young_uses}
    main = {"binders": [], "conclusion": _term("∀ u : Ex.Sol, bounded u", "/"),
            "closure": ["Ex.Sol"]}
    claims = [
        {"id": "P:eq:young", "paper": "P", "number": "Equation (1)", "kind": "equation",
         "key": "eq:young", "source_sha256": young_sha,
         "excerpt": {"file": "paper.tex", "start_line": 5, "end_line": 7},
         "links": [{"name": "Ex.young", "fingerprint": fps["Ex.young"], "statement": young}],
         "suggestions": [], "clauses": [], "decls": {"Ex.norm": "k-norm", "Ex.Sol": "k-sol"}},
        {"id": "P:thm:main", "paper": "P", "number": "Theorem 1", "kind": "theorem",
         "key": "thm:main", "source_sha256": "s-main-1",
         "excerpt": {"file": "paper.tex", "start_line": 9, "end_line": 11},
         "links": [{"name": "Ex.main", "fingerprint": fps["Ex.main"], "statement": main}],
         "suggestions": [], "clauses": [], "decls": {"Ex.Sol": "k-sol"}},
    ]
    for c in claims:
        (data / "claims" / f"{c['key'].replace(':', '_')}.json").write_text(json.dumps(c))
    for key, name in (("k-norm", "Ex.norm"), ("k-sol", "Ex.Sol"), ("k-helper", "Ex.helper")):
        (data / "decls" / f"{key}.json").write_text(json.dumps(
            {"name": name, "fingerprint": fps[name], "kind": "def", "uses": []}))
    index = {"schema": "prooflens/manifest@1", "release": "v-1",
             "project": {"name": "ex", "commit": "abc123"},
             "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123"}],
             "claims": [{"id": c["id"], "paper": "P", "number": c["number"], "kind": c["kind"],
                         "file": f"{c['key'].replace(':', '_')}.json"} for c in claims]}
    (data / "index.json").write_text(json.dumps(index))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Ex.Basic"} for n in FPS]))
    return Snapshot(data)


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def submit(rid, base):
    return {"op": "submit", "id": rid, "base_rev": base}


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w)
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def opened(work):
    return wsp.open_for(work, WHO, "informed", sources=snap_of(work).sources())


def rec(p, rid):
    return wsp.read(p)["records"][rid]


def states(p, work, root=None):
    return {k: v["state"] for k, v in wsp.currency(wsp.read(p), snap_of(work), root).items()
            if k.startswith("f-")}


# The reading of the estimate: for every ε > 0 (line 4), there is C independent of ε (line 8),
# the bound (the display).
READING = [
    put({"id": "q-eps", "kind": "requirement", "claim": "P:eq:young", "local_id": "r1",
         "form": "for every", "binds": ["ε"], "domain": "ε > 0", "text": "for every ε > 0"}),
    put({"id": "q-c", "kind": "requirement", "claim": "P:eq:young", "local_id": "r1.1",
         "parent": "r1", "form": "there is", "binds": ["C"], "independent_of": ["ε"],
         "text": "C independent of ε"}),
    put({"id": "q-bound", "kind": "requirement", "claim": "P:eq:young", "local_id": "r1.1.1",
         "parent": "r1.1", "form": "conclusion", "text": "the bound"}),
    put({"id": "q-norm", "kind": "requirement", "claim": "P:eq:young", "local_id": "r2",
         "form": "object", "text": "the norm of f"}),
    put({"id": "p-eps", "kind": "fragment", "claim": "P:eq:young", "requirement": "r1",
         "role": "quantifier domain", "region": {"file": "paper.tex", "start_line": 4}}),
    put({"id": "p-c", "kind": "fragment", "claim": "P:eq:young", "requirement": "r1.1",
         "role": "constant dependence", "region": {"file": "paper.tex", "start_line": 8}}),
    put({"id": "p-bound", "kind": "fragment", "claim": "P:eq:young", "requirement": "r1.1.1",
         "role": "statement", "passage": {"claim": "P:eq:young"}}),
    put({"id": "a-bound", "kind": "alignment", "claim": "P:eq:young",
         "requirements": ["r1.1.1"], "lean": [{"decl": "Ex.young", "conclusion": True}]}),
    put({"id": "e-young", "kind": "evidence", "claim": "P:eq:young", "role": "supports",
         "ref": {"decl": "Ex.young"}}),
    put({"id": "e-quote", "kind": "evidence", "claim": "P:eq:young", "role": "context",
         "ref": {"paper": {"claim": "P:thm:main", "quote": "Every solution is bounded."}}}),
]


def test_a_submitted_finding_records_what_it_rests_on_with_each_version(work):
    p = opened(work)
    wsp.update(p, READING + [
        put({"id": "f-bound", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "basis": "direct", "evidence": ["e-young", "e-quote"],
             "note": "The Lean states the bound."})], snap_of(work))
    # A draft records none: what it rests on is read from its records whenever it is shown.
    assert "dependencies" not in rec(p, "f-bound")
    wsp.update(p, [submit("f-bound", 1)], snap_of(work))
    deps = rec(p, "f-bound")["dependencies"]
    assert deps["kinds"] == ["statement comparison", "object correspondence"]
    assert deps["unknown"] == [] and deps["at"]
    by = {(it["dependency"], it.get("record")): it for it in deps["items"]}
    assert by[("passage", None)] == {"dependency": "passage", "claim": "P:eq:young",
                                     "sha256": "s-young-1"}
    # The requirement it names and those it sits inside, each with its reading's digest and
    # the passages that govern it; not r2, which is beside it.
    assert [it["requirement"] for it in deps["items"] if it["dependency"] == "reading"] == \
        ["r1", "r1.1", "r1.1.1"]
    ctx = {it["record"]: it for it in deps["items"] if it["dependency"] == "context"}
    assert set(ctx) == {"p-eps", "p-c", "p-bound"}
    assert ctx["p-eps"]["region"]["start_line"] == 4 and ctx["p-eps"]["region"]["sha256"]
    assert ctx["p-bound"]["passage"] == {"claim": "P:eq:young", "sha256": "s-young-1"}
    # The object: the scoped expression of the target, with the declaration's digest and the
    # definitions its statement uses.
    (target,) = by[("object", "a-bound")]["lean"]
    assert target["conclusion"] and target["target"] == "|u| ≤ ε * Ex.norm f + C / ε"
    assert target["closure"] == {"Ex.norm": "fp:norm-1", "Ex.Sol": "fp:sol-1"}
    # The cited declaration with the definitions its statement uses and the expansion it
    # prints; the quoted passage with the version quoted.
    ref = by[("declaration", "e-young")]["ref"]
    assert (ref["decl"], ref["fingerprint"]) == ("Ex.young", "fp:young-1")
    assert ref["closure"] == {"Ex.norm": "fp:norm-1", "Ex.Sol": "fp:sol-1"}
    assert ref["expansions"] == [{"at": "/1/1", "name": "Ex.norm", "key": "k-norm-1"}]
    assert by[("paper", "e-quote")]["ref"]["paper"]["sha256"] == "s-main-1"
    # Shown, the same; and current while nothing changed.
    v = wsp.view(wsp.read(p), snap_of(work))
    (f,) = v["claims"]["P:eq:young"]["findings"]
    assert f["dependencies"] == deps and f["currency"] == {"state": "current", "changes": []}


def test_a_changed_definition_reopens_only_the_findings_whose_statements_use_it(work):
    """The theorem's name and fingerprint stay; a definition its statement uses changes: the
    evidence, the alignment and the finding that rest on it are stale, naming the definition and
    the declaration that uses it. A finding resting on another declaration stays current."""
    p = opened(work)
    wsp.update(p, READING + [
        put({"id": "e-main", "kind": "evidence", "claim": "P:thm:main", "role": "supports",
             "ref": {"decl": "Ex.main"}}),
        put({"id": "e-helper", "kind": "evidence", "claim": "P:thm:main", "role": "context",
             "ref": {"decl": "Ex.helper"}}),
        put({"id": "f-bound", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "evidence": ["e-young"], "note": "n"}),
        put({"id": "f-main", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
             "evidence": ["e-main", "e-helper"], "note": "n"})], snap_of(work))
    wsp.update(p, [submit("f-bound", 1), submit("f-main", 1)], snap_of(work))
    assert states(p, work) == {"f-bound": "current", "f-main": "current"}
    make_build(work, fps={"Ex.norm": "fp:norm-2"}, norm_key="k-norm-2")
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["e-young"]["state"] == "stale" and cur["a-bound"]["state"] == "stale"
    assert cur["e-main"]["state"] == cur["e-helper"]["state"] == "current"
    assert (cur["f-bound"]["state"], cur["f-main"]["state"]) == ("stale", "current")
    reasons = {c.get("reason") for c in cur["f-bound"]["changes"]}
    assert "Ex.norm, which the statement of Ex.young uses, changed" in reasons
    # The requirement aligned with that object is stale with it; the others are not.
    assert cur["q-bound"]["state"] == "stale" and cur["q-norm"]["state"] == "current"
    # A declaration neither statement uses changes: only the finding citing it is reopened.
    make_build(work, fps={"Ex.helper": "fp:helper-2"})
    assert states(p, work) == {"f-bound": "current", "f-main": "stale"}


def test_a_changed_governing_passage_reopens_the_findings_on_that_reading_only(work):
    p = opened(work)
    wsp.update(p, READING + [
        put({"id": "f-bound", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "note": "n"}),
        put({"id": "f-norm", "kind": "finding", "claim": "P:eq:young", "requirement": "r2",
             "coverage": "full", "note": "n"}),
        put({"id": "f-whole", "kind": "finding", "claim": "P:eq:young", "coverage": "partial",
             "note": "n"})], snap_of(work))
    wsp.update(p, [submit("f-bound", 1), submit("f-norm", 1), submit("f-whole", 1)],
               snap_of(work))
    # Line 8 restricts the constant; the display, and so the claim's own pin, are unchanged. The
    # finding on the bound sits inside that constant's requirement and is reopened; the one on
    # another requirement, and the one on the whole claim, whose evidence does not rest on that
    # passage, are not.
    make_build(work, paper=PAPER.replace("independent of", "depending on"))
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert {k: cur[k]["state"] for k in ("f-bound", "f-norm", "f-whole")} == {
        "f-bound": "stale", "f-norm": "current", "f-whole": "current"}
    (ch,) = [c for c in cur["f-bound"]["changes"] if c.get("region")]
    assert ch["region"] == "paper.tex:8" and ch["lines"] == [8]


def test_a_proof_edit_reopens_findings_on_its_facts_and_keeps_statement_comparisons(
        work, tmp_path, monkeypatch):
    """The enclosing theorem's statement is unchanged; a fact inside its proof and an
    application in it change. The finding resting on the fact, and the one resting on the
    composition that uses the application, are stale; the statement comparison stays current,
    and so does a finding on another requirement."""
    from prooflens import proof_facts as pf
    app = {"id": "app:Ex.young:0", "callee": "Ex.norm_le", "caller": "Ex.young",
           "available": True, "params": [{"binder": "x", "argument": "f"}], "result": "‖f‖ ≤ 1"}
    lean = {"proof": "b" * 16, "app": app}
    monkeypatch.setattr(pf, "extract", lambda root, name, module=None, cached_only=False, **k: {
        "ok": True, "status": "found", "proof": {"hash": lean["proof"]},
        "facts": [{"at": "/1/2", "fact_hash": "a" * 16}]})
    monkeypatch.setattr(us, "uses", lambda root, name, module=None, cached_only=False, **k: {
        "ok": True, "status": "found", "complete": True, "applications_complete": True,
        "users": [{"name": "Ex.young"}], "applications": [lean["app"]]})
    root = tmp_path / "lean"
    root.mkdir()
    p = opened(work)
    wsp.update(p, READING + [
        put({"id": "e-fact", "kind": "evidence", "claim": "P:eq:young", "role": "supports",
             "ref": {"fact": {"decl": "Ex.young", "module": "Ex.Basic", "at": "/1/2",
                              "fact_hash": "a" * 16, "proof_hash": "b" * 16}}}),
        put({"id": "e-app", "kind": "evidence", "claim": "P:eq:young", "role": "supports",
             "ref": {"app": {"callee": "Ex.norm_le", "module": "Ex.Basic", "id": app["id"],
                             "caller": "Ex.young", "app_hash": us.app_hash(app)}}}),
        put({"id": "c-norm", "kind": "composition", "claim": "P:eq:young", "steps": [
            {"id": "s1", "establishes": "‖f‖ ≤ 1 at x := f", "uses": ["e-app"],
             "requirements": ["r2"], "substitutions": [{"variable": "x", "value": "f",
                                                        "in": "e-app"}]}]}),
        put({"id": "f-stmt", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "basis": "direct", "evidence": ["e-young"], "note": "n"}),
        put({"id": "f-fact", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1",
             "coverage": "full", "basis": "reviewed_composition", "evidence": ["e-fact"],
             "note": "n"}),
        put({"id": "f-comp", "kind": "finding", "claim": "P:eq:young", "requirement": "r2",
             "coverage": "partial", "basis": "reviewed_composition", "composition": "c-norm",
             "note": "n"})], snap_of(work))
    wsp.update(p, [submit(f, 1) for f in ("f-stmt", "f-fact", "f-comp")], snap_of(work))
    deps = {f: rec(p, f)["dependencies"] for f in ("f-stmt", "f-fact", "f-comp")}
    assert deps["f-fact"]["kinds"] == ["proof route"]
    assert deps["f-comp"]["kinds"] == ["composition", "proof route"]
    by = {(it["dependency"], it.get("record")): it for it in deps["f-comp"]["items"]}
    assert by[("application", "e-app")]["via"] == ["c-norm"]
    assert by[("composition", "c-norm")]["sha256"].startswith("composition-v1:")
    assert states(p, work, root) == {"f-stmt": "current", "f-fact": "current",
                                     "f-comp": "current"}
    lean["proof"] = "c" * 16
    assert states(p, work, root) == {"f-stmt": "current", "f-fact": "stale",
                                     "f-comp": "current"}
    lean["app"] = {**app, "params": [{"binder": "x", "argument": "2 • f"}]}
    assert states(p, work, root) == {"f-stmt": "current", "f-fact": "stale",
                                     "f-comp": "stale"}
    # Without the Lean project, what rests on Lean's answers is not known to be current.
    got = wsp.currency(wsp.read(p), snap_of(work))
    assert (got["f-stmt"]["state"], got["f-fact"]["state"]) == ("current", "unchecked")
    assert got["f-fact"]["unknown"][0]["why"] == "no Lean project to check against"


def test_a_submitted_finding_is_never_rebound_to_a_record_re_pinned_after_it(work):
    p = opened(work)
    wsp.update(p, READING + [
        put({"id": "f-sub", "kind": "finding", "claim": "P:eq:young", "requirement": "r1.1.1",
             "coverage": "full", "evidence": ["e-young"], "note": "n"}),
        put({"id": "f-draft", "kind": "finding", "claim": "P:eq:young",
             "requirement": "r1.1.1", "coverage": "full", "evidence": ["e-young"],
             "note": "n"})], snap_of(work))
    wsp.update(p, [submit("f-sub", 1)], snap_of(work))
    make_build(work, fps={"Ex.Sol": "fp:sol-2"})
    assert states(p, work) == {"f-sub": "stale", "f-draft": "stale"}
    # The auditor reads the new definition and re-pins the evidence and the alignment.
    ops = [put({"id": "e-young", "kind": "evidence", "claim": "P:eq:young", "role": "supports",
                "ref": {"decl": "Ex.young"}, "repin": True}, rec(p, "e-young")["rev"]),
           put({"id": "a-bound", "kind": "alignment", "claim": "P:eq:young",
                "requirements": ["r1.1.1"], "lean": [{"decl": "Ex.young", "conclusion": True}],
                "repin": True}, rec(p, "a-bound")["rev"])]
    wsp.update(p, ops, snap_of(work))
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert cur["e-young"]["state"] == cur["a-bound"]["state"] == "current"
    # The draft follows its records; the submitted finding keeps the versions it was
    # submitted with, and says which records changed since.
    assert (cur["f-draft"]["state"], cur["f-sub"]["state"]) == ("current", "stale")
    assert {c.get("record") for c in cur["f-sub"]["changes"] if c.get("record")} == \
        {"e-young", "a-bound"}
    assert "the evidence e-young was edited or re-pinned after the finding was submitted" in \
        {c.get("reason") for c in cur["f-sub"]["changes"]}
    # Superseding it records the versions the auditor now rests on.
    wsp.update(p, [{"op": "supersede", "id": "f-sub", "base_rev": 2,
                    "reason": "the solution type changed; the bound still holds",
                    "record": {"id": "f-sub-2", "requirement": "r1.1.1", "coverage": "full",
                               "evidence": ["e-young"], "note": "n"}}], snap_of(work))
    assert states(p, work)["f-sub-2"] == "current"
    assert rec(p, "f-sub")["dependencies"]["items"] != rec(p, "f-sub-2")["dependencies"]["items"]


def test_what_cannot_be_identified_is_unknown_never_current(work, tmp_path):
    p = opened(work)
    wsp.update(p, [
        # Evidence recorded without a build: it carries its fingerprint, not the definitions
        # its statement uses.
        put({"id": "e-bare", "kind": "evidence", "claim": "P:thm:main", "role": "supports",
             "ref": {"decl": "Ex.main", "fingerprint": "fp:main-1"}}),
        put({"id": "e-line", "kind": "evidence", "claim": "P:thm:main", "role": "context",
             "ref": {"source": {"file": "Ex/Basic.lean", "line": 3}}}),
        put({"id": "f-bare", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
             "evidence": ["e-bare"], "note": "n"}),
        put({"id": "f-line", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
             "evidence": ["e-line"], "note": "n"}),
        put({"id": "f-own", "kind": "finding", "claim": "P:thm:main", "coverage": "full",
             "basis": "checked_bridge", "bridge": {"theorem": "Ex.main", "target": "Ex.Spec"},
             "note": "n"})], None)
    wsp.update(p, [submit(f, 1) for f in ("f-bare", "f-line", "f-own")], None)
    cur = wsp.currency(wsp.read(p), snap_of(work))
    assert {k: cur[k]["state"] for k in ("e-bare", "f-bare", "f-line", "f-own")} == {
        "e-bare": "unchecked", "f-bare": "unchecked", "f-line": "unchecked",
        "f-own": "unchecked"}
    why = {u["dependency"]: u["why"] for k in ("f-bare", "f-line", "f-own")
           for u in cur[k]["unknown"]}
    assert why["passage"].startswith("it was recorded without a build")
    assert why["declaration"].startswith("the definitions the statement of Ex.main uses were "
                                         "not recorded")
    assert why["source"] == "a source line records no version of its text"
    assert why["bridge"].startswith("a finding's own bridge records no version")
    # A finding submitted before findings recorded their dependencies is not taken as current.
    p2 = opened(work)
    wsp.update(p2, READING + [put({"id": "f-old", "kind": "finding", "claim": "P:eq:young",
                                   "coverage": "full", "evidence": ["e-young"], "note": "n"})],
               snap_of(work))
    wsp.update(p2, [submit("f-old", 1)], snap_of(work))
    data = wsp.export(p2)
    del data["records"]["f-old"]["dependencies"]
    other = tmp_path / "elsewhere" / ".machinechecked"
    make_build(other)
    wsp.import_(other, data, snap_of(other))
    got = wsp.currency(wsp.read(wsp.find(other, data["id"])), snap_of(other))
    assert got["f-old"]["state"] == "unchecked"
    assert got["f-old"]["unknown"][0]["dependency"] == "dependencies"
    # A definition the later build shows no version of is unknown too.
    make_build(work, young_uses=["Ex.norm", "Ex.Sol", "Ex.gone"])
    p3 = opened(work)
    wsp.update(p3, [put({"id": "e-y3", "kind": "evidence", "claim": "P:eq:young",
                         "role": "supports", "ref": {"decl": "Ex.young"}}),
                    put({"id": "f-y3", "kind": "finding", "claim": "P:eq:young",
                         "coverage": "full", "evidence": ["e-y3"], "note": "n"})],
               snap_of(work))
    got = wsp.currency(wsp.read(p3), snap_of(work))
    assert got["e-y3"]["state"] == got["f-y3"]["state"] == "unchecked"
    assert "Ex.gone" in got["f-y3"]["unknown"][0]["why"]


def test_a_checked_bridge_rests_on_its_composition_s_bridge(work, tmp_path):
    """A finding recorded as a checked bridge on a composition rests on the bridge's pins (the
    target's fingerprint and the passage Lean checked it against); without the Lean project the
    bridge cannot be checked, so the finding is not current."""
    p = opened(work)
    wsp.update(p, READING[:4], snap_of(work))
    data = wsp.export(p)
    data["records"]["c-bridge"] = {
        "id": "c-bridge", "kind": "composition", "claim": "P:eq:young", "rev": 1,
        "created_at": "2026-01-01T00:00:00Z", "created_by": WHO["id"],
        "updated_at": "2026-01-01T00:00:00Z", "updated_by": WHO["id"],
        "pins": {"release": "v-1", "statement_sha256": "s-young-1"},
        "steps": [{"id": "s1", "establishes": "the bound", "uses": ["e-young"],
                   "requirements": ["r1", "r2"]}], "evidence": ["e-young"], "coverage": "full",
        "bridge": {"theorem": "Ex.young", "target": "Ex.YoungSpec",
                   "target_fingerprint": "t" * 16, "source_sha256": "s-young-1"}}
    data["records"]["e-young"] = {
        "id": "e-young", "kind": "evidence", "claim": "P:eq:young", "role": "supports", "rev": 1,
        "created_at": "2026-01-01T00:00:00Z", "created_by": WHO["id"],
        "updated_at": "2026-01-01T00:00:00Z", "updated_by": WHO["id"], "pins": {},
        "ref": {"decl": "Ex.young", "fingerprint": "fp:young-1", "digest": "fp:young-1",
                "closure": {"Ex.norm": "fp:norm-1", "Ex.Sol": "fp:sol-1"}}}
    wsp.import_(work, data, snap_of(work))
    wsp.update(p, [put({"id": "f-bridge", "kind": "finding", "claim": "P:eq:young",
                        "coverage": "full", "basis": "checked_bridge", "composition": "c-bridge",
                        "note": "n"}), submit("f-bridge", 1)], snap_of(work))
    deps = rec(p, "f-bridge")["dependencies"]
    assert deps["kinds"] == ["statement comparison", "composition", "checked bridge"]
    (b,) = [it for it in deps["items"] if it["dependency"] == "bridge"]
    assert b == {"dependency": "bridge", "record": "c-bridge", "theorem": "Ex.young",
                 "target": "Ex.YoungSpec", "target_fingerprint": "t" * 16,
                 "source_sha256": "s-young-1"}
    cur = wsp.currency(wsp.read(p), snap_of(work))["f-bridge"]
    assert cur["state"] == "unchecked"
    assert cur["unknown"] == [{"dependency": "bridge", "record": "c-bridge",
                               "why": "no Lean project to check the bridge against"}]


def test_dependencies_travel_with_the_workspace_and_are_shown(work, tmp_path, monkeypatch,
                                                              capsys):
    p = opened(work)
    wsp.update(p, READING + [put({"id": "f-bound", "kind": "finding", "claim": "P:eq:young",
                                  "requirement": "r1.1.1", "coverage": "full",
                                  "evidence": ["e-young"], "note": "n"}),
                             submit("f-bound", 1)], snap_of(work))
    data = json.loads(json.dumps(wsp.export(p)))
    other = tmp_path / "elsewhere" / ".machinechecked"
    make_build(other, fps={"Ex.norm": "fp:norm-2"})
    wsp.import_(other, data, snap_of(other), "human:B-Auditor")
    got = wsp.read(wsp.find(other, data["id"]))["records"]["f-bound"]
    assert got["dependencies"] == rec(p, "f-bound")["dependencies"]
    v = wsp.view(wsp.read(wsp.find(other, data["id"])), snap_of(other))
    (f,) = v["claims"]["P:eq:young"]["findings"]
    assert f["currency"]["state"] == "stale"
    # `changes --workspace` lists it with the change named.
    due = chg.workspace_due(v, data["id"])
    (row,) = [r for r in due["records"] if r["id"] == "f-bound"]
    assert row["state"] == "stale" and row["submitted"]
    text = "\n".join(chg.workspace_lines(due))
    assert "Ex.norm, which the statement of Ex.young uses, changed" in text
    # `workspace show` says what it rests on and what changed.
    root = other.parent
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    monkeypatch.chdir(root)
    capsys.readouterr()
    cli.main(["workspace", "show", "--id", data["id"]])
    out = capsys.readouterr().out
    assert "rests on: the passage of P:eq:young; requirement r1; " in out
    assert "Ex.young (and 2 definitions its statement uses)" in out
    assert "changed: Ex.norm, which the statement of Ex.young uses, changed" in out
    cli.main(["workspace", "show", "--id", data["id"], "--json"])
    shown = json.loads(capsys.readouterr().out)["claims"]["P:eq:young"]["findings"][0]
    assert shown["dependencies"]["kinds"] == ["statement comparison", "object correspondence"]


def test_the_dependency_words_cover_each_kind():
    items = [{"dependency": "passage", "claim": "P:x"},
             {"dependency": "reading", "requirement": "r1"},
             {"dependency": "context", "requirement": "r1", "role": "quantifier domain",
              "region": {"file": "a.tex", "start_line": 3, "end_line": 4}},
             {"dependency": "object", "relation": "corresponds",
              "lean": [{"decl": "Ex.f", "var": 0, "target": "x"}]},
             {"dependency": "application", "ref": {"app": {"callee": "Ex.g",
                                                           "caller": "Ex.f"}}},
             {"dependency": "composition", "record": "c1"},
             {"dependency": "bridge", "theorem": "Ex.f", "target": "Ex.S"},
             {"dependency": "counterexample", "record": "x1"}]
    assert [dp.item_text(it) for it in items] == [
        "the passage of P:x", "requirement r1", "a.tex:3-4 (quantifier domain of r1)",
        "Ex.f (variable 0: x) (corresponds)", "Ex.g applied in Ex.f", "composition c1",
        "bridge Ex.f for Ex.S", "counterexample x1"]
