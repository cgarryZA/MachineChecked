"""A claim's requirements in a workspace (#99): the passages of the paper that govern each one
(a quantifier's domain, a constant's dependence, a standing assumption), suggested context the
auditor accepts or removes, witness obligations, many-to-many alignment with Lean, currency
against the paper's source and the Lean, and the reading in `workspace show`, `compare` and the
local reader's interface. A small synthetic build and paper stand in for a real one, so these
tests run no Lean."""

import json
import types

import pytest

from prooflens import cli
from prooflens import compare as cmp
from prooflens import requirements as rq
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

WHO = rc.parse_reviewer("human:A-Auditor")

# A synthetic paper. The display (lines 7-9) is a claim of its own; the quantifier before it
# (line 6) and the constant's dependence after it (line 10) are outside that claim's passage,
# and a later line chooses a particular value. Section 2's preamble fixes a parameter for its
# examples only.
PAPER = r"""\documentclass{article}
\begin{document}
\section{Estimates}

\begin{lemma}\label{lem:bound}
Let $u$ solve the problem of Definition~\ref{def:sol}. For every $\varepsilon > 0$,
\begin{equation}\label{eq:young}
  |u| \le \varepsilon |f| + C/\varepsilon,
\end{equation}
the constant $C$ here does not depend on the choice of $\varepsilon$.
\end{lemma}

Choosing $\varepsilon < 1$ in \eqref{eq:young} gives the bound.

\section{Examples}
Throughout this section, $\nu \neq 0$ is fixed.

\begin{example}\label{ex:one}
The scalar system with coefficient $\nu$ satisfies the assumptions.
\end{example}

\section{Other examples}

\begin{example}\label{ex:two}
The zero system satisfies the assumptions.
\end{example}

\begin{definition}\label{def:sol}
A solution is a pair $(u, f)$.
\end{definition}
\end{document}
"""

YOUNG = {"binders": [
    {"id": "/", "name": "ε", "role": "forall", "type": {"text": "ℝ", "segments": [{"t": "ℝ"}],
                                                        "terms": []}},
    {"id": "/1", "name": "hε", "role": "hypothesis",
     "type": {"text": "0 < ε", "segments": [{"t": "0"}, {"t": " < "}, {"t": "ε", "var": 0}],
              "terms": [{"id": "/1/0/0", "from": 0, "to": 3}]}},
    {"id": "/1/1", "name": "hf", "role": "hypothesis",
     "type": {"text": "Bounded f", "segments": [{"t": "Bounded f"}], "terms": []}}],
    "conclusion": {"id": "/1/1/1", "text": "|u| ≤ ε * |f| + C / ε",
                   "segments": [{"t": "|u| ≤ ε * |f| + C / ε"}], "terms": []},
    "fingerprint": "fp:young-1"}


def _chunk(cid, number, kind, key, sha, lines=None, **extra):
    out = {"id": cid, "paper": "P", "number": number, "kind": kind, "key": key,
           "source_sha256": sha, "links": [], "suggestions": [], "clauses": [], "decls": {},
           "anchor": {"file": "paper.tex", "label": key}}
    if lines:
        out["excerpt"] = {"file": "paper.tex", "start_line": lines[0], "end_line": lines[1]}
    out.update(extra)
    return out


