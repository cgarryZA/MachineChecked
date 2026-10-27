"""Alignments and symbol links that name exactly what the paper and the Lean say (#99): one
passage aligned with several Lean targets and several passages with one; the definitions of a
claim that only defines as targets; sub-terms of a definition expanded at its arguments (nested
ones included) and of an equation the site stores on a later page; and a symbol whose
occurrences are different objects of the paper, each linked apart. A small synthetic build
stands in for a real one, so these tests run no Lean. None of it changes a status."""

import json

import pytest

from prooflens import published_work as pw
from prooflens import requirements as rq
from prooflens import review_cli as rc
from prooflens import symbols as sy
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.manifest import symbol_links
from prooflens.targets import Snapshot
from prooflens.util import sha256_text

WHO = rc.parse_reviewer("human:A-Auditor")
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)

PAPER = r"""\documentclass{article}
\begin{document}
\section{Definitions}

\begin{definition}\label{def:even}
A number $n$ is even if $n = 2k$ for some $k$. The number $T_n$ is $0 + 1 + \dots + n$.
\end{definition}

\begin{theorem}\label{thm:good}
For every $n$, the profile of $n$ is good.
\end{theorem}

\begin{lemma}\label{lem:est}
For every $\varepsilon > 0$,
\begin{equation}\label{eq:est}
  |u| \le \varepsilon |f| + C/\varepsilon,
\end{equation}
with $C$ independent of $\varepsilon$.
\end{lemma}

\begin{theorem}\label{thm:exists}
There are a function $u$ and a source $f$ such that
\begin{enumerate}
\item $u$ is continuous,
\item $u(0) = 0$,
\item $f \ge 0$,
\item $u' = f$,
\item $|u| \le 1$, and
\item $f$ has compact support.
\end{enumerate}
\end{theorem}
\end{document}
"""


def seg(*parts):
    """Printed segments from (text, extra) pairs or plain text."""
    return [{"t": p} if isinstance(p, str) else {"t": p[0], **p[1]} for p in parts]


def pp(pid, text, segments, terms=(), **extra):
    return {"id": pid, "text": text, "segments": segments, "terms": list(terms), **extra}


K_GOOD, K_BELOW, K_PAGE = "a1" * 12, "b2" * 12, "c3" * 12
D_EVEN, D_TRI = "d4" * 12, "e5" * 12

# Ex.good : ∀ n, Ex.Good n. Ex.Good is expanded at n (stored on its own), and inside it Ex.Below.
GOOD = {"binders": [{"id": "/", "name": "n", "role": "forall",
                     "type": pp("/0", "Nat", seg("Nat"))}],
        "conclusion": pp("/1", "Ex.Good n", seg(("Ex.Good", {"ref": "Ex.Good"}), " ",
                                                 ("n", {"var": 0, "at": "/1/1"})),
                         expansions=[{"at": "/1", "id": "/1=", "name": "Ex.Good",
                                      "key": K_GOOD}]),
        "closure": ["Ex.Good", "Ex.Below"], "fingerprint": "fp:good-1"}
GOOD_AT_N = {"name": "Ex.Good", "at": "/1", "id": "/1=", "checked": True, "defined_by": "body",
             "args": [{"name": "n", "binder": "explicit",
                       "value": pp("/1/1", "n", seg(("n", {"var": 0, "at": "/1/1"})))}],
             "body": pp("/1=/", "∀ i < 3, Ex.Below n i",
                        seg("∀ ", ("i", {"at": "/1=/"}), " < 3, ",
                            ("Ex.Below", {"ref": "Ex.Below"}), " ",
                            ("n", {"var": 0, "at": "/1=/1/0/1"}), " ", ("i", {"at": "/1=/1/1"})),
                        [{"id": "/1=/1", "from": 3, "to": 8}],
                        expansions=[{"at": "/1=/1", "id": "/1=/1=", "name": "Ex.Below",
                                     "key": K_BELOW}])}
