"""Computed hints where an aligned paper expression and its Lean expression differ in quantity
(#500, part of #111), on the structure fixture's built data (`web/tests/fixtures/structure/data`,
no Lean).

`Shape.jet_lower` states `∀ f S n C, JetBound f S (n + 5) C → JetBound f S (n + 4) C`, and the
build expands `JetBound` at both applications. The build's copy of the paper's source here writes
the claim with `m` for the Lean's `n` ("If the first $m + 5$ differences …, so are the first
$m + 4$"), so that the paper's variable is matched with the Lean's only through an alignment. A
hint is a pointer for the auditor: it changes no status and no review record, the semantic
summary does not count it, and a published audit does not carry it.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import estimates as est
from prooflens import expressions as ex
from prooflens import published_work as pw
from prooflens import requirements as rq
from prooflens import review_cli as rc
from prooflens import semantic
from prooflens import workspace as wsp
from prooflens.config import Publish
from prooflens.targets import Snapshot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "tests" / "fixtures" / "structure" / "data"
PAPER = ROOT / "tests" / "fixtures" / "structure" / "paper" / "main.tex"
WHO = rc.parse_reviewer("human:A-Auditor")
JET, BOUND = "P:thm:jet", "P:thm:bound-once"
DECL = "Shape.jet_lower"
JET_LINE = ("If the first $n + 5$ differences of $f$ are bounded by $C$ on $S$, so are the first "
            "$n + 4$.")
IN_M = JET_LINE.replace("$n + 5$", "$m + 5$").replace("$n + 4$", "$m + 4$")
H_ARG = "/1/1/1/1/0/0/1"          # n + 5, the argument k of JetBound in h's type
IN_EXPANSION = "/1/1/1/1/0=/1/0/1"  # n + 5 inside JetBound expanded at h's arguments
EVERYTHING = Publish(pdf=True, source_text=True, lean=True, reviews=True)
CLOSED = Publish(pdf=False, source_text=False, lean=False, reviews=False)


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    shutil.copytree(DATA, w / "site" / "data")
    src = PAPER.read_text(encoding="utf-8")
    assert JET_LINE in src
    (w / "sources" / "P").mkdir(parents=True)
    (w / "sources" / "P" / "main.tex").write_text(src.replace(JET_LINE, IN_M), encoding="utf-8")
    return w


def snap_of(work):
    return Snapshot(work / "site" / "data")


def put(rec, base=None):
    return {"op": "put", "record": rec, **({"base_rev": base} if base is not None else {})}


def line_of(text):
    lines = PAPER.read_text(encoding="utf-8").splitlines()
    return next(i for i, t in enumerate(lines, 1) if text in t)


def region(line):
    return {"file": "main.tex", "start_line": line}


def jet_reading(align_m=True):
    """For every m (aligned with Lean's n); the assumption, on m + 5; the conclusion, on m + 4."""
    at = line_of(JET_LINE)
    ops = [put({"id": "r-m", "kind": "requirement", "claim": JET, "local_id": "m",
                "form": "for every", "binds": ["m"], "text": "for every m"}),
           put({"id": "r-h", "kind": "requirement", "claim": JET, "local_id": "m.h",
                "parent": "m", "form": "assumption",
                "text": "the first m + 5 differences of f are bounded by C on S"}),
           put({"id": "r-c", "kind": "requirement", "claim": JET, "local_id": "m.c",
                "parent": "m", "form": "conclusion", "text": "so are the first m + 4"}),
           put({"id": "p-h", "kind": "fragment", "claim": JET, "requirement": "m.h",
                "role": "statement", "region": region(at)}),
           put({"id": "p-c", "kind": "fragment", "claim": JET, "requirement": "m.c",
                "role": "statement", "region": region(at)})]
    if align_m:
        ops.append(put({"id": "a-m", "kind": "alignment", "claim": JET, "requirements": ["m"],
                        "lean": [{"decl": DECL, "var": "n"}]}))
    return ops


def align(aid, req, expression, **target):
    return put({"id": aid, "kind": "alignment", "claim": JET, "requirements": [req],
                "expression": expression, "lean": [{"decl": DECL, **target}]})


def opened(work, ops):
    p = wsp.open_for(work, WHO, "informed", sources=snap_of(work).sources())
    wsp.update(p, ops, snap_of(work))
    return p


def block(work, p, claim=JET):
    return wsp.view(wsp.read(p), snap_of(work))["claims"][claim]["reading"]["estimates"]


def by_alignment(hints):
    return {h["alignment"]: h for h in hints if h.get("alignment")}


# -- the TeX reader and the normal form ----------------------------------------------------------

REAL = {"k": "type", "name": "real"}
NAT = {"k": "type", "name": "nat"}


def var(i, name):
    return {"k": "var", "var": i, "name": name}


def num(v, t=REAL):
    return {"k": "num", "value": str(v), "in": t}


def op(o, *args, t=REAL):
    return {"k": "op", "op": o, "args": list(args), "in": t}


AB = {"a": "v:0", "b": "v:1"}
AB_LEAN = {"v:0": "a", "v:1": "b"}


def test_the_tex_reader_gives_the_probes_vocabulary():
    assert ex.read_tex("m + 4") == {"k": "op", "op": "add", "args": [
        {"k": "local", "name": "m", "tex": "m"}, {"k": "num", "value": "4"}]}
    two = ex.read_tex(r"2\left(a + b\right)")
    assert two["op"] == "mul" and two["args"][1]["op"] == "add"
    assert ex.read_tex(r"\frac{C}{\varepsilon}")["args"][1] == {
        "k": "local", "name": "ε", "tex": r"\varepsilon"}
    assert ex.read_tex(r"\|u\| + |v|")["args"][0]["op"] == "norm"
    assert ex.read_tex("C_{\\varepsilon} x_1^2")["args"][0]["name"] == "C_ε"
    for tex, said in ((r"\sum_k a_k", r"unsupported: \sum"), (r"n \le C", r"unsupported: \le"),
                      ("f(x)", "unsupported: f(…) may be a function applied or a product"),
                      (r"\sqrt{n}", r"unsupported: \sqrt"),
                      ("(a + b", "unsupported: brackets that do not match"),
                      ("m +", "unsupported: the expression ends too early")):
        with pytest.raises(ex.Unsupported) as e:
            ex.read_tex(tex)
        assert str(e.value) == said


def test_equal_forms_give_no_hint_and_a_multiple_gives_a_coefficient_hint():
    expanded = op("add", op("mul", num(2), var(0, "a")), op("mul", num(2), var(1, "b")))
    assert ex.compare("2(a+b)", expanded, AB, AB_LEAN)["outcome"] == "same"
    res = ex.compare("2(a+b)", op("add", var(0, "a"), var(1, "b")), AB, AB_LEAN)
    assert (res["outcome"], res["kind"], res["feature"], res["factor"]) == \
        ("differs", "coefficient", "weight", "1/2")
    assert (res["paper_normal"], res["lean_normal"]) == ("2·a + 2·b", "a + b")
    # A rename through the correspondence is no difference; an index offset is.
    mn, n = {"m": "v:2"}, {"v:2": "n"}
    assert ex.compare("m + 4", op("add", var(2, "n"), num(4, NAT), t=NAT), mn, n)["outcome"] == \
        "same"
    res = ex.compare("m + 4", op("add", var(2, "n"), num(5, NAT), t=NAT), mn, n)
    assert (res["kind"], res["feature"], res["difference"]) == ("offset", "index offset", "1")
    # Powers written as products, and a quotient by a monomial, with its divisor kept.
    cn = {"C": "v:0", "n": "v:1", "ε": "v:2"}
    cn_lean = {"v:0": "C", "v:1": "n", "v:2": "ε"}
    lean = op("add", op("mul", var(0, "C"), op("mul", var(1, "n"), var(1, "n"))), var(1, "n"))
    assert ex.compare("C n^2 + n", lean, cn, cn_lean)["outcome"] == "same"
    res = ex.compare(r"\frac{C}{\varepsilon}", op("div", var(0, "C"), var(2, "ε")), cn, cn_lean)
    assert res["outcome"] == "same" and res["conditions"] == ["ε ≠ 0"]
    res = ex.compare("C n^3", op("mul", var(0, "C"), op("pow", var(1, "n"), num(2, NAT))), cn,
                     cn_lean)
    assert res["kind"] == "power"


def test_what_is_not_this_arithmetic_is_not_compared():
    n = {"m": "v:2"}
    # Subtraction in ℕ is cut off at 0; division in ℕ rounds.
    res = ex.compare("m - 1", op("sub", var(2, "n"), num(1, NAT), t=NAT), n, {"v:2": "n"})
    assert res == {"outcome": "not compared", "reason": "Lean's subtraction in ℕ is cut off at 0"}
    res = ex.compare("m / 2", op("div", var(2, "n"), num(2, NAT), t=NAT), n, {"v:2": "n"})
    assert res["reason"] == "Lean's division in ℕ is not exact"
    # A variable outside the correspondence, on either side.
    res = ex.compare("k + 4", op("add", var(2, "n"), num(4, NAT), t=NAT), n, {"v:2": "n"})
    assert res["reason"] == "the paper's k is aligned with no Lean variable"
    res = ex.compare("m + 4", op("add", var(3, "k"), num(4, NAT), t=NAT), n, {"v:2": "n"})
    assert res["reason"] == "Lean's k is aligned with no variable of the paper"


# -- hints on the structure fixture -------------------------------------------------------------

def test_m_plus_4_against_jetbound_at_n_plus_5_is_an_index_offset(work):
    p = opened(work, jet_reading() + [align("a-x", "m.c", "m + 4", binder="h"),
                                     align("a-y", "m.c", "m + 4", at=H_ARG),
                                     align("a-z", "m.c", "m + 4", at=IN_EXPANSION)])
    b = block(work, p)
    hs = by_alignment(b["hints"])
    h = hs["a-x"]
    assert (h["kind"], h["feature"], h["basis"], h["difference"]) == \
        ("offset", "index offset", "computed hint", "1")
    assert h["paper"] == {"text": "m + 4", "normal": "m + 4"}
    assert h["lean"] == {"text": "n + 5", "normal": "n + 5", "at": H_ARG}
    assert h["variables"] == [{"paper": "m", "lean": "n", "via": "alignment a-m"}]
    assert h["target"] == {"decl": DECL, "binder": 4} and h["requirements"] == ["m.c"]
    # It names the definition, the argument the expression stands in, and its expansion.
    assert h["definition"] == {
        "name": "Shape.JetBound", "expansion": "/1/1/1/1/0=", "parameter": "k",
        "expanded": "∀ (j : Nat), j ≤ n + 5 → ∀ (x : Nat), S x → f j x ≤ C"}
    assert h["text"] == ("The paper's m + 4 and Lean's n + 5 differ by 1: Lean's is larger (m as "
                         "n; in Shape.jet_lower, the argument k of Shape.JetBound, which expands "
                         "to ∀ (j : Nat), j ≤ n + 5 → ∀ (x : Nat), S x → f j x ≤ C).")
    # The argument named directly, and the same expression inside the expansion.
    assert hs["a-y"]["definition"]["parameter"] == "k" and hs["a-y"]["kind"] == "offset"
    assert hs["a-z"]["kind"] == "offset"
    assert hs["a-z"]["definition"] == {
        "name": "Shape.JetBound", "expansion": "/1/1/1/1/0=",
        "expanded": "∀ (j : Nat), j ≤ n + 5 → ∀ (x : Nat), S x → f j x ≤ C"}
    # The terminal shows the hint and the paper expression on the alignment.
    text = "\n".join(rq.lines(wsp.view(wsp.read(p), snap_of(work))["claims"][JET]["reading"]))
    assert "m.c, the paper's m + 4 -> Shape.jet_lower" in text
    assert "hint: The paper's m + 4 and Lean's n + 5 differ by 1" in text


def test_a_rename_alone_and_the_same_quantity_give_no_hint(work):
    p = opened(work, jet_reading() + [align("a-h", "m.h", "m + 5", binder="h"),
                                     align("a-c", "m.c", "m + 4", conclusion=True)])
    assert by_alignment(block(work, p)["hints"]) == {}


def test_an_unaligned_variable_is_not_compared(work):
    p = opened(work, jet_reading(align_m=False) + [align("a-x", "m.c", "m + 4", binder="h")])
    h, = [h for h in block(work, p)["hints"] if h.get("alignment")]
    assert (h["kind"], h["reason"]) == ("not compared",
                                        "the paper's m is aligned with no Lean variable")
    assert "feature" not in h and h["paper"] == {"text": "m + 4"}
    assert h["lean"] == {"text": "Shape.JetBound f S (n + 5) C"}


def test_a_symbol_link_matches_the_variables_too(work):
    f = next((work / "site" / "data" / "claims").glob("P_thm_jet-*.json"))
    ch = json.loads(f.read_text())
    ch["symbols"] = [{"symbol": {"tex": "m", "occurrence": "all"}, "by": "human:B-Linker",
                      "lean": {"decl": DECL, "var": 2}, "stale": False, "stale_because": []}]
    f.write_text(json.dumps(ch))
    p = opened(work, jet_reading(align_m=False) + [align("a-x", "m.c", "m + 4", binder="h")])
    h = by_alignment(block(work, p)["hints"])["a-x"]
    assert h["kind"] == "offset"
    assert h["variables"] == [{"paper": "m", "lean": "n", "via": "symbol link by human:B-Linker"}]
    # A stale link matches nothing.
    ch["symbols"][0]["stale"] = True
    f.write_text(json.dumps(ch))
    h = by_alignment(block(work, p)["hints"])["a-x"]
    assert h["kind"] == "not compared"


def test_an_unsupported_construct_says_so_and_a_relation_is_read_through_its_side(work):
    at = line_of("There is a constant $C$ with")
    ops = [put({"id": "r-C", "kind": "requirement", "claim": BOUND, "local_id": "c",
                "form": "there is", "binds": ["C"], "text": "there is a constant C"}),
           put({"id": "r-n", "kind": "requirement", "claim": BOUND, "local_id": "c.n",
                "parent": "c", "form": "for every", "binds": ["n"], "text": "for every n"}),
           put({"id": "r-e", "kind": "requirement", "claim": BOUND, "local_id": "c.n.e",
                "parent": "c.n", "form": "conclusion", "text": "n ≤ C n² + n"}),
           put({"id": "p-e", "kind": "fragment", "claim": BOUND, "requirement": "c.n.e",
                "role": "statement", "region": region(at)}),
           put({"kind": "alignment", "claim": BOUND, "requirements": ["c"],
                "lean": [{"decl": "Shape.bound_once", "var": "C"}]}),
           put({"kind": "alignment", "claim": BOUND, "requirements": ["c.n"],
                "lean": [{"decl": "Shape.bound_once", "var": "n"}]}),
           put({"id": "a-rel", "kind": "alignment", "claim": BOUND, "requirements": ["c.n.e"],
                "expression": "C n^2 + n",
                "lean": [{"decl": "Shape.bound_once", "conclusion": True}]}),
           put({"id": "a-le", "kind": "alignment", "claim": BOUND, "requirements": ["c.n.e"],
                "expression": r"n \le C n^2 + n",
                "lean": [{"decl": "Shape.bound_once", "conclusion": True}]})]
    p = opened(work, ops)
    hs = by_alignment(block(work, p, BOUND)["hints"])
    # C n^2 + n is the right side of n ≤ C * (n * n) + n: the same polynomial, no hint.
    assert "a-rel" not in hs
    h = hs["a-le"]
    assert (h["kind"], h["reason"]) == ("not compared", r"unsupported: \le")
    # Both exact texts are kept.
    assert h["paper"]["text"] == r"n \le C n^2 + n"
    assert h["lean"]["text"] == "n ≤ C * (n * n) + n"


# -- the paper expression: verbatim in a governing passage ---------------------------------------

def test_the_expression_occurs_verbatim_in_a_governing_passage_or_the_alignment_goes_stale(work):
    p = opened(work, jet_reading())
    s = snap_of(work)
    with pytest.raises(wsp.WorkspaceError, match="does not occur in a passage that governs"):
        wsp.update(p, [align("a-x", "m.c", "n + 5", binder="h")], s)
    with pytest.raises(wsp.WorkspaceError, match="attach that passage"):
        wsp.update(p, [align("a-x", "m", "m + 4", binder="h")], s)
    wsp.update(p, [align("a-x", "m.c", "m + 4", binder="h")], s)
    assert wsp.currency(wsp.read(p), s)["a-x"]["state"] == "current"
    # The paper's source no longer prints m + 4 there: the alignment is out of date, and its
    # hint says so instead of comparing.
    f = work / "sources" / "P" / "main.tex"
    f.write_text(f.read_text().replace("so are the first $m + 4$", "so are the first $m + 3$"))
    cur = wsp.currency(wsp.read(p), s)["a-x"]
    assert cur["state"] == "stale"
    assert {"record": "a-x", "reason": "its paper expression no longer occurs in a passage that "
                                       "governs it"} in cur["changes"]
    h = by_alignment(block(work, p)["hints"])["a-x"]
    assert h["kind"] == "not compared" and "out of date" in h["reason"]


# -- dismissal --------------------------------------------------------------------------------

def test_a_dismissed_hint_is_listed_apart_with_its_reason(work):
    p = opened(work, jet_reading() + [align("a-x", "m.c", "m + 4", binder="h")])
    s = snap_of(work)
    dismiss = {"id": "f-d", "kind": "finding", "claim": JET, "requirement": "m.c",
               "difference": {"feature": "index offset", "paper": "m + 4", "lean": "n + 5",
                              "outcome": "no difference",
                              "why": "the assumption is one order stronger; the claim holds",
                              "hint": {"alignment": "a-x", "kind": "offset"}},
               "note": "dismissed"}
    with pytest.raises(wsp.WorkspaceError, match="not an alignment of P:thm:jet"):
        wsp.update(p, [put({**dismiss, "difference": {**dismiss["difference"],
                                                      "hint": {"alignment": "a-nope",
                                                               "kind": "offset"}}})], s)
    with pytest.raises(wsp.WorkspaceError, match="`kind` one of"):
        wsp.update(p, [put({**dismiss, "difference": {**dismiss["difference"],
                                                      "hint": {"alignment": "a-x",
                                                               "kind": "nonsense"}}})], s)
    wsp.update(p, [put(dismiss)], s)
    b = block(work, p)
    assert "a-x" not in by_alignment(b["hints"])
    d, = [h for h in b["settled_hints"] if h.get("alignment") == "a-x"]
    assert d["settled_by"] == "f-d"
    assert d["settled"] == {"finding": "f-d", "outcome": "no difference",
                            "why": "the assumption is one order stronger; the claim holds",
                            "by": "human:A-Auditor"}
    assert "hint dismissed by f-d (no difference, human:A-Auditor): The paper's m + 4" in \
        "\n".join(est.lines(b))
    # A dismissal superseded by a finding that dismisses nothing no longer settles it.
    wsp.update(p, [{"op": "submit", "id": "f-d", "base_rev": 1},
                   {"op": "supersede", "id": "f-d", "base_rev": 2, "reason": "reconsidered",
                    "record": {"id": "f-e", "claim": JET, "coverage": "partial",
                               "note": "one order more"}}], s)
    assert "a-x" in by_alignment(block(work, p)["hints"])


# -- where hints show, and what they change ----------------------------------------------------

def _digests(root: Path) -> dict[str, str]:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def _run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_hints_show_in_the_informed_packet_only_and_change_nothing(work, tmp_path, monkeypatch,
                                                                   capsys):
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, tmp_path))
    p = opened(work, jet_reading() + [align("a-x", "m.c", "m + 4", binder="h")])
    wid = wsp.read(p)["id"]
    before = _digests(work.parent)
    status = snap_of(work).chunk(JET)["status_code"]
    code, out, _ = _run(["workspace", "show", "--id", wid], capsys)
    assert code == 0 and "hint: The paper's m + 4 and Lean's n + 5 differ by 1" in out
    code, out, _ = _run(["compare", "Theorem 17", "--workspace", wid, "--json"], capsys)
    pk = json.loads(out)
    h, = [h for h in pk["interpretations"]["requirements"]["estimates"]["hints"]
          if h.get("alignment")]
    assert h["kind"] == "offset"
    # Independent review's stages hold no hints: the compare stage withholds every recorded
    # interpretation, the reading of the workspace included.
    for stage in ("read", "compare"):
        code, out, _ = _run(["compare", "Theorem 17", "--workspace", wid, "--stage", stage,
                             "--json"], capsys)
        assert code == 0
        raw = json.loads(out)
        assert "interpretations" not in raw and "computed hint" not in out
    hints = est.workspace_hints(work, work / "site" / "data")
    assert [h["alignment"] for h in hints[JET]["hints"] if h.get("alignment")] == ["a-x"]
    # Nothing was written, and the claim's status is the engine's.
    assert _digests(work.parent) == before
    assert snap_of(work).chunk(JET)["status_code"] == status
    # The semantic summary counts findings only: a hint is none.
    assert semantic.workspace_findings(work, work / "site" / "data") == {}