def make_build(work, fp_young="fp:young-1", fp_bound="fp:bound-1", paper=PAPER):
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True, exist_ok=True)
    (data / "decls").mkdir(parents=True, exist_ok=True)
    src = work / "sources" / "P"
    src.mkdir(parents=True, exist_ok=True)
    (src / "paper.tex").write_text(paper, encoding="utf-8")
    young = {**YOUNG, "fingerprint": fp_young}
    claims = [
        _chunk("P:eq:young", "Equation (1)", "equation", "eq:young", "s-young", (7, 9),
               clauses=[{"name": "statement", "spec": "Ex.young_spec", "statement": young}],
               links=[{"name": "Ex.young", "fingerprint": fp_young, "statement": young}]),
        _chunk("P:lem:bound", "Lemma 1.1", "lemma", "lem:bound", "s-bound", (5, 11),
               links=[{"name": "Ex.bound", "fingerprint": fp_bound}]),
        _chunk("P:ex:one", "Example 2.1", "example", "ex:one", "s-one", (18, 20)),
        _chunk("P:ex:two", "Example 3.1", "example", "ex:two", "s-two", (24, 26)),
        _chunk("P:def:sol", "Definition 3.2", "definition", "def:sol", "s-sol", (28, 30)),
    ]
    for c in claims:
        (data / "claims" / f"{c['key'].replace(':', '_')}.json").write_text(json.dumps(c))
    index = {"schema": "prooflens/manifest@1", "release": "v-1",
             "project": {"name": "ex", "commit": "abc123"},
             "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123"}],
             "claims": [{"id": c["id"], "paper": "P", "number": c["number"], "kind": c["kind"],
                         "file": f"{c['key'].replace(':', '_')}.json"} for c in claims]}
    (data / "index.json").write_text(json.dumps(index))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Ex.Basic"}
         for n in ("Ex.young", "Ex.young_spec", "Ex.bound", "Ex.other")]))
    return Snapshot(data)


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w)
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def opened(work):
    return wsp.open_for(work, WHO, "informed", sources=snap_of(work).sources())


def put(rec, base=None):
    op = {"op": "put", "record": rec}
    if base is not None:
        op["base_rev"] = base
    return op


def region(a, b=None):
    return {"file": "paper.tex", "start_line": a, "end_line": b or a}


# The printed reading of (1): one C, chosen before ε and independent of it; for every ε > 0;
# the estimate. Each requirement keeps the passage it comes from.
YOUNG_READING = [
    put({"id": "r-C", "kind": "requirement", "claim": "Equation (1)", "local_id": "r1",
         "form": "there is", "binds": ["C"], "independent_of": ["ε"],
         "text": "there is a constant C, independent of ε"}),
    put({"id": "r-eps", "kind": "requirement", "claim": "Equation (1)", "local_id": "r1.1",
         "parent": "r1", "form": "for every", "binds": ["ε"], "text": "for every ε > 0"}),
    put({"id": "r-est", "kind": "requirement", "claim": "Equation (1)", "local_id": "r1.1.1",
         "parent": "r1.1", "form": "conclusion", "text": "|u| ≤ ε|f| + C/ε"}),
    put({"id": "p-dep", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1",
         "role": "constant dependence", "region": region(10)}),
    put({"id": "p-eps", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1.1",
         "role": "quantifier domain", "region": region(6), "scope": "Lemma 1.1"}),
    put({"id": "p-est", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1.1.1",
         "role": "statement", "passage": {"claim": "Equation (1)"}}),
    put({"id": "p-use", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1.1",
         "role": "later use", "region": region(13)}),
]


def reading_of(work, p, claim="P:eq:young"):
    return wsp.view(wsp.read(p), snap_of(work))["claims"][claim]["reading"]


def req(rd, lid):
    return next(r for r in rd["requirements"] if r["local_id"] == lid)


# -- governing context -----------------------------------------------------------------------

