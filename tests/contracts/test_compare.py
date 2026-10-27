"""Comparison packets and targeted queries (#124), and what each stage of the review protocol
may receive (#75, #122): a reading receives paper content only, a comparison receives no prior
authored interpretation, and nothing is cut without saying so."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conftest import ROOT, build, needs_lean, needs_tex
from prooflens import cli
from prooflens import compare as cmp
from prooflens.review_cli import Session

LONG = " ".join(f"clause {i} holds for every $x_{{{i}}}$;" for i in range(400))  # > 9000 chars
NOTE = "AUTHORED-NOTE: the bound is read with the constant chosen first."
REVIEW = "PRIOR-REVIEW-READING: the authors' reading of the claim."
MARKER = "AUTHOR-MARKER: reviewed against the definition."
SYMBOL = "AUTHORED-SYMBOL-LINK"
ARGUMENT = "AUTHORED-ARGUMENT: chain the two bounds."


def seg(text, refs=()):
    return {"id": "/", "text": text,
            "segments": [{"t": text}] + [{"t": "", "ref": r} for r in refs], "terms": []}


def statement(text, refs=(), closure=()):
    return {"binders": [{"id": "/", "name": "n", "role": "forall", "type": seg("Nat", ["Nat"])}],
            "conclusion": seg(text, refs), "exact": seg(f"∀ (n : Nat), {text}", refs),
            "closure": list(closure), "direct": []}


def write_site(tmp: Path, n_claims: int = 8) -> Path:
    """A synthetic site: one link unit stated in `n_claims` places (the first a long LaTeX
    passage, one PDF-only, one without text), a definition with a generated constant."""
    data = tmp / "work" / "site" / "data"
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    big = "Syn.big_bound_" + "x" * 20
    long_exact = " ∧ ".join(f"Syn.Jet {i} n" for i in range(600))  # > 7000 chars
    defs = {
        "Syn.Jet": {"name": "Syn.Jet", "kind": "def", "module": "Syn.Defs",
                    "signature": seg("Nat → Nat → Prop", ["Nat"]),
                    "value": seg("fun m n => Syn.Jet._f m n", ["Syn.Jet._f"]),
                    "uses": ["Syn.Jet._f"], "fingerprint": "fp-jet", "doc": "A finite jet.",
                    "review": {"current": [{"by": "author", "text": MARKER}], "state":
                               "author-reviewed"}},
        "Syn.Jet._f": {"name": "Syn.Jet._f", "kind": "def", "module": "Syn.Defs",
                       "signature": seg("Nat → Nat → Prop"), "value": seg("fun m n => m ≤ n"),
                       "uses": [], "fingerprint": "fp-jet-f"},
        "Syn.other": {"name": "Syn.other", "kind": "theorem", "module": "Syn.Other",
                      "signature": seg("∀ n, Syn.Jet 2 n", ["Syn.Jet"]), "uses": [],
                      "fingerprint": "fp-other"},
    }
    keys = {}
    for n, rec in defs.items():
        keys[n] = hashlib.sha256(n.encode()).hexdigest()[:24]
        (data / "decls" / f"{keys[n]}.json").write_text(json.dumps(rec))
    link = {"name": big, "kind": "theorem", "module": "Syn.Main", "source": "confirmed",
            "fingerprint": "fp-big", "axioms": ["propext"], "sorry": False, "errors": [],
            "status": "linked: Lean proof checked", "status_code": "link.checked",
            "statement": statement(long_exact, ["Syn.Jet"], ["Syn.Jet", "Syn.Jet._f"])}
    index_claims, units_claims = [], []
    for i in range(n_claims):
        cid = f"S:thm:t{i}"
        tex = f"\\label{{thm:t{i}}}\\lean{{{big}}} Statement {i}. " + (LONG if i == 0 else "")
        anchor = {"kind": "exact", "file": "main.tex", "line": 10 + i, "label": f"thm:t{i}",
                  "begin": [1, 0, 0], "end": [1, 0, 1], "statement": tex}
        if i == 1:
            anchor = {"kind": "approximate", "begin": [3, 0, 0], "end": [3, 0, 1],
                      "statement": "P" * cmp.PDF_TEXT_CHARS}
            tex = None
        if i == 2:
            anchor, tex = {"kind": "approximate", "begin": [4, 0, 0], "end": [4, 0, 1]}, None
        ch = {"id": cid, "key": f"thm:t{i}", "paper": "S", "number": f"Theorem {i}",
              "kind": "theorem", "heading": None, "location": "main.tex", "anchor": anchor,
              "statement_tex": tex, "source_sha256": f"sha{i}",
              "status": "linked: Lean proof checked", "status_code": "link.checked",
              "class": "proved", "links": [link], "suggestions": [], "clauses": [],
              "decls": {n: keys[n] for n in ("Syn.Jet", "Syn.Jet._f")},
              "correspondence": {"note": NOTE, "coverage": "full",
                                 "basis": "reviewed_composition", "argument": ARGUMENT,
                                 "next_step": "State the combination as one Lean result.",
                                 "by": "author"},
              "reviews": [{"reading": REVIEW, "verdict": {"value": "faithful"}}],
              "symbols": [{"tex": "C", "lean": SYMBOL}], "findings": [], "blockers": []}
        f = f"S_thm_t{i}.json"
        (data / "claims" / f).write_text(json.dumps(ch))
        index_claims.append({"id": cid, "paper": "S", "number": f"Theorem {i}", "file": f,
                             "status": ch["status"], "class": "proved"})
        units_claims.append({"id": cid, "number": f"Theorem {i}", "file": f})
    index = {"schema": "prooflens/manifest@1", "mode": "simple", "release": "v-synthetic",
             "evidence": "e" * 64, "project": {"name": "syn", "commit": "c" * 40},
             "papers": [{"id": "S", "title": "Synthetic", "revision": "c" * 40}],
             "claims": index_claims}
    (data / "index.json").write_text(json.dumps(index))
    queue = {"schema": "prooflens/review-queue@1", "release": "v-synthetic", "mode": "simple",
             "units": [{"id": "link:thm:t0", "kind": "link", "key": "thm:t0", "name": big,
                        "lean": [big], "fingerprints": {big: "fp-big"}, "papers": ["S"],
                        "claims": units_claims, "state": "pending",
                        "author_review": [{"by": "author", "text": MARKER}],
                        "reason": "Long statement"}]}
    (data / "review-queue.json").write_text(json.dumps(queue))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": "Syn.wrapper", "module": "Syn.W", "kind": "theorem",
          "type": "∀ n, Jet 3 n → True"}]))
    return data


@pytest.fixture
def site(tmp_path):
    return cmp.Site(write_site(tmp_path))


def dump(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def test_a_packet_holds_the_whole_passage_and_the_whole_statement(site):
    pk = cmp.claim_packet(site, "thm:t0")
    p, = pk["paper"]["passages"]
    assert p["available"] and p["complete"] and LONG in p["text"]
    d, = pk["lean"]["declarations"]
    assert d["statement"]["text"] == "∀ (n : Nat), " + " ∧ ".join(
        f"Syn.Jet {i} n" for i in range(600))
    jet = next(x for x in pk["lean"]["definitions"] if x["name"] == "Syn.Jet")
    assert jet["value"] == "fun m n => Syn.Jet._f m n" and jet["expansion"] == "generic"
    gen = next(x for x in pk["lean"]["definitions"] if x["name"] == "Syn.Jet._f")
    assert gen["generated_for"] == "Syn.Jet" and gen["value"] == "fun m n => m ≤ n"
    assert pk["snapshot"]["release"] == "v-synthetic" and pk["snapshot"]["project"]["commit"]
    # What the build does not extract is named with its owner, not implied absent.
    assert {u["owner"] for u in pk["retrieval"]["unavailable"]} >= {"#98"}
    assert "#97" not in {u["owner"] for u in pk["retrieval"]["unavailable"]}
    assert [q["query"] for q in pk["retrieval"]["on_request"]] == ["uses", "impact"]


def test_pdf_text_and_missing_text_say_where_they_come_from(site):
    pdf = cmp.claim_packet(site, "Theorem 1", "read")["paper"]["passages"][0]
    assert pdf["quality"] == "text extracted from the PDF"
    assert pdf["source"]["position"] == "approximate" and pdf["source"]["page"] == 3
    assert pdf["complete"] is False and "4000" in pdf["reason"]
    gone = cmp.claim_packet(site, "S:thm:t2", "read")["paper"]["passages"][0]
    assert gone["available"] is False and gone["text"] is None and gone["source"]["page"] == 4
    assert "UNAVAILABLE" in cmp.passage_text(gone)


def test_the_text_source_and_the_position_are_reported_apart():
    """An approximate position does not make a passage's text PDF extraction: a proof step of
    a LaTeX paper, placed by its line, gives its LaTeX source; a paper read from its PDF gives
    extracted text however it is placed."""
    tex = "\\begin{equation}\\label{eq:s} " + "x_i + " * 800 + "y \\end{equation}"  # > 4000
    step = {"id": "S:eq:s", "number": "Equation (1)", "location": "main.tex:40",
            "anchor": {"kind": "approximate", "file": "main.tex", "line": 40,
                       "begin": [2, 0, 300.0], "end": [2, 0, 320.0]},
            "source_evidence": {"state": "pass", "placement": "approximate"},
            "statement_tex": tex}
    p = cmp.passage(step, "read")
    assert (p["quality"], p["source"]["position"]) == ("LaTeX source", "approximate")
    # The PDF extraction's length limit does not apply to source text.
    assert p["complete"] and p["text"] == tex and "reason" not in p
    assert "(LaTeX source, approximate position; main.tex:40, page 2)" in cmp.passage_text(p)
    exact = cmp.passage({**step, "anchor": {**step["anchor"], "kind": "exact"}}, "read")
    assert (exact["quality"], exact["source"]["position"]) == ("LaTeX source", "exact")
    # A paper read from its PDF gives extracted text, here as `statement_tex`.
    pdf = {"id": "S:thm:p", "number": "Theorem 3", "location": "paper.pdf",
           "anchor": {"kind": "approximate", "begin": [5, 0, 100.0], "end": [5, 0, 130.0],
                      "statement": "Theorem 3. Every n is a number."},
           "source_evidence": {"state": "pdf-only", "placement": "approximate"},
           "statement_tex": "Theorem 3. Every n is a number."}
    q = cmp.passage(pdf, "read")
    assert (q["quality"], q["source"]["position"]) == ("text extracted from the PDF",
                                                      "approximate")


def test_definitions_continue_by_cursor_and_never_silently(site):
    first = cmp.claim_packet(site, "thm:t0", limit=1)
    page = first["retrieval"]["definitions"]
    assert page["total"] == 2 and page["returned"] == 1 and not page["complete"]
    rest = cmp.claim_packet(site, "thm:t0", limit=1, after=page["next"])
    assert [d["name"] for d in first["lean"]["definitions"] + rest["lean"]["definitions"]] == \
        ["Syn.Jet", "Syn.Jet._f"]
    assert rest["retrieval"]["definitions"]["next"] is None
    # The linked statement and the passage are never paged.
    assert rest["lean"]["declarations"] and LONG in rest["paper"]["passages"][0]["text"]
    with pytest.raises(cmp.CompareError):
        cmp.claim_packet(site, "thm:t0", limit=1, after="def:nothing")


def test_reading_receives_the_paper_only(site):
    unit = site.queue()["units"][0]
    pk = cmp.unit_packet(site, unit, "read")
    text = dump(pk)
    assert len(pk["paper"]["passages"]) == 8      # every claim of the unit, not the first six
    assert pk["paper"]["complete"]
    for leak in ("Syn.", "fp-big", NOTE, ARGUMENT, REVIEW, MARKER, SYMBOL,
                 "Lean proof checked", "reviewed_composition"):
        assert leak not in text, leak
    assert "lean" not in pk and "interpretations" not in pk
    assert pk["paper"]["passages"][0]["removed"]   # the \lean tag was taken out, and said so
    assert pk["contains"] == ["paper"]


def test_comparison_receives_no_prior_interpretation(site):
    unit = site.queue()["units"][0]
    pk = cmp.unit_packet(site, unit, "compare")
    text = dump(pk)
    assert unit["name"] in text and "Syn.Jet._f m n" in text
    for leak in (NOTE, ARGUMENT, REVIEW, MARKER, SYMBOL, "Lean proof checked", "link.checked",
                 "reviewed_composition"):
        assert leak not in text, leak
    assert "\\lean{" in pk["paper"]["passages"][0]["text"]
    later = dump(cmp.unit_packet(site, unit, "informed"))
    for shown in (NOTE, ARGUMENT, REVIEW, MARKER, SYMBOL):
        assert shown in later
    # The informed packet carries the reading whole: coverage and, separately, its basis.
    cor = cmp.claim_packet(site, "thm:t0", "informed")["interpretations"]["correspondence"]
    assert (cor["coverage"], cor["basis"], cor["argument"]) == ("full", "reviewed_composition",
                                                                ARGUMENT)
    assert cmp.claim_packet(site, "thm:t0", "informed")["contains"][-1] == \
        "prior interpretations"


def test_the_review_session_follows_the_stages(site, tmp_path):
    s = Session(site.data.parent.parent, {"id": "human:T", "kind": "human"})
    uid = "link:thm:t0"
    step1 = s.read(uid)
    assert "Theorem 7" in step1 and "Statement 7." in step1 and "Syn." not in step1
    assert "UNAVAILABLE" in step1 and "INCOMPLETE" in step1
    assert "Syn." not in dump(s.read(uid, as_json=True))
    s.lock(uid, "Every statement bounds the jet uniformly in n.")
    assert NOTE not in dump(s.show(uid, as_json=True))
    s.decide(uid, "faithful", "Same statement.")
    author = s.author(uid)
    assert NOTE in author and MARKER in author and ARGUMENT in author
    assert "Every clause, by the auditor's composition" in author
    assert "Lean has not checked this combination. Next step: State the combination as one " \
        "Lean result." in author


def test_queries_answer_with_provenance_and_change_nothing(site):
    before = {p: p.read_bytes() for p in site.data.rglob("*") if p.is_file()}
    d = cmp.query(site, "definition", "Syn.Jet")
    assert [r["name"] for r in d["results"]] == ["Syn.Jet", "Syn.Jet._f"]
    assert d["available"] and d["provenance"] and d["context"]["release"] == "v-synthetic"
    m = cmp.query(site, "mentions", "Syn.Jet")
    names = {r["name"]: r for r in m["results"]}
    assert {"Syn.other", "Syn.wrapper"} <= set(names) and "Syn.Jet" not in names
    assert any(n.startswith("Syn.big_bound") for n in names)
    assert "preview" in names["Syn.wrapper"]["note"]
    page = cmp.query(site, "mentions", "Syn.Jet", limit=1)
    assert page["retrieval"]["next"] == page["results"][0]["id"]
    for op, owner in cmp.NOT_YET.items():
        q = cmp.query(site, op, "Syn.Jet")
        assert q["available"] is False and owner in q["reason"] and q["results"] == []
    with pytest.raises(cmp.CompareError):
        cmp.query(site, "definition", "Syn.Nothing")
    after = {p: p.read_bytes() for p in site.data.rglob("*") if p.is_file()}
    assert before == after


def eq(i):
    return {"name": f"Syn.code.eq_{i}", "statement": seg(f"Syn.code {i} = {i}"), "params": [],
            "equation": seg(f"Syn.code {i} = {i}")}


def test_a_packet_gives_what_definitions_say_at_their_arguments(tmp_path):
    """A packet's definition says what it says (#97): its body, or every equation Lean derives
    for it, those stored in pages of their own included; each application of a definition in a
    linked statement or a definition's body comes with the definition at its arguments
    (`lean.expansions`), the same record under the same key as the reader fetches, pinned to
    the definition's fingerprint; `--query expansion KEY` gives any expansion by its key."""
    from prooflens import manifest as mf
    data = write_site(tmp_path)
    jet_at = {"at": "/1", "id": "/1=", "name": "Syn.Jet", "checked": True,
              "args": [{"name": "m", "binder": "explicit", "value": seg("2")},
                       {"name": "n", "binder": "explicit", "value": seg("n")}],
              "defined_by": "body", "params": [], "body": seg("Syn.Jet._f 2 n")}
    nested = {**jet_at, "at": "/2", "id": "/2=", "body": {**seg("Syn.Jet 2 n"),
                                                        "expansions": [jet_at]}}
    code = {"name": "Syn.code", "kind": "def", "module": "Syn.Defs", "signature": seg("Nat → Nat"),
            "value": seg("fun n => Syn.code.match_1 n"), "uses": [], "fingerprint": "fp-code",
            "defined_by": "equations", "equations": [eq(i) for i in range(1, 71)],
            "equation_names": [f"Syn.code.eq_{i}" for i in range(1, 71)], "equations_omitted": 0}
    # The equations after the first 64 are stored in pages, and each expansion is pinned to
    # the definition it expands; splitting again changes nothing.
    parts, pins = {}, {"Syn.Jet": "fp-jet", "Syn.code": "fp-code"}
    split = mf.split_expansions(code, parts, pins)
    assert [e["name"] for e in split["equations"]] == [f"Syn.code.eq_{i}" for i in range(1, 65)]
    [page] = split["equations_more"]
    assert page["name"] == "Syn.code.eq_65" and mf.is_expansion_ref(page)
    assert parts[page["key"]] == {"definition": "Syn.code", "equations": [eq(i) for i in
                                                                          range(65, 71)]}
    assert mf.split_expansions(split, parts, pins) == split
    stmt = mf.split_expansions({"conclusion": {**seg("Syn.Jet 2 n ∧ Syn.Jet 2 n"),
                                               "expansions": [jet_at, nested]}}, parts, pins)
    refs = stmt["conclusion"]["expansions"]
    assert [r["at"] for r in refs] == ["/1", "/2"] and all(mf.is_expansion_ref(r) for r in refs)
    assert parts[refs[0]["key"]] == {**jet_at, "fingerprint": "fp-jet"}
    assert mf.expansion_keys(parts[refs[1]["key"]]) == {refs[0]["key"]}
    # An expansion already stored stays as it is; one of a changed definition has another key,
    # though it prints the same.
    assert mf.split_expansions(stmt, {}, {"Syn.Jet": "fp-jet-2"}) == stmt
    again = mf.split_expansions({"expansions": [jet_at]}, {}, {"Syn.Jet": "fp-jet-2"})
    assert again["expansions"][0]["key"] != refs[0]["key"]
    (data / "expansions").mkdir()
    for k, x in parts.items():
        (data / "expansions" / f"{k}.json").write_text(json.dumps(x))
    (data / "decls" / f"{'c' * 24}.json").write_text(json.dumps(split))
    for f in (data / "claims").glob("*.json"):
        ch = json.loads(f.read_text())
        ch["links"][0]["statement"]["conclusion"] = stmt["conclusion"]
        ch["decls"]["Syn.code"] = "c" * 24
        f.write_text(json.dumps(ch))
    site = cmp.Site(data)
    pk = cmp.claim_packet(site, "thm:t0", "compare")
    # The expansions the statement refers to, in order, as the reader fetches them; the one
    # inside the second stays a reference that the query resolves.
    assert [x["key"] for x in pk["lean"]["expansions"]] == [r["key"] for r in refs]
    assert pk["lean"]["expansions"][0] == {"key": refs[0]["key"], **jet_at,
                                           "fingerprint": "fp-jet"}
    inner = pk["lean"]["expansions"][1]["body"]["expansions"]
    assert inner == [refs[0]]
    q = cmp.query(site, "expansion", inner[0]["key"])
    assert q["results"] == [pk["lean"]["expansions"][0]] and q["available"]
    with pytest.raises(cmp.CompareError) as e:
        cmp.query(site, "expansion", "0" * 24)
    assert e.value.kind == "unknown-expansion"
    # Every equation of the definition, the pages' included, in order.
    d = next(x for x in pk["lean"]["definitions"] if x["name"] == "Syn.code")
    assert d["defined_by"] == "equations" and d["expansion"] == "generic"
    assert [e["name"] for e in d["equations"]] == [f"Syn.code.eq_{i}" for i in range(1, 71)]
    assert "equations_more" not in d
    q = cmp.query(site, "definition", "Syn.code")
    assert len(q["results"][0]["equations"]) == 70
    text = cmp.packet_text(pk)
    assert "Syn.Jet at the application /1" in text and "arguments: m := 2, n := n" in text
    assert "is: Syn.Jet._f 2 n" in text and "equation Syn.code.eq_70: Syn.code 70 = 70" in text
    # A page the build no longer holds is said to be missing, not left out silently.
    (data / "expansions" / f"{page['key']}.json").unlink()
    d = cmp.query(cmp.Site(data), "definition", "Syn.code")["results"][0]
    assert len(d["equations"]) == 64 and d["equations_unavailable"] == [
        {**page, "available": False}]