def test_check_json_gives_each_claims_hints_attributed(work, monkeypatch):
    p = opened(work, jet_reading() + [align("a-x", "m.c", "m + 4", binder="h"),
                                     align("a-d", "m.c", "m + 4", at=H_ARG),
                                     put({"id": "f-d", "kind": "finding", "claim": JET,
                                          "requirement": "m.c",
                                          "difference": {"feature": "index offset",
                                                         "paper": "m + 4", "lean": "n + 5",
                                                         "outcome": "difference",
                                                         "hint": {"alignment": "a-d",
                                                                  "kind": "offset"}},
                                          "note": "recorded"})])
    wid = wsp.read(p)["id"]
    root = work.parent

    def write_site(view, site, web, r, *more):
        shutil.copytree(work / "site" / "data", Path(site) / "data")
    monkeypatch.setattr("prooflens.simple.write_view_site", write_site)
    monkeypatch.setattr(semantic, "of_view", lambda body, r, found: ({"counted": found}, {}))
    summary, facts, hints = cli._check_workspaces({"body": {}}, root)
    claims = [{"id": JET}, {"id": BOUND}]
    cli._with_hints(claims, hints)
    jet, other = claims
    h, = [h for h in jet["hints"] if h.get("alignment")]
    assert (h["alignment"], h["kind"], h["workspace"], h["by"], h["mode"]) == \
        ("a-x", "offset", wid, "human:A-Auditor", "informed")
    d, = jet["dismissed_hints"]
    assert (d["alignment"], d["settled_by"]) == ("a-d", "f-d")
    assert "hints" not in other and "dismissed_hints" not in other
    # The summary is given no hint: only the (here, no) submitted findings.
    assert summary == {"counted": None}


def test_a_published_audit_carries_no_hint(work):
    p = opened(work, jet_reading() + [align("a-x", "m.c", "m + 4", binder="h"),
                                     put({"id": "f-d", "kind": "finding", "claim": JET,
                                          "requirement": "m.c",
                                          "difference": {"feature": "index offset",
                                                         "paper": "m + 4", "lean": "n + 5",
                                                         "outcome": "difference",
                                                         "hint": {"alignment": "a-x",
                                                                  "kind": "offset"}},
                                          "note": "one order more"})])
    wsp.update(p, [{"op": "submit", "id": "f-d", "base_rev": 1}], snap_of(work))
    for pub in (EVERYTHING, CLOSED):
        rd, = pw.readings(work, snap_of(work), lambda cid: pub, {JET})[JET]
        raw = json.dumps(rd, ensure_ascii=False)
        assert "computed hint" not in raw and "Shape.JetBound, which expands" not in raw
        assert "hints" not in rd
        # The recorded difference is published, with the hint it settles.
        assert rd["findings"][0]["difference"]["hint"] == {"alignment": "a-x", "kind": "offset"}