BELOW_AT = {"name": "Ex.Below", "at": "/1=/1", "id": "/1=/1=", "checked": True,
            "defined_by": "body",
            "body": pp("/1=/1=/", "i ≤ n", seg(("i", {"at": "/1=/1=/0/1"}), " ≤ ",
                                               ("n", {"var": 0, "at": "/1=/1=/1"})),
                       [{"id": "/1=/1=/", "from": 0, "to": 3}])}


def equation(name, k, text):
    st = pp(f"{name}.eq_{k}:/", text, seg(text), [{"id": f"{name}.eq_{k}:/1", "from": 0, "to": 1}])
    return {"name": f"{name}.eq_{k}", "params": [], "statement": st, "equation": st}


# Ex.f is defined by three equations; the site keeps the first two in the claim's record and the
# third on a page of its own.
F_DEF = {"name": "Ex.f", "kind": "def", "fingerprint": "fp:f-1", "defined_by": "equations",
         "equation_names": ["Ex.f.eq_1", "Ex.f.eq_2", "Ex.f.eq_3"],
         "equations": [equation("Ex.f", 1, "Ex.f 0 = 0"), equation("Ex.f", 2, "Ex.f 1 = 1")],
         "equations_more": [{"name": "Ex.f.eq_3", "key": K_PAGE}]}
F_PAGE = {"definition": "Ex.f", "equations": [equation("Ex.f", 3, "Ex.f 2 = 1")]}
F_TYPE = {"binders": [{"id": "/", "name": "x", "role": "forall",
                       "type": pp("/0", "Nat", seg("Nat"))}],
          "conclusion": pp("/1", "Nat", seg("Nat")), "closure": [], "fingerprint": "fp:f-1"}


def is_even(fp="fp:even-1"):
    """A definition as the declaration store of a full assessment records it."""
    return {"name": "Ex.IsEven", "kind": "def", "fingerprint": fp, "defined_by": "body",
            "uses": [], "params": [{"id": "/", "name": "n", "binder": "explicit",
                                    "type": pp("/0", "Nat", seg("Nat"))}],
            "body": pp("/1", "∃ k, n = 2 * k",
                       seg("∃ ", "k", ", ", ("n", {"var": 0}), " = 2 * ", "k"),
                       [{"id": "/1/0/0", "from": 0, "to": 6},
                        {"id": "/1/1/1/0/0/0", "from": 3, "to": 6}])}


TRI = {"name": "Ex.tri", "kind": "def", "fingerprint": "fp:tri-1", "defined_by": "equations",
       "uses": [], "equation_names": ["Ex.tri.eq_1", "Ex.tri.eq_2"],
       "equations": [equation("Ex.tri", 1, "Ex.tri 0 = 0"),
                     equation("Ex.tri", 2, "Ex.tri (n + 1) = Ex.tri n + (n + 1)")]}

EST = {"binders": [
    {"id": "/", "name": "ε", "role": "forall", "type": pp("/0", "ℝ", seg("ℝ"))},
    {"id": "/1", "name": "hε", "role": "hypothesis",
     "type": pp("/1/0", "0 < ε", seg("0", " < ", ("ε", {"var": 0})))},
    {"id": "/1/1", "name": "hC", "role": "hypothesis",
     "type": pp("/1/1/0", "C ≥ 0", seg("C ≥ 0"))}],
    "conclusion": pp("/1/1/1", "|u| ≤ ε * |f| + C / ε", seg("|u| ≤ ε * |f| + C / ε")),
    "closure": [], "fingerprint": "fp:est-1"}


# Ex.exists : ∃ u f, C u ∧ u 0 = 0 ∧ 0 ≤ f ∧ D u = f ∧ |u| ≤ 1 ∧ S f, the six clauses as
# sub-terms of one conclusion about the same two witnesses.
CLAUSES = ["Continuous u", "u 0 = 0", "0 ≤ f", "deriv u = f", "∀ x, |u x| ≤ 1",
           "HasCompactSupport f"]