def test_an_unknown_claim_is_refused_with_candidates(site):
    with pytest.raises(cmp.CompareError) as e:
        cmp.claim_packet(site, "S:thm:t9")
    assert e.value.kind == "unknown-claim" and e.value.candidates


# The tactic scripts of tactic defaults (#371), each with the declaration whose type has the
# default: a binder's as Lean 4.32 names it (inside the definition's namespace) and as Lean 4.24
# does (outside it), and a structure field's, whose default is the constructor's binder.
SCRIPTS = {"Syn.half._auto_1": "Syn.half", "_auto._@.Syn.Defs.12._hygCtx._hyg.3": "Syn.third",
           "Syn.Pos.pos._autoParam": "Syn.Pos.mk"}


def script_site(tmp: Path, auto_param=True, script_fp="fp-script") -> Path:
    """A site whose store holds the declarations of SCRIPTS and their scripts. The probe marks
    each script (`auto_param`; left out for `None`, as in a record of an earlier probe), and the
    owner's printed type names it."""
    data = tmp / "site" / "data"
    (data / "decls").mkdir(parents=True)
    recs = []
    for s, owner in SCRIPTS.items():
        recs.append({"name": owner, "kind": "ctor" if owner.endswith(".mk") else "def",
                     "module": "Syn.Defs", "uses": [], "fingerprint": f"fp-{owner}",
                     "auto_param": False,
                     "signature": seg(f"(n : Nat) → autoParam (0 < n) {s} → Nat",
                                      ["Nat", "autoParam", "LT.lt", s])})
        recs.append({"name": s, "kind": "def", "module": "Syn.Defs", "uses": [],
                     "fingerprint": f"{script_fp}:{s}", "signature": seg("Lean.Syntax"),
                     "value": seg("Lean.Syntax.node Lean.SourceInfo.none `byTactic"),
                     **({} if auto_param is None else {"auto_param": auto_param})})
    for rec in recs:
        key = hashlib.sha256(rec["name"].encode()).hexdigest()[:24]
        (data / "decls" / f"{key}.json").write_text(json.dumps(rec))
    (data / "index.json").write_text(json.dumps(
        {"schema": "prooflens/manifest@1", "mode": "simple", "release": "v-scripts",
         "evidence": "e" * 64, "project": {"name": "syn"}, "papers": [], "claims": []}))
    return data