def test_a_display_keeps_its_quantifier_and_the_dependence_of_its_constant(work):
    p = opened(work)
    wsp.update(p, YOUNG_READING, snap_of(work))
    rd = reading_of(work, p)
    assert [(r["local_id"], r["depth"]) for r in rd["requirements"]] == \
        [("r1", 0), ("r1.1", 1), ("r1.1.1", 2)]
    eps = req(rd, "r1.1")
    # The exact printed sentence, kept with its role, origin, scope and author.
    gov = eps["fragments"]["governing"]
    assert [f["region"]["text"] for f in gov] == [
        r"Let $u$ solve the problem of Definition~\ref{def:sol}. For every $\varepsilon > 0$,"]
    assert gov[0]["role"] == "quantifier domain" and gov[0]["origin"] == "printed"
    assert gov[0]["scope"] == "Lemma 1.1" and gov[0]["created_by"] == "human:A-Auditor"
    assert len(gov[0]["region"]["line_sha256"]) == 1
    assert req(rd, "r1")["fragments"]["governing"][0]["region"]["text"] == \
        r"the constant $C$ here does not depend on the choice of $\varepsilon$."
    # A later choice of ε is a use: shown apart, and it does not rewrite "for every ε > 0".
    assert [f["region"]["start_line"] for f in eps["fragments"]["later_uses"]] == [13]
    assert eps["text"] == "for every ε > 0"
    # One C, chosen before ε.
    assert rd["witnesses"] == [{"requirement": "r1", "binds": ["C"], "scope": "produced",
                                "after": [], "before": ["ε"], "independent_of": ["ε"],
                                "conditions": ["r1.1"], "inside": [], "forms": []}]
    assert rd["questions"] == []
    assert all(r["currency"]["state"] == "current" for r in rd["requirements"])


def test_a_later_use_never_changes_the_reading_it_uses(work):
    p = opened(work)
    wsp.update(p, YOUNG_READING[:-1], snap_of(work))
    before = req(reading_of(work, p), "r1.1")["reading_sha256"]
    wsp.update(p, YOUNG_READING[-1:], snap_of(work))
    assert req(reading_of(work, p), "r1.1")["reading_sha256"] == before
    # A requirement attached only to later uses has no source, and says so.
    wsp.update(p, [put({"kind": "requirement", "claim": "P:eq:young", "local_id": "r9",
                        "form": "condition", "text": "ε < 1"}),
                   put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r9",
                        "role": "later use", "region": region(13)})], snap_of(work))
    r9 = req(reading_of(work, p), "r9")
    assert r9["questions"] == ["no passage of the paper is attached as its source (only later "
                               "uses are)"]


def test_changing_the_quantifier_changes_the_reading_though_the_display_is_unchanged(work):
    p = opened(work)
    snap = snap_of(work)
    wsp.update(p, YOUNG_READING + [put({"id": "f-eps", "kind": "finding", "claim": "P:eq:young",
                                        "requirement": "r1.1", "coverage": "changed",
                                        "note": "The paper's domain is too wide."})], snap)
    before = req(reading_of(work, p), "r1.1")["reading_sha256"]
    src = work / "sources" / "P" / "paper.tex"
    src.write_text(PAPER.replace(r"For every $\varepsilon > 0$",
                                 r"For every $0 < \varepsilon \le 1$"), encoding="utf-8")
    # The display's own claim has the same text, so its pin is unchanged.
    assert snap_of(work).chunk("P:eq:young")["source_sha256"] == "s-young"
    v = wsp.view(wsp.read(p), snap_of(work))
    rd = v["claims"]["P:eq:young"]["reading"]
    eps = req(rd, "r1.1")
    assert eps["currency"]["state"] == "stale"
    assert eps["fragments"]["governing"][0]["currency"]["changes"][0]["lines"] == [6]
    assert req(rd, "r1.1.1")["currency"]["state"] == "current"
    assert req(rd, "r1")["currency"]["state"] == "current"
    f = next(x for x in v["claims"]["P:eq:young"]["findings"] if x["id"] == "f-eps")
    assert f["currency"]["state"] == "stale"
    # The fragment keeps the text it was attached with until it is re-pinned; re-pinned, the
    # reading's digest changes.
    frag = wsp.read(p)["records"]["p-eps"]
    assert "0 < \\varepsilon" not in frag["region"]["text"]
    wsp.update(p, [put({**{k: frag[k] for k in ("id", "kind", "claim", "requirement", "role",
                                                 "region", "scope")}, "repin": True},
                       frag["rev"])], snap_of(work))
    after = req(reading_of(work, p), "r1.1")
    assert after["currency"]["state"] == "current"
    assert after["reading_sha256"] != before
    assert r"0 < \varepsilon \le 1" in after["fragments"]["governing"][0]["region"]["text"]