def exists_statement():
    text = " ∧ ".join(CLAUSES)
    segs, terms = [], []
    for i, c in enumerate(CLAUSES):
        if i:
            segs.append({"t": " ∧ "})
        terms.append({"id": "/1/1" + "/1" * i + "/0", "from": len(segs), "to": len(segs) + 1})
        segs.append({"t": c})
    body = pp("/1/1", text, segs, terms)
    leaf = {"leaf": body}
    tree = {"op": "exists", "var": 0, "name": "u", "id": "/", "type": pp("/0", "ℝ → ℝ", seg("ℝ → ℝ")),
            "args": [{"op": "exists", "var": 1, "name": "f", "id": "/1",
                      "type": pp("/1/0", "ℝ → ℝ", seg("ℝ → ℝ")), "args": [leaf]}]}
    return {"binders": [], "conclusion": pp("/", "∃ u f, " + text, seg("∃ u f, " + text)),
            "tree": tree, "closure": [], "fingerprint": "fp:exists-1"}


def make_build(work, even_fp="fp:even-1"):
    data = work / "site" / "data"
    for d in ("claims", "decls", "expansions"):
        (data / d).mkdir(parents=True, exist_ok=True)
    src = work / "sources" / "P"
    src.mkdir(parents=True, exist_ok=True)
    (src / "paper.tex").write_text(PAPER, encoding="utf-8")
    for key, part in ((K_GOOD, GOOD_AT_N), (K_BELOW, BELOW_AT), (K_PAGE, F_PAGE)):
        (data / "expansions" / f"{key}.json").write_text(json.dumps(part))
    for key, rec in ((D_EVEN, is_even(even_fp)), (D_TRI, TRI),
                     ("f6" * 12, {"name": "Ex.Good", "kind": "def", "fingerprint": "fp:Good"}),
                     ("a7" * 12, {"name": "Ex.Below", "kind": "def", "fingerprint": "fp:Below"})):
        (data / "decls" / f"{key}.json").write_text(json.dumps(rec))

    def chunk(cid, number, kind, key, lines, **extra):
        return {"id": cid, "paper": "P", "number": number, "kind": kind, "key": key,
                "source_sha256": "s-" + key, "links": [], "suggestions": [], "clauses": [],
                "decls": {}, "anchor": {"file": "paper.tex", "label": key},
                "excerpt": {"file": "paper.tex", "start_line": lines[0], "end_line": lines[1]},
                **extra}
    claims = [
        chunk("P:def:even", "Definition 1.1", "definition", "def:even", (5, 7),
              clauses=[{"name": "definition", "spec": None, "defs": ["Ex.IsEven", "Ex.tri"]}],
              decls={"Ex.IsEven": D_EVEN, "Ex.tri": D_TRI}),
        chunk("P:thm:good", "Theorem 2.1", "theorem", "thm:good", (9, 11),
              links=[{"name": "Ex.good", "fingerprint": "fp:good-1", "statement": GOOD},
                     {"name": "Ex.f", "fingerprint": "fp:f-1", "statement": F_TYPE,
                      "definition": F_DEF}]),
        chunk("P:eq:est", "Equation (1)", "equation", "eq:est", (15, 17),
              clauses=[{"name": "statement", "spec": "Ex.est_spec", "statement": EST}]),
        chunk("P:thm:exists", "Theorem 2.3", "theorem", "thm:exists", (21, 31),
              links=[{"name": "Ex.exists", "fingerprint": "fp:exists-1",
                      "statement": exists_statement()}]),
    ]
    for c in claims:
        (data / "claims" / f"{c['key'].replace(':', '_')}.json").write_text(json.dumps(c))
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "release": "v-1",
        "project": {"name": "ex", "commit": "abc123"},
        "papers": [{"id": "P", "title": "Synthetic", "revision": "abc123"}],
        "claims": [{"id": c["id"], "paper": "P", "number": c["number"], "kind": c["kind"],
                    "file": f"{c['key'].replace(':', '_')}.json"} for c in claims]}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "def", "module": "Ex.Basic"}
         for n in ("Ex.IsEven", "Ex.tri", "Ex.good", "Ex.f", "Ex.est_spec", "Ex.exists")]))
    return Snapshot(data)


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w)
    return w


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def opened(work):
    return wsp.open_for(work, WHO, "informed", sources=Snapshot(work / "site" / "data").sources())