def test_a_tactic_script_is_shown_with_the_declaration_whose_type_has_the_default(tmp_path):
    """#371: on Lean 4.24 a binder's script is named outside its definition's namespace, so
    its name does not tie it to the definition; the probe's records do, on either version."""
    from prooflens.targets import Snapshot, script_owners
    site = cmp.Site(script_site(tmp_path))
    assert script_owners(site.store().values()) == SCRIPTS
    for s, owner in SCRIPTS.items():
        d = cmp.query(site, "definition", owner)["results"]
        assert [r["name"] for r in d] == [owner, s]
        assert d[1]["generated_for"] == owner
        unit = {"id": f"def:{owner}", "kind": "def", "name": owner, "claims": []}
        pk = cmp.unit_packet(site, unit, "compare")
        assert {r["name"]: r["generated_for"] for r in pk["lean"]["definitions"]}[s] == owner
        # The text shows the declaration under review, and not its script as a definition.
        assert "Lean.Syntax.node" not in cmp.packet_text(pk)
    # An edit of a tactic changes its owner's digest, as an edit of an equation does.
    digests = Snapshot(site.data).digests()
    edited = Snapshot(script_site(tmp_path / "edited", script_fp="fp-edited")).digests()
    for owner in SCRIPTS.values():
        assert digests[owner].startswith("ws-digest:") and edited[owner] != digests[owner]