def test_a_region_is_checked_against_the_papers_source(work):
    p = opened(work)
    snap = snap_of(work)
    wsp.update(p, YOUNG_READING[:1], snap)
    for bad, msg in (({"file": "paper.tex", "start_line": 400}, "outside the file"),
                     ({"file": "../secret.tex", "start_line": 1}, "leaves the manuscript"),
                     ({"file": "paper.tex", "start_line": 4}, "empty"),
                     ({"file": "paper.tex", "start_line": 9, "end_line": 6}, "ends before")):
        with pytest.raises(wsp.WorkspaceError, match=msg):
            wsp.update(p, [put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r1",
                                "role": "context", "region": bad})], snap)
    with pytest.raises(wsp.WorkspaceError, match="no requirement 'r7'"):
        wsp.update(p, [put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r7",
                            "role": "context", "region": region(6)})], snap)
    with pytest.raises(wsp.WorkspaceError, match="one region"):
        wsp.update(p, [put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r1",
                            "role": "context"})], snap)


# -- suggestions -----------------------------------------------------------------------------

def test_nearby_context_is_suggested_and_the_auditor_accepts_or_removes_it(work):
    snap = snap_of(work)
    got = rq.suggest(snap, "P:eq:young")
    where = {(s["role"], (s.get("region") or {}).get("start_line"),
              (s.get("passage") or {}).get("claim")) for s in got}
    assert ("quantifier domain", 6, None) in where
    assert ("constant dependence", 10, None) in where
    # The later use is not context of the estimate.
    assert not any((s.get("region") or {}).get("start_line") == 13 for s in got)
    assert all(s["state"] == "proposed" for s in got)
    # The lemma cites the definition of a solution.
    lemma = rq.suggest(snap, "P:lem:bound")
    assert any(s.get("passage") == {"claim": "P:def:sol"} and s["role"] == "definition"
               for s in lemma)

    p = opened(work)
    wsp.update(p, YOUNG_READING[:3], snap)
    ops = rq.suggestion_ops(wsp.read(p), snap, "P:eq:young", "r1.1")
    wsp.update(p, ops, snap)
    assert rq.suggestion_ops(wsp.read(p), snap, "P:eq:young", "r1.1") == []
    eps = req(reading_of(work, p), "r1.1")
    assert eps["fragments"]["governing"] == []
    assert len(eps["fragments"]["proposed"]) == len(ops)
    assert any("not yet accepted" in q for q in eps["questions"])
    ws = wsp.read(p)
    by_line = {r["region"]["start_line"]: r for r in ws["records"].values()
               if r["kind"] == "fragment" and r.get("region")}
    keep, wrong = by_line[6], by_line[10]
    fields = ("id", "kind", "claim", "requirement", "role", "origin", "region", "suggestion")
    with pytest.raises(wsp.WorkspaceError, match="why it was removed"):
        wsp.update(p, [put({**{k: wrong[k] for k in fields}, "state": "removed"},
                           wrong["rev"])], snap)
    wsp.update(p, [put({**{k: keep[k] for k in fields}, "state": "accepted"}, keep["rev"]),
                   put({**{k: wrong[k] for k in fields}, "state": "removed",
                        "why_removed": "it constrains the constant, not ε"}, wrong["rev"])],
               snap, by="human:B-Auditor")
    eps = req(reading_of(work, p), "r1.1")
    assert [f["region"]["start_line"] for f in eps["fragments"]["governing"]] == [6]
    assert eps["fragments"]["governing"][0]["suggestion"]["by"] == "machinechecked"
    assert eps["fragments"]["governing"][0]["state_by"] == "human:B-Auditor"
    gone = eps["fragments"]["removed"][0]
    assert gone["state_by"] == "human:B-Auditor" and gone["created_by"] == "human:A-Auditor"
    assert gone["why_removed"] == "it constrains the constant, not ε"
    # The source is left exactly as it was.
    assert (work / "sources" / "P" / "paper.tex").read_text(encoding="utf-8") == PAPER