def reading(work, p, claim):
    return wsp.view(wsp.read(p), Snapshot(work / "site" / "data"))["claims"][claim]["reading"]


def region(a, b=None, **cols):
    return {"file": "paper.tex", "start_line": a, "end_line": b or a, **cols}


# -- the Lean side ---------------------------------------------------------------------------

def test_a_sub_term_inside_an_expansion_or_a_later_page_of_equations_is_found(work):
    snap = Snapshot(work / "site" / "data")
    st = rq._statements(snap, "P:thm:good")
    good, f = st["Ex.good"], st["Ex.f"]
    # The claim's record holds references only: without the stored parts nothing is found.
    assert sy.term_by_id(good, "/1=/1") is None
    assert sy.term_by_id(f, "Ex.f.eq_3:/1") is None
    # With them: the expansion at n, the one nested in it, and the third equation.
    assert sy.term_by_id(good, "/1=/1", snap.part) == "Ex.Below n i"
    assert sy.term_by_id(good, "/1=/1=/", snap.part) == "i ≤ n"
    assert sy.term_by_id(good, "/1=/1=/1", snap.part) == "n"
    assert sy.term_by_id(f, "Ex.f.eq_3:/", snap.part) == "Ex.f 2 = 1"
    assert sy.term_by_id(f, "Ex.f.eq_2:/", snap.part) == "Ex.f 1 = 1"
    assert sy.term_by_id(good, "/1=/9", snap.part) is None
    # An expansion written inline (a build's evidence, before the site stores it apart) is
    # searched as it is.
    inline = {**good, "conclusion": {**good["conclusion"], "expansions": [
        {**GOOD_AT_N, "body": {**GOOD_AT_N["body"], "expansions": [BELOW_AT]}}]}}
    assert sy.term_by_id(inline, "/1=/1=/") == "i ≤ n"

    p = opened(work)
    wsp.update(p, [
        put({"kind": "requirement", "claim": "Theorem 2.1", "local_id": "r1", "form": "condition",
             "text": "every entry of the profile is at most n"}),
        put({"id": "a-below", "kind": "alignment", "claim": "Theorem 2.1", "requirements": ["r1"],
             "lean": [{"decl": "Ex.good", "at": "/1=/1=/"}, {"decl": "Ex.f", "at": "Ex.f.eq_3:/"}]}),
    ], snap)
    a = reading(work, p, "P:thm:good")["alignments"][0]
    assert [t["target"] for t in a["lean"]] == ["i ≤ n", "Ex.f 2 = 1"]
    assert a["currency"]["state"] == "current"
    with pytest.raises(wsp.WorkspaceError, match="no sub-term with the identity"):
        wsp.update(p, [put({"kind": "alignment", "claim": "Theorem 2.1", "requirements": ["r1"],
                            "lean": [{"decl": "Ex.good", "at": "/1=/7"}]})], snap)