def test_a_record_without_the_probes_answer_is_tied_by_its_name_only(tmp_path):
    from prooflens.targets import Snapshot
    site = cmp.Site(script_site(tmp_path, auto_param=None))
    assert site.script_owners() == {}
    assert [r["name"] for r in cmp.query(site, "definition", "Syn.half")["results"]] == [
        "Syn.half", "Syn.half._auto_1"]
    assert [r["name"] for r in cmp.query(site, "definition", "Syn.third")["results"]] == [
        "Syn.third"]
    assert Snapshot(site.data).digests()["Syn.third"] == "fp-Syn.third"


# -- the examples ------------------------------------------------------------------------------

def run_json(capsys, *args):
    cli.main(list(args))
    return json.loads(capsys.readouterr().out)


@needs_lean
@needs_tex
def test_the_toy_packet_matches_the_reader_records(toy, monkeypatch, capsys):
    build(toy)
    monkeypatch.chdir(toy)
    pk = run_json(capsys, "compare", "Theorem 2.5", "--json")
    data = cmp.Site(toy / ".machinechecked" / "site" / "data")
    ch = data.chunk("T:thm:bound")
    assert pk["paper"]["passages"][0]["text"] == ch["statement_tex"]
    d, = pk["lean"]["declarations"]
    cl = ch["clauses"][0]
    assert d["name"] == cl["spec"] and d["clause"] == cl["name"] and d["statement"]["text"] == cl["statement"]["exact"]["text"]
    tri = next(x for x in pk["lean"]["definitions"] if x["name"] == "Toy.triangle")
    assert tri["value"] and tri["signature"] == "Nat → Nat"
    assert tri["defined_by"] == "equations"
    assert [e["name"] for e in tri["equations"]] == ["Toy.triangle.eq_1", "Toy.triangle.eq_2"]
    # The packet gives the expansions the reader fetches for the statement, under the same keys,
    # each pinned to the definition it expands (#97).
    from prooflens import manifest as mf
    wanted = mf.expansion_keys(cl["statement"])
    xs = {x["key"]: x for x in pk["lean"]["expansions"]}
    assert wanted and wanted <= set(xs)
    assert {(xs[k]["name"], xs[k]["fingerprint"]) for k in wanted} == \
        {("Toy.triangle", tri["fingerprint"])}
    assert "interpretations" in pk
    q = run_json(capsys, "compare", "--query", "definition", "Toy.triangle", "--json")
    assert {"Toy.triangle", "Toy.triangle._f"} <= {r["name"] for r in q["results"]}