def test_a_standing_assumption_is_suggested_only_within_its_section(work):
    snap = snap_of(work)
    one = [s for s in rq.suggest(snap, "P:ex:one") if s["role"] == "standing assumption"]
    assert [(s["region"]["start_line"], s["origin"]) for s in one] == [(16, "inferred")]
    assert "Examples" in one[0]["scope"]
    # Another section's example inherits nothing from it.
    two = rq.suggest(snap, "P:ex:two")
    assert not any((s.get("region") or {}).get("start_line") == 16 for s in two)


# -- logical structure -----------------------------------------------------------------------

def _tree(work, claim, nodes):
    p = opened(work)
    ops = [put({"kind": "requirement", "claim": claim, "local_id": lid, "form": form,
                "text": text, **({"parent": parent} if parent else {}),
                **({"binds": binds} if binds else {})})
           for lid, parent, form, text, binds in nodes]
    wsp.update(p, ops, snap_of(work))
    return reading_of(work, p, claim)["witnesses"]


def test_one_witness_for_both_properties_differs_from_two_witnesses(work):
    one = _tree(work, "P:ex:one", [("a", None, "there is", "x", ["x"]),
                                   ("a.1", "a", "condition", "P x", None),
                                   ("a.2", "a", "condition", "Q x", None)])
    assert [(w["binds"], w["conditions"]) for w in one] == [(["x"], ["a.1", "a.2"])]
    two = _tree(work, "P:ex:two", [("b", None, "and", "both", None),
                                   ("b.1", "b", "there is", "x", ["x"]),
                                   ("b.1.1", "b.1", "condition", "P x", None),
                                   ("b.2", "b", "there is", "y", ["y"]),
                                   ("b.2.1", "b.2", "condition", "Q y", None)])
    assert [(w["binds"], w["conditions"]) for w in two] == [(["x"], ["b.1.1"]),
                                                             (["y"], ["b.2.1"])]


def test_negation_premise_and_alternative_keep_a_witness_in_its_scope(work):
    ws = _tree(work, "P:lem:bound", [
        ("n", None, "not", "there is no x with P x", None),
        ("n.1", "n", "there is", "x", ["x"]),
        ("i", None, "implies", "if a solution exists then R", None),
        ("i.1", "i", "assumption", "a solution exists", None),
        ("i.1.1", "i.1", "there is", "s", ["s"]),
        ("i.2", "i", "conclusion", "R", None),
        ("o", None, "or", "either there is z or Q", None),
        ("o.1", "o", "there is", "z", ["z"])])
    assert {w["requirement"]: w["scope"] for w in ws} == {"n.1": "denied", "i.1.1": "assumed",
                                                          "o.1": "alternative"}


def test_one_constant_before_every_index_differs_from_one_per_index(work):
    uniform = _tree(work, "P:ex:one", [("c", None, "there is", "C", ["C"]),
                                       ("c.1", "c", "for every", "n", ["n"]),
                                       ("c.1.1", "c.1", "conclusion", "T n ≤ C n²", None)])
    assert [(w["after"], w["before"]) for w in uniform] == [([], ["n"])]
    per = _tree(work, "P:ex:two", [("d", None, "for every", "n", ["n"]),
                                   ("d.1", "d", "there is", "C", ["C"]),
                                   ("d.1.1", "d.1", "conclusion", "T n ≤ C n²", None)])
    assert [(w["after"], w["before"]) for w in per] == [(["n"], [])]