def test_the_definitions_of_a_claim_that_only_defines_are_targets(work):
    """Definition 1.1's two sentences align separately with the two definitions, down to a
    sub-term of the first's body, a parameter, and an equation of the second."""
    snap = Snapshot(work / "site" / "data")
    line = PAPER.splitlines().index(
        r"A number $n$ is even if $n = 2k$ for some $k$. The number $T_n$ is $0 + 1 + \dots + n$."
    ) + 1
    cut = PAPER.splitlines()[line - 1].index("The") + 1
    p = opened(work)
    wsp.update(p, [
        put({"kind": "requirement", "claim": "Definition 1.1", "local_id": "even",
             "form": "definition", "text": "n is even if n = 2k for some k"}),
        put({"id": "p-even", "kind": "fragment", "claim": "Definition 1.1", "requirement": "even",
             "role": "statement", "region": region(line, end_column=cut)}),
        put({"kind": "requirement", "claim": "Definition 1.1", "local_id": "tri",
             "form": "definition", "text": "T_n = 0 + 1 + ... + n"}),
        put({"id": "p-tri", "kind": "fragment", "claim": "Definition 1.1", "requirement": "tri",
             "role": "statement", "region": region(line, start_column=cut)}),
        put({"id": "a-even", "kind": "alignment", "claim": "Definition 1.1",
             "fragments": ["p-even"],
             "lean": [{"decl": "Ex.IsEven", "var": "n"},
                      {"decl": "Ex.IsEven", "at": "/1/1/1/0/0/0"}]}),
        put({"id": "a-tri", "kind": "alignment", "claim": "Definition 1.1", "fragments": ["p-tri"],
             "relation": "alternative representation",
             "lean": [{"decl": "Ex.tri", "at": "Ex.tri.eq_2:/"}],
             "note": "a recursion instead of the sum"}),
    ], snap)
    rd = reading(work, p, "P:def:even")
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-even"]["requirements"] == ["even"]
    assert [t["target"] for t in al["a-even"]["lean"]] == ["n", "n = 2 * k"]
    assert al["a-tri"]["lean"][0]["target"] == "Ex.tri (n + 1) = Ex.tri n + (n + 1)"
    assert all(t["fingerprint"] and t["build"] == "built" for a in al.values() for t in a["lean"])
    assert {a["currency"]["state"] for a in al.values()} == {"current"}
    texts = {r["local_id"]: r["fragments"]["governing"][0]["region"]["text"]
             for r in rd["requirements"]}
    assert texts["even"].endswith("for some $k$. ") and texts["tri"].startswith("The number")
    # A changed definition puts its alignment, and the requirement it concerns, out of date.
    make_build(work, even_fp="fp:even-2")
    rd = reading(work, p, "P:def:even")
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-even"]["currency"]["state"] == "stale"
    assert al["a-tri"]["currency"]["state"] == "current"
    assert {r["local_id"]: r["currency"]["state"] for r in rd["requirements"]} == \
        {"even": "stale", "tri": "current"}


# -- the paper side --------------------------------------------------------------------------

EST_READING = [
    put({"kind": "requirement", "claim": "Equation (1)", "local_id": "r1", "form": "there is",
         "binds": ["C"], "independent_of": ["ε"], "text": "a constant C, independent of ε"}),
    put({"kind": "requirement", "claim": "Equation (1)", "local_id": "r1.1", "parent": "r1",
         "form": "for every", "binds": ["ε"], "text": "for every ε > 0"}),
    put({"kind": "requirement", "claim": "Equation (1)", "local_id": "r1.1.1", "parent": "r1.1",
         "form": "conclusion", "text": "|u| ≤ ε|f| + C/ε"}),
    put({"id": "p-eps", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1.1",
         "role": "quantifier domain", "region": region(14)}),
    put({"id": "p-dep", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1",
         "role": "constant dependence", "region": region(18)}),
    put({"id": "p-est", "kind": "fragment", "claim": "Equation (1)", "requirement": "r1.1.1",
         "role": "statement", "region": region(15, 17)}),
]