@needs_lean
@needs_tex
def test_the_dependencies_text_names_what_its_json_holds(toy, monkeypatch, capsys):
    """The terminal answer of `--query dependencies` shows the statement and every dependency
    the JSON answer gives, and says a declaration is missing only when Lean did not find it."""
    build(toy)
    monkeypatch.chdir(toy)

    def answer(name):
        r, = run_json(capsys, "compare", "--query", "dependencies", name, "--json")["results"]
        cli.main(["compare", "--query", "dependencies", name])
        return r, capsys.readouterr().out.splitlines()

    r, lines = answer("Toy.Acceptance.thm_bound")
    d = r["declaration"]
    assert r["ok"] and r["status"] == "found" and r["proof_dependencies"]
    assert not any("no statement" in x or "not found" in x for x in lines)
    assert lines[0].startswith(f"{d['name']}  ({d['kind']}, {d['file']}")
    assert f"  statement: {d['statement']}" in lines
    assert f"  axioms: {', '.join(d['axioms'])}" in lines
    assert "  statement uses (this project): " + ", ".join(r["statement_dependencies"]) in lines
    assert "  proof uses (this project): " + ", ".join(r["proof_dependencies"]) in lines
    assert "  proof uses (outside this project): " + \
        ", ".join(r["external_dependencies"]["proof"]) in lines
    for m in r["closure"]["members"]:
        assert f"    {m['depth']:>3}  {m['name']}  ({m['kind']}, {m['module']})" in lines
    r, lines = answer("Toy.Nothing")
    assert not r["ok"] and r["status"] == "not found"
    assert lines == ["Toy.Nothing: not found"]