def test_requirements_are_validated(work):
    p = opened(work)
    snap = snap_of(work)
    wsp.update(p, YOUNG_READING[:3], snap)
    cases = [
        ({"local_id": "r1", "text": "again"}, "already has a requirement r1"),
        ({"local_id": "bad id", "text": "x"}, "not a local id"),
        ({"local_id": "r2", "text": "x", "parent": "r8"}, "no requirement 'r8'"),
        ({"local_id": "r2", "text": "x", "form": "condition", "binds": ["n"]}, "binds"),
        ({"local_id": "r2", "text": "x", "form": "wish"}, "the form"),
        ({"local_id": "r2", "text": ""}, "is empty"),
        ({"local_id": "r2", "text": "x", "origin": "correction"}, "names the printed"),
    ]
    for rec, msg in cases:
        with pytest.raises(wsp.WorkspaceError, match=msg):
            wsp.update(p, [put({"kind": "requirement", "claim": "P:eq:young", **rec})], snap)
    # A requirement cannot be put inside one of its own parts.
    r1 = wsp.read(p)["records"]["r-C"]
    with pytest.raises(wsp.WorkspaceError, match="is inside"):
        wsp.update(p, [put({**{k: r1[k] for k in ("id", "kind", "claim", "local_id", "form",
                                                   "text")}, "parent": "r1.1.1"}, r1["rev"])],
                   snap)
    # Nor removed or renamed while other records refer to it.
    with pytest.raises(wsp.WorkspaceError, match="used by"):
        wsp.update(p, [{"op": "delete", "id": "r-C", "base_rev": r1["rev"]}], snap)
    with pytest.raises(wsp.WorkspaceError, match="used by"):
        wsp.update(p, [put({**{k: r1[k] for k in ("id", "kind", "claim", "form", "text")},
                            "local_id": "r0"}, r1["rev"])], snap)
    leaf = wsp.read(p)["records"]["r-est"]
    wsp.update(p, [{"op": "delete", "id": "r-est", "base_rev": leaf["rev"]}], snap)
    assert "r-est" not in wsp.read(p)["records"]


def test_a_correction_adds_a_requirement_beside_the_printed_one(work):
    p = opened(work)
    snap = snap_of(work)
    wsp.update(p, [
        put({"kind": "requirement", "claim": "P:eq:young", "local_id": "r1", "form": "for every",
             "binds": ["ε"], "text": "for every ε > 0"}),
        put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r1",
             "role": "quantifier domain", "region": region(6)}),
        put({"kind": "requirement", "claim": "P:eq:young", "local_id": "r1c", "form": "for every",
             "binds": ["ε"], "text": "for every 0 < ε ≤ 1", "origin": "correction",
             "corrects": "r1"}),
        put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r1c",
             "role": "proposed correction", "region": region(13),
             "note": "the proof only uses ε < 1"})], snap)
    rd = reading_of(work, p)
    assert req(rd, "r1")["text"] == "for every ε > 0" and req(rd, "r1")["origin"] == "printed"
    corr = req(rd, "r1c")
    assert corr["corrects"] == "r1" and corr["origin"] == "correction"
    assert corr["fragments"]["governing"][0]["origin"] == "correction"
    assert corr["questions"] == []
    with pytest.raises(wsp.WorkspaceError, match="origin `correction`"):
        wsp.update(p, [put({"kind": "fragment", "claim": "P:eq:young", "requirement": "r1",
                            "role": "proposed correction", "origin": "printed",
                            "region": region(13)})], snap)


# -- alignment with Lean ---------------------------------------------------------------------