def test_one_passage_aligns_with_several_targets_and_several_passages_with_one(work):
    snap = Snapshot(work / "site" / "data")
    p = opened(work)
    wsp.update(p, EST_READING + [
        # One passage, two parts of the Lean: the quantifier's variable and its domain.
        put({"id": "a-eps", "kind": "alignment", "claim": "Equation (1)", "fragments": ["p-eps"],
             "lean": [{"decl": "Ex.est_spec", "var": "ε"},
                      {"decl": "Ex.est_spec", "binder": "hε"}]}),
        # Three passages, one conclusion: the estimate reads with its quantifier and the
        # dependence of its constant, each kept with its own source.
        put({"id": "a-est", "kind": "alignment", "claim": "Equation (1)",
             "fragments": ["p-est", "p-eps", "p-dep"],
             "lean": [{"decl": "Ex.est_spec", "conclusion": True}]}),
    ], snap)
    rd = reading(work, p, "P:eq:est")
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-eps"]["fragments"] == ["p-eps"] and al["a-eps"]["requirements"] == ["r1.1"]
    assert [t["target"] for t in al["a-eps"]["lean"]] == ["ε", "hε : 0 < ε"]
    assert al["a-est"]["fragments"] == ["p-est", "p-eps", "p-dep"]
    assert al["a-est"]["requirements"] == ["r1.1.1", "r1.1", "r1"]
    assert {a["currency"]["state"] for a in al.values()} == {"current"}
    lines = "\n".join(rq.lines(rd))
    assert "r1.1 on paper.tex:14 -> Ex.est_spec (variable 0: ε); Ex.est_spec (the type of " \
           "variable 1: hε : 0 < ε)" in lines
    assert "on paper.tex:15-17; paper.tex:14; paper.tex:18 -> Ex.est_spec (the conclusion" in lines
    # Only a passage that governs the reading can be named, and only the claim's own.
    wsp.update(p, [put({"id": "p-maybe", "kind": "fragment", "claim": "Equation (1)",
                        "requirement": "r1", "role": "context", "state": "proposed",
                        "region": region(13)})], snap)
    for frags, msg in ((["p-maybe"], "suggested passage"), (["p-none"], "not a passage"),
                       (["a-eps"], "not a passage"), ([7], "list of the ids")):
        with pytest.raises(wsp.WorkspaceError, match=msg):
            wsp.update(p, [put({"kind": "alignment", "claim": "Equation (1)", "fragments": frags,
                                "lean": [{"decl": "Ex.est_spec"}]})], snap)
    wsp.update(p, [put({"kind": "requirement", "claim": "Definition 1.1", "local_id": "d",
                        "text": "a definition"}),
                   put({"id": "p-def", "kind": "fragment", "claim": "Definition 1.1",
                        "requirement": "d", "role": "statement", "region": region(6)})], snap)
    with pytest.raises(wsp.WorkspaceError, match="a passage of P:def:even, not P:eq:est"):
        wsp.update(p, [put({"kind": "alignment", "claim": "Equation (1)", "fragments": ["p-def"],
                            "lean": [{"decl": "Ex.est_spec"}]})], snap)
    # A passage an alignment names is kept: it can be marked removed, with why, not deleted;
    # the alignment then rests on a passage that no longer governs the reading.
    dep = wsp.read(p)["records"]["p-dep"]
    with pytest.raises(wsp.WorkspaceError, match="a passage of alignment\\(s\\) a-est"):
        wsp.update(p, [{"op": "delete", "id": "p-dep", "base_rev": dep["rev"]}], snap)
    wsp.update(p, [put({**{k: dep[k] for k in ("id", "kind", "claim", "requirement", "role")},
                        "region": {k: dep["region"][k] for k in ("file", "start_line")},
                        "state": "removed", "why_removed": "the constant is fixed earlier"},
                       dep["rev"])], snap)
    rd = reading(work, p, "P:eq:est")
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-est"]["currency"] == {"state": "stale", "changes": [
        {"fragment": "p-dep", "was": "accepted", "now": "removed"}]}
    assert al["a-eps"]["currency"]["state"] == "current"
    # A changed passage puts the alignment that names it out of date, and its requirement once.
    (work / "sources" / "P" / "paper.tex").write_text(
        PAPER.replace(r"For every $\varepsilon > 0$,", r"For every $\varepsilon \in (0, 1]$,"),
        encoding="utf-8")
    rd = reading(work, p, "P:eq:est")
    al = {a["id"]: a for a in rd["alignments"]}
    assert al["a-eps"]["currency"]["state"] == "stale"
    assert [c.get("region") for c in al["a-eps"]["currency"]["changes"]] == ["paper.tex:14"]
    # The requirement lists the change once, though its passage and both alignments carry it.
    eps = next(r for r in rd["requirements"] if r["local_id"] == "r1.1")
    assert [c.get("region") for c in eps["currency"]["changes"] if "region" in c] == \
        ["paper.tex:14"]