PLAIN = ROOT / "examples" / "plain-paper"


@pytest.fixture
def plain(tmp_path):
    dst = tmp_path / "plain"
    shutil.copytree(PLAIN, dst, ignore=shutil.ignore_patterns(
        ".prooflens", ".machinechecked", "prooflens.links.json", "machinechecked.links.json"),
        symlinks=True)
    return dst


@needs_lean
@needs_tex
def test_zero_configuration_review_from_the_terminal(plain, tmp_path, monkeypatch, capsys):
    from prooflens.simple import built_modules
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    (plain / "machinechecked.links.json").write_text(json.dumps({"version": 1, "papers": {
        "paper/main.tex": {"thm:odd-add": {"lean": ["Plain.odd_add_odd"], "note": NOTE,
                                           "coverage": "composed", "by": "author"}}}}))
    monkeypatch.chdir(plain)
    monkeypatch.setenv("MACHINECHECKED_REVIEWER", "human:Test-Referee")
    assert not (plain / "machinechecked.toml").exists()
    cli.main(["build"])
    capsys.readouterr()

    def run(*args):
        cli.main(["review", *args])
        return capsys.readouterr().out

    def refused(*args):
        with pytest.raises(SystemExit) as e:
            cli.main(["review", *args])
        assert e.value.code == 2
        return capsys.readouterr().err

    nxt = json.loads(run("next", "--json"))
    uid = nxt["unit"]["id"]
    assert uid == "link:thm:odd-add" and nxt["mode"] == "simple"
    step1 = run("read", uid)
    assert "The sum of two odd natural numbers is even." in step1
    assert "Plain." not in step1 and NOTE not in step1
    assert "lock your reading first" in refused("show", uid)
    reading = tmp_path / "r.md"
    reading.write_text("The sum of any two odd natural numbers is an even natural number.")
    run("lock", uid, str(reading))
    shown = json.loads(run("show", uid, "--json"))
    assert shown["contains"] == ["paper", "Lean"] and NOTE not in json.dumps(shown)
    decl, = shown["lean"]["declarations"]
    assert decl["name"] == "Plain.odd_add_odd"
    assert decl["statement"]["text"].startswith("∀ {a b : Nat}, Plain.Odd a")
    assert any(d["name"] == "Plain.Odd" and d["value"] for d in shown["lean"]["definitions"])
    assert "Plain.odd_add_odd" in run("show", uid)
    assert "needs step 'author'" in refused("author", uid)
    run("decide", uid, "faithful", str(reading))
    none = tmp_path / "none.md"
    none.write_text("none")
    assert "read the author's review first" in refused("submit", uid, str(none))
    assert NOTE in run("author", uid)
    run("submit", uid, str(none))
    out = plain / "machinechecked-reviews" / "referee.json"
    out.parent.mkdir()
    run("export", "--out", str(out))
    report, = json.loads(out.read_text())["reports"]
    assert report["unit"]["id"] == uid and report["pins"]["fingerprints"]["Plain.odd_add_odd"]
    # The steps were saved in the reviewer's workspace, the one `workspace` commands open.
    saved = json.loads((plain / ".machinechecked" / "review-work"
                        / "human_Test-Referee.json").read_text())
    assert saved["schema"] == "prooflens/workspace@1" and len(saved["review"]["reports"]) == 1
    ws, = run_json(capsys, "workspace", "list", "--json")["workspaces"]
    assert ws["id"] == saved["id"] and ws["mode"] == "independent" and ws["reports"] == 1
    # The packet of a general comparison is an informed one, and says so.
    pk = run_json(capsys, "compare", "thm:odd-add", "--json")
    assert pk["contains"][-1] == "prior interpretations"
    cor = pk["interpretations"]["correspondence"]
    # A stored `composed` reaches the packet as full coverage by the auditor's composition, its
    # note as the argument.
    assert (cor["coverage"], cor["basis"], cor["argument"], cor["next_step"]) == (
        "full", "reviewed_composition", NOTE, "State the combination as one Lean result.")