def test_requirements_and_lean_targets_align_many_to_many(work):
    p = opened(work)
    snap = snap_of(work)
    wsp.update(p, YOUNG_READING + [
        # One paper condition, two hypotheses of the Lean statement.
        put({"id": "a-eps", "kind": "alignment", "claim": "P:eq:young", "requirements": ["r1.1"],
             "lean": [{"decl": "Ex.young_spec", "var": "ε"},
                      {"decl": "Ex.young_spec", "binder": "hε"}]}),
        # Two requirements, one conclusion.
        put({"id": "a-est", "kind": "alignment", "claim": "P:eq:young",
             "requirements": ["r1", "r1.1.1"],
             "lean": [{"decl": "Ex.young_spec", "conclusion": True}, {"decl": "Ex.young"}]}),
        # A Lean hypothesis with no counterpart in the paper.
        put({"id": "a-extra", "kind": "alignment", "claim": "P:eq:young", "requirements": [],
             "relation": "additional assumption",
             "lean": [{"decl": "Ex.young_spec", "binder": 2}],
             "note": "the Lean also assumes f bounded"})], snap)
    rd = reading_of(work, p)
    al = {a["id"]: a for a in rd["alignments"]}
    assert [t.get("target") for t in al["a-eps"]["lean"]] == ["ε", "hε : 0 < ε"]
    assert [t.get("var", t.get("binder")) for t in al["a-eps"]["lean"]] == [0, 1]
    assert al["a-est"]["lean"][0]["target"] == "|u| ≤ ε * |f| + C / ε"
    assert al["a-est"]["lean"][1]["fingerprint"] == "fp:young-1"
    assert al["a-extra"]["relation"] == "additional assumption"
    assert al["a-extra"]["created_by"] == "human:A-Auditor"
    assert req(rd, "r1.1")["alignments"] == ["a-eps"]
    assert req(rd, "r1")["alignments"] == ["a-est"]
    assert req(rd, "r1.1.1")["alignments"] == ["a-est"]
    # Checked against the build.
    for lean, msg in (([{"decl": "Ex.young_spec", "binder": "hz"}], "no variable 'hz'"),
                      ([{"decl": "Ex.bound", "conclusion": True}], "no statement of Ex.bound"),
                      ([{"decl": "Ex.nothing"}], "not a declaration of the project"),
                      ([], "one or more Lean targets")):
        with pytest.raises(wsp.WorkspaceError, match=msg):
            wsp.update(p, [put({"kind": "alignment", "claim": "P:eq:young",
                                "requirements": ["r1"], "lean": lean})], snap)
    with pytest.raises(wsp.WorkspaceError, match="names the requirements"):
        wsp.update(p, [put({"kind": "alignment", "claim": "P:eq:young", "requirements": [],
                            "lean": [{"decl": "Ex.young"}]})], snap)
    # A changed declaration makes the alignment, and the requirements it concerns, stale.
    make_build(work, fp_young="fp:young-2")
    rd = reading_of(work, p)
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-est"]["currency"]["state"] == "stale"
    assert req(rd, "r1.1.1")["currency"]["state"] == "stale"


# -- interfaces ------------------------------------------------------------------------------