def test_a_published_alignment_keeps_the_passages_it_names(work):
    snap = Snapshot(work / "site" / "data")
    p = opened(work)
    wsp.update(p, EST_READING + [
        put({"id": "a-eps", "kind": "alignment", "claim": "Equation (1)", "fragments": ["p-eps"],
             "lean": [{"decl": "Ex.est_spec", "binder": "hε"}]})], snap)
    rd, = pw.readings(work, snap, lambda cid: EVERYTHING, {"P:eq:est"})["P:eq:est"]
    a, = rd["alignments"]
    assert a["fragments"] == ["p-eps"] and a["requirements"] == ["r1.1"]
    assert a["currency"]["state"] == "current"
    assert "p-eps" in {f["id"] for f in rd["fragments"]}


# -- symbol links ----------------------------------------------------------------------------

def test_occurrences_are_counted_in_the_order_the_reader_typesets_them():
    excerpt = {"blocks": [
        {"p": [{"text": "A number "}, {"math": "n"}, {"text": " is even if "},
               {"math": "n = 2k"}, {"children": [{"math": "T_n"}], "style": "em"}]},
        {"math": "n + \\nu", "display": True},
        {"list": "itemize", "items": [{"blocks": [{"p": [{"math": "\\nuexample n"}]}]}]}]}
    pieces = sy.math_pieces(excerpt, None)
    assert pieces == ["n", "n = 2k", "T_n", "n + \\nu", "\\nuexample n"]
    assert sy.occurrences(pieces, "n") == 5
    assert sy.occurrences(pieces, "\\nu") == 1, "not the start of \\nuexample"
    assert sy.math_pieces(None, "For $a$ and $b$, $a + b$.") == ["$a$", "$b$", "$a + b$"]


def test_two_objects_printed_with_one_symbol_are_linked_apart():
    pieces = ["n", "n = 2k", "T_n"]
    whole = sy.symbol_record("n", pieces)
    assert whole == {"tex": "n", "occurrence": "all"}
    first = sy.symbol_record("n", pieces, [2, 1], "n, the number defined")
    assert first == {"tex": "n", "occurrence": [1, 2], "of": 3,
                     "object": "n, the number defined"}
    index = sy.symbol_record("n", pieces, [3], "n, the index of T")
    for occ, obj, msg in (([4], "x", "occurs 3 time"), ([0], "x", "no occurrence 0"),
                          ([1], None, "name it"), (["one"], "x", "its number"),
                          (None, " ", "name the paper object")):
        with pytest.raises(sy.SymbolError, match=msg):
            sy.symbol_record("n", pieces, occ, obj)

    def link(sym, by="human:A"):
        return {"claim": "P:x", "symbol": sym, "by": by}
    links = [link(first)]
    # Another object's occurrences may not overlap; the same object's link is replaced.
    assert sy._clashes(links, "P:x", index) == []
    assert sy._clashes(links, "P:x", sy.symbol_record("n", pieces, [2, 3], "n, the index of T")) \
        == links
    assert sy._clashes(links, "P:x", whole) == links, "every occurrence overlaps"
    assert sy._clashes(links, "P:x", sy.symbol_record("n", pieces, [1], "n, the number defined")) \
        == []
    assert sy._clashes([link(whole)], "P:x", index) == [link(whole)]
    assert sy._clashes([link(whole)], "P:x", whole) == [], "the old rule: one link per symbol"
    assert sy._clashes(links, "P:y", index) == [] and sy._clashes(links, "P:x", {
        "tex": "k", "occurrence": "all"}) == []
    assert sy.symbol_text(first) == "n (n, the number defined) at occurrence 1, 2 of 3"


def test_a_link_into_a_definition_a_claim_only_defines_is_read_in_that_definition():
    """The build shows a link of a claim that only defines in the definition it points into,
    and says why it no longer holds when the definition says something else."""
    text = "A number $n$ is even if $n = 2k$ for some $k$."
    rec = is_even()
    lean = {"specs": {}, "decls": {"Ex.IsEven": rec}}
    assert sy.spec_of(lean, "Ex.IsEven")["definition"] is rec
    assert sy.claim_decls({"clauses": [{"spec": None, "defs": ["Ex.IsEven", "Ex.tri"]},
                                       {"spec": "Ex.s", "defs": ["Ex.other"]}]}) == \
        ({"Ex.s"}, {"Ex.IsEven", "Ex.tri"})

    def why(lean_end, target, **pins):
        display = {"symbols": [{
            "claim": "P:def:even", "symbol": {"tex": "n", "occurrence": [1], "of": 2,
                                              "object": "the number"},
            "lean": {"decl": "Ex.IsEven", **lean_end}, "by": "human:A",
            "pins": {"statement": "fp:even-1", "source": sha256_text(text), "target": target,
                     "ids": sy.IDS, **pins}}]}
        [ln] = symbol_links(display, "P:def:even", text, lean)
        assert ln["symbol"]["occurrence"] == [1] and ln["symbol"]["object"] == "the number"
        return ln["stale_because"]
    assert why({"var": 0}, "n", binder_id="/") == []
    assert why({"at": "/1/1/1/0/0/0"}, "n = 2 * k") == []
    assert why({"at": "/1/1/1/0/0/0"}, "n = 2 * j") == ["target"]
    lean["decls"]["Ex.IsEven"] = is_even("fp:even-2")
    assert why({"at": "/1/1/1/0/0/0"}, "n = 2 * k") == ["statement"]


def test_six_clauses_of_one_existence_statement_align_with_the_same_two_witnesses(work):
    """Each clause keeps its own source line; all six are about the witnesses u and f the one
    `there is` produces, and each aligns with its own part of the one Lean conclusion."""
    snap = Snapshot(work / "site" / "data")
    first = PAPER.splitlines().index(r"\item $u$ is continuous,") + 1
    ops = [put({"kind": "requirement", "claim": "Theorem 2.3", "local_id": "e", "form": "there is",
                "binds": ["u", "f"], "text": "a function u and a source f"}),
           put({"kind": "fragment", "claim": "Theorem 2.3", "requirement": "e", "role": "statement",
                "region": region(first - 2)}),
           put({"id": "a-e", "kind": "alignment", "claim": "Theorem 2.3", "requirements": ["e"],
                "lean": [{"decl": "Ex.exists", "var": "u"}, {"decl": "Ex.exists", "var": "f"}]})]
    for i, clause in enumerate(CLAUSES, 1):
        ops += [put({"kind": "requirement", "claim": "Theorem 2.3", "local_id": f"e.{i}",
                     "parent": "e", "form": "condition", "text": f"clause ({i})"}),
                put({"id": f"p-{i}", "kind": "fragment", "claim": "Theorem 2.3",
                     "requirement": f"e.{i}", "role": "statement",
                     "region": region(first + i - 1)}),
                put({"id": f"a-{i}", "kind": "alignment", "claim": "Theorem 2.3",
                     "fragments": [f"p-{i}"],
                     "lean": [{"decl": "Ex.exists", "at": "/1/1" + "/1" * (i - 1) + "/0"}]})]
    p = opened(work)
    wsp.update(p, ops, snap)
    rd = reading(work, p, "P:thm:exists")
    assert [(w["binds"], w["scope"], w["conditions"]) for w in rd["witnesses"]] == \
        [(["u", "f"], "produced", [f"e.{i}" for i in range(1, 7)])]
    al = {a["id"]: a for a in rd["alignments"]}
    assert [t["target"] for t in al["a-e"]["lean"]] == ["u", "f"]
    for i, clause in enumerate(CLAUSES, 1):
        r = next(x for x in rd["requirements"] if x["local_id"] == f"e.{i}")
        assert r["fragments"]["governing"][0]["region"]["text"] == PAPER.splitlines()[first + i - 2]
        assert al[f"a-{i}"]["lean"][0]["target"] == clause
        assert al[f"a-{i}"]["requirements"] == [f"e.{i}"]
    assert {a["currency"]["state"] for a in al.values()} == {"current"}