def _run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_command_line_suggest_show_and_compare(work, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_workspace_place", lambda a: (work, work / "site" / "data",
                                                            tmp_path))
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, tmp_path))
    p = opened(work)
    wsp.update(p, YOUNG_READING, snap_of(work))
    wid = wsp.read(p)["id"]
    code, out, _ = _run(["workspace", "suggest", "--id", wid, "--claim", "Equation (1)",
                         "--requirement", "r1.1"], capsys)
    assert code == 0
    ops = json.loads(out)["ops"]
    assert {o["record"]["region"]["start_line"] for o in ops if o["record"].get("region")} \
        >= {10}
    assert all(o["record"]["state"] == "proposed" for o in ops)
    code, out, _ = _run(["workspace", "suggest", "--id", wid, "--claim", "Equation (1)",
                         "--requirement", "r1.1", "--apply", "--as", "human:A-Auditor"], capsys)
    assert code == 0 and json.loads(out)["suggested"] == len(ops)
    code, out, _ = _run(["workspace", "suggest", "--id", wid, "--claim", "Equation (1)",
                         "--requirement", "nope"], capsys)
    assert code == 1 and "no requirement 'nope'" in json.loads(out)["error"]
    code, out, _ = _run(["workspace", "show", "--id", wid, "--claim", "Equation (1)"], capsys)
    assert code == 0
    assert "r1.1  for every ε: for every ε > 0" in out
    assert "from paper.tex:6 (domain of a quantifier, printed, applies to Lemma 1.1" in out
    assert "used later at paper.tex:13 (a use; the reading is unchanged)" in out
    assert "witness C: the claim produces it; chosen before ε; independent of ε" in out
    # The informed packet carries the reading with the exact source of each fragment.
    code, out, _ = _run(["compare", "Equation (1)", "--workspace", wid, "--json"], capsys)
    assert code == 0
    pk = json.loads(out)
    rd = pk["interpretations"]["requirements"]
    assert rd["workspace"] == wid and rd["reviewer"] == "human:A-Auditor"
    texts = [f["region"]["text"] for r in rd["requirements"]
             for f in r["fragments"]["governing"] if f.get("region")]
    assert r"the constant $C$ here does not depend on the choice of $\varepsilon$." in texts
    assert any("For every $\\varepsilon > 0$" in t for t in texts)
    # Before the verdict, the auditor's reading is withheld.
    for stage in ("read", "compare"):
        code, out, _ = _run(["compare", "Equation (1)", "--workspace", wid, "--stage", stage,
                             "--json"], capsys)
        pk = json.loads(out)
        assert "interpretations" not in pk
        assert "recorded requirements" in json.dumps(pk["retrieval"]["withheld"])
    code, out, _ = _run(["compare", "Equation (1)", "--workspace", wid], capsys)
    assert "Requirements recorded in workspace" in out and "r1.1.1" in out
    code, out, _ = _run(["compare", "Equation (1)", "--workspace", "ws-nothing", "--json"],
                        capsys)
    assert code == 1 and json.loads(out)["error"]["kind"] == "unknown-workspace"


def test_the_readers_interface_suggests_and_shows_the_reading(work):
    get, post = wsp.api(work, work / "site" / "data")
    v = post["/api/workspace"]({"action": "open", "reviewer": "human:A-Auditor",
                                "mode": "informed"})
    post["/api/workspace"]({"action": "update", "id": v["id"], "ops": YOUNG_READING[:3],
                            "op_id": "req-1"})
    ack = post["/api/workspace"]({"action": "suggest", "id": v["id"], "claim": "Equation (1)",
                                  "requirement": "r1"})
    assert ack["suggested"] >= 1
    again = post["/api/workspace"]({"action": "suggest", "id": v["id"], "claim": "P:eq:young",
                                    "requirement": "r1"})
    assert again["suggested"] == 0
    shown = get["/api/workspace"]({"id": [v["id"]], "claim": ["P:eq:young"]})
    rd = shown["claims"]["P:eq:young"]["reading"]
    assert [r["local_id"] for r in rd["requirements"]] == ["r1", "r1.1", "r1.1.1"]
    assert req(rd, "r1")["fragments"]["proposed"]
    assert shown["requirements"] == 3


def test_requirements_survive_export_and_import(work, tmp_path):
    p = opened(work)
    wsp.update(p, YOUNG_READING, snap_of(work))
    body = wsp.export(p)
    other = tmp_path / "other" / ".machinechecked"
    make_build(other)
    res = wsp.import_(other, body, Snapshot(other / "site" / "data"))
    assert res["problems"] == [] and len(res["added"]) == len(YOUNG_READING)
    q = wsp.read(wsp.find(other, body["id"]))
    rd = wsp.view(q, Snapshot(other / "site" / "data"))["claims"]["P:eq:young"]["reading"]
    assert [r["local_id"] for r in rd["requirements"]] == ["r1", "r1.1", "r1.1.1"]
    assert all(r["currency"]["state"] == "current" for r in rd["requirements"])
