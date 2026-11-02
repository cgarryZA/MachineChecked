"""The paper version map between two revisions of a synthetic paper (#120): every class, the
context a passage is read with, proposals that stay proposals, the maintainer's resolution, each
side's own facts, and the paper numbers it resolves. No Lean runs; only the toy paper's test
compiles TeX."""

import json

import pytest

from conftest import build, edit, needs_tex
from prooflens import cli
from prooflens import evidence as ev
from prooflens import numbering as nb
from prooflens import version_map as vm
from prooflens.source_regions import SCHEME, extract
from prooflens.tex import statement_at
from prooflens.util import norm_ws, sha256_text

PREAMBLE = ("\\documentclass{article}\n\\newcommand{\\R}{\\mathbb{R}}\n"
            "\\newcommand{\\dimK}{DIM}\n\\newtheorem{theorem}{Theorem}[section]\n"
            "\\newtheorem{definition}[theorem]{Definition}\n\\newtheorem{claim}[theorem]{Claim}\n"
            "\\begin{document}\n")


def env(kind, label, body):
    return f"\\begin{{{kind}}}\\label{{{label}}}\n{body}\n\\end{{{kind}}}\n\n"


TWICE = "\\begin{equation}\\label{eq:twice}\n  x = y\n\\end{equation}\n\n"
DEF_A = "A function $f$ is bounded if $|f| \\le M$ for some $M$."
DEF_B = "A function $f$ is bounded if $|f| \\le M$ for some constant $M$."
CLAIM_A = "The constant $C$ is uniform in $n$."
CLAIM_B = "The constant $C$ is uniform in $n \\ge 1$."


def earlier():
    return (PREAMBLE.replace("DIM", "3")
            + "\\section{Setting}\nThroughout, $f$ is continuous.\n\n"
            + env("definition", "def:bounded", DEF_A)
            + env("theorem", "thm:keep", "Every bounded $f$ on $\\R$ is integrable.")
            + env("theorem", "thm:refers", "By Definition~\\ref{def:bounded}, $f$ is locally "
                                           "bounded.")
            + "\\section{Results}\n\n"
            + env("theorem", "thm:moved", "Every even number is a sum of two odd numbers.")
            + env("theorem", "thm:edit", "The bound holds with constant $2$.")
            + env("theorem", "thm:macro", "The dimension is $\\dimK$.")
            + TWICE
            + "\\section{Bounds}\nIn this section $n \\ge 1$.\n\n"
            + env("theorem", "thm:standing", "The sum is at most $n^2$.")
            + CLAIM_A + "\n\n"
            + env("theorem", "thm:gone", "A result the later revision drops.")
            + "\\end{document}\n")


def later():
    return (PREAMBLE.replace("DIM", "4")
            + "\\section{Setting}\nThroughout, $f$ is continuous.\n\n"
            + env("definition", "def:bounded", DEF_B)
            + env("theorem", "thm:keep", "Every bounded $f$ on $\\R$ is integrable.")
            + env("theorem", "thm:refers", "By Definition~\\ref{def:bounded}, $f$ is locally "
                                           "bounded.")
            + "\\section{Results}\n\n"
            + env("theorem", "thm:new", "A result the earlier revision did not have.")
            + env("theorem", "thm:moved", "Every even number is a sum of two odd numbers.")
            + env("theorem", "thm:edit", "The bound holds with constant $3$.")
            + env("theorem", "thm:macro", "The dimension is $\\dimK$.")
            + TWICE
            + "\\section{Interlude}\nA remark without results.\n\n"
            + "\\section{Bounds}\nIn this section $n \\ge 0$.\n\n"
            + env("theorem", "thm:standing", "The sum is at most $n^2$.")
            + CLAIM_B + "\n\n"
            + TWICE
            + "\\end{document}\n")


def line_of(text, needle, nth=1):
    i = -1
    for _ in range(nth):
        i = text.index(needle, i + 1)
    return text[:i].count("\n") + 1


def env_claim(root, cid, kind, number, pinned=True):
    c = {"id": f"T:{cid}", "paper": "T", "kind": kind, "number": number,
         "location": "paper.tex", "label": cid, "scope": "formal", "clauses": []}
    if pinned:
        text = (root / "paper.tex").read_text()
        body = statement_at(root / "paper.tex", line_of(text, f"\\label{{{cid}}}"), kind)
        c["source_sha256"] = sha256_text(norm_ws(body))
    return c


def line_claim(root, cid, needle, kind, number, nth=1, span=False):
    text = (root / "paper.tex").read_text()
    ln = line_of(text, needle, nth)
    c = {"id": f"T:{cid}", "paper": "T", "kind": kind, "number": number,
         "location": f"paper.tex:{ln}", "scope": "formal", "clauses": []}
    if span:
        c["source_region"] = {"end_line": ln}
    r = extract(root, c)
    c.update(source_hash_scheme=SCHEME, source_sha256=r.sha256,
             source_line_sha256=r.line_sha256)
    return c


@pytest.fixture
def revisions(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, text in ((a, earlier()), (b, later())):
        root.mkdir()
        (root / "paper.tex").write_text(text)
    old = [env_claim(a, "def:bounded", "definition", "Definition 1.1"),
           env_claim(a, "thm:keep", "theorem", "Theorem 1.2"),
           env_claim(a, "thm:refers", "theorem", "Theorem 1.3"),
           env_claim(a, "thm:moved", "theorem", "Theorem 2.1"),
           env_claim(a, "thm:edit", "theorem", "Theorem 2.2"),
           env_claim(a, "thm:macro", "theorem", "Theorem 2.3"),
           line_claim(a, "eq:twice", "\\begin{equation}", "equation", "Equation (1)"),
           env_claim(a, "thm:standing", "theorem", "Theorem 3.1"),
           line_claim(a, "claim-c", CLAIM_A, "claim", "Claim 3.2", span=True),
           env_claim(a, "thm:gone", "theorem", "Theorem 3.3"),
           {"id": "T:nowhere", "paper": "T", "kind": "remark", "number": "Remark 3.4",
            "scope": "expository", "clauses": []}]
    # The later inventory, as a repin and a few edits by hand leave it: the claims whose text
    # changed keep the earlier pin, so their pins are of other text.
    pins = {c["id"]: c.get("source_sha256") for c in old}
    new = [env_claim(b, "def:bounded", "definition", "Definition 1.1", pinned=False),
           env_claim(b, "thm:keep", "theorem", "Theorem 1.2"),
           env_claim(b, "thm:refers", "theorem", "Theorem 1.3"),
           env_claim(b, "thm:new", "theorem", "Theorem 2.1"),
           env_claim(b, "thm:moved", "theorem", "Theorem 2.2"),
           env_claim(b, "thm:edit", "theorem", "Theorem 2.3", pinned=False),
           env_claim(b, "thm:macro", "theorem", "Theorem 2.4"),
           line_claim(b, "eq:twice-1", "\\begin{equation}", "equation", "Equation (1)"),
           env_claim(b, "thm:standing", "theorem", "Theorem 4.1"),
           line_claim(b, "claim-c", CLAIM_B, "claim", "Claim 4.2", span=True),
           line_claim(b, "eq:twice-2", "\\begin{equation}", "equation", "Equation (2)", nth=2)]
    for c in new:
        if c["id"] in ("T:def:bounded", "T:thm:edit"):
            c["source_sha256"] = pins[c["id"]]
    return a, b, old, new


def by_from(doc):
    return {r["from"]["claim"]: r for r in doc["claims"] if r["from"]}


def test_every_class_between_two_revisions(revisions):
    a, b, old, new = revisions
    doc = vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2"))
    assert doc["schema"] == "prooflens/version-map@1"
    e = by_from(doc)
    cls = {k: r["class"] for k, r in e.items()}
    assert cls == {
        "T:thm:keep": "unchanged", "T:thm:moved": "moved", "T:def:bounded": "changed",
        "T:thm:edit": "changed", "T:thm:refers": "context-changed",
        "T:thm:macro": "context-changed", "T:thm:standing": "context-changed",
        "T:thm:gone": "removed", "T:eq:twice": "ambiguous", "T:claim-c": "ambiguous",
        "T:nowhere": "unknown"}
    new_rows = {r["to"]["claim"]: r for r in doc["claims"] if r["class"] == "new"}
    assert set(new_rows) == {"T:thm:new", "T:eq:twice-1", "T:eq:twice-2", "T:claim-c"}
    assert new_rows["T:eq:twice-2"]["candidate_for"] == ["T:eq:twice"]
    assert doc["counts"] == {"changed": 2, "context-changed": 3, "removed": 1, "ambiguous": 2,
                             "new": 4, "unknown": 1, "moved": 1, "unchanged": 1}
    # A text found once: both places, and the number each revision prints.
    moved = e["T:thm:moved"]
    assert moved["by"] == ["text"] and moved["renumbered"] and moved["moved"]
    assert moved["from"]["location"] != moved["to"]["location"]
    assert (moved["from"]["number"], moved["to"]["number"]) == ("Theorem 2.1", "Theorem 2.2")
    assert e["T:thm:keep"]["from"]["bounds"] == e["T:thm:keep"]["to"]["bounds"]
    # A label leads to the changed passage: the exact change, and the pin is of other text.
    edit = e["T:thm:edit"]
    assert edit["by"] == ["label"]
    assert "-The bound holds with constant $2$." in edit["change"]["diff"]
    assert "+The bound holds with constant $3$." in edit["change"]["diff"]
    assert edit["from"]["pin"] == "matches" and edit["to"]["pin"] == "differs"
    assert e["T:def:bounded"]["to"]["pin"] == "differs"
    # The label is gone and nothing proposes another claim.
    assert e["T:thm:gone"]["to"] is None and "candidates" not in e["T:thm:gone"]
    # A label twice is never chosen between; the copy that keeps the number is only proposed.
    twice = {x["claim"]: x["by"] for x in e["T:eq:twice"]["candidates"]}
    assert twice == {"T:eq:twice-1": ["label", "number"], "T:eq:twice-2": ["label"]}
    # A rewritten line without a label: the line diff and the id propose; nothing is matched.
    c = e["T:claim-c"]
    assert c["to"] is None
    assert c["candidates"] == [{"claim": "T:claim-c", "by": ["line-diff", "id"]}]
    assert "a proposed match, to resolve by hand" in c["reason"]
    assert e["T:nowhere"]["from"]["error"] == "it has no source location"


def test_context_changes_while_the_claims_own_lines_stay(revisions):
    a, b, old, new = revisions
    e = by_from(vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2")))
    # A macro the passage uses is defined otherwise.
    ctx = e["T:thm:macro"]["context"]
    assert [(x["what"], x["macro"], x["change"]) for x in ctx] == [
        ("macro", "\\dimK", "changed")]
    assert "-\\newcommand{\\dimK}{3}" in ctx[0]["diff"]
    assert "+\\newcommand{\\dimK}{4}" in ctx[0]["diff"]
    assert e["T:thm:macro"]["renumbered"] and e["T:thm:macro"]["by"] == ["text"]
    # The prose opening its section, a standing assumption, changed.
    st = e["T:thm:standing"]["context"]
    assert [(x["what"], x["section"], x["change"]) for x in st] == [
        ("standing assumption", "Bounds", "changed")]
    assert "+In this section $n \\ge 0$." in st[0]["diff"]
    # It refers to a definition whose text changed.
    ref = e["T:thm:refers"]["context"]
    assert ref == [{"what": "definition", "claim": "T:def:bounded", "number": "Definition 1.1",
                    "change": "changed", "via": ["reference"], "label": "def:bounded"}]
    assert e["T:thm:refers"]["from"]["bounds"] == e["T:thm:refers"]["to"]["bounds"]
    # A macro left as it was, in the same section, is no change.
    assert "context" not in e["T:thm:keep"]


def test_a_pinned_macro_definition_is_context_and_named_once(revisions):
    """A pin that lists the definition of a macro its passage states: the repinning planner
    finds the passage by its text and the definition changed, so the claim's own lines are
    unchanged and its context is not."""
    from prooflens.source_regions import MULTI, definition_part, part_claim, pin, tex_sources
    a, b, old, new = revisions

    def with_part(root, cid):
        c = line_claim(root, cid, "The dimension is", "statement", None)
        part = definition_part(tex_sources(root), "\\dimK")
        r = extract(root, part_claim(part))
        c.update(source_parts=[{**part, "sha256": r.sha256, "line_sha256": r.line_sha256}],
                 source_hash_scheme=MULTI)
        c["source_sha256"] = pin(root, c).sha256
        return c

    doc = vm.compare("T", vm.Side(old + [with_part(a, "dim")], a, "r1"),
                     vm.Side(new + [with_part(b, "dim")], b, "r2"))
    dim = by_from(doc)["T:dim"]
    assert dim["class"] == "context-changed" and dim["by"] == ["text"]
    assert [(x["what"], x.get("macro"), x["change"]) for x in dim["context"]] == [
        ("macro definition", "\\dimK", "changed")]
    assert dim["from"]["pin_sha256"] != dim["from"]["sha256"]


def test_a_definition_the_lean_relies_on_is_context(revisions):
    a, b, old, new = revisions
    uses = {"T:thm:keep": {"T:def:bounded": ["Ex.Bounded"]}}
    doc = vm.compare("T", vm.Side(old, a, "r1", uses=uses), vm.Side(new, b, "r2", uses=uses))
    keep = by_from(doc)["T:thm:keep"]
    assert keep["class"] == "context-changed"
    assert keep["context"] == [{"what": "definition", "claim": "T:def:bounded",
                                "number": "Definition 1.1", "change": "changed",
                                "via": ["lean"], "names": ["Ex.Bounded"]}]
    assert "the definition it relies on, Definition 1.1, is changed" in keep["reason"]


def test_the_maintainer_resolves_a_proposal_and_it_is_recorded(revisions):
    a, b, old, new = revisions
    doc = vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2"),
                     resolve=[("T:claim-c", "T:claim-c"), ("T:eq:twice", "T:eq:twice-2")])
    e = by_from(doc)
    c = e["T:claim-c"]
    assert c["class"] == "changed" and c["by"] == ["maintainer", "line-diff", "id"]
    assert c["resolved"]["by"] == "maintainer" and c["resolved"]["was"] == "ambiguous"
    assert "-" + CLAIM_A in c["change"]["diff"] and "+" + CLAIM_B in c["change"]["diff"]
    # Its section's opening changed too: the context is given with the match.
    assert [x["what"] for x in c["context"]] == ["standing assumption"]
    # The copy the maintainer chose has the same text, in a section that opens with prose.
    twice = e["T:eq:twice"]
    assert twice["class"] == "context-changed" and twice["to"]["claim"] == "T:eq:twice-2"
    assert twice["moved"] and twice["renumbered"]
    assert [(x["what"], x["change"]) for x in twice["context"]] == [
        ("standing assumption", "added")]
    assert {r["to"]["claim"] for r in doc["claims"] if r["class"] == "new"} == {
        "T:thm:new", "T:eq:twice-1"}
    with pytest.raises(vm.MapError, match="already matched to T:thm:moved by its text"):
        vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2"),
                   resolve=[("T:thm:moved", "T:thm:new")])
    with pytest.raises(vm.MapError, match="T:thm:moved is already matched to T:thm:moved"):
        vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2"),
                   resolve=[("T:thm:gone", "T:thm:moved")])


def test_two_earlier_claims_on_one_later_claim_are_both_ambiguous(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    (a / "p.tex").write_text("One.\nTwo.\n")
    (b / "p.tex").write_text("Zero.\nOne.\nTwo.\n")
    one = {"id": "P:one", "paper": "P", "location": "p.tex:1", "clauses": []}
    two = {"id": "P:two", "paper": "P", "location": "p.tex:2", "clauses": []}
    wide = {"id": "P:both", "paper": "P", "location": "p.tex:2",
            "source_region": {"end_line": 3}, "clauses": []}
    doc = vm.compare("P", vm.Side([one, two], a, "r1"), vm.Side([wide], b, "r2"))
    e = by_from(doc)
    assert e["P:one"]["class"] == e["P:two"]["class"] == "ambiguous"
    assert "2 earlier claims (P:one, P:two) lead to the later claim P:both" in e["P:one"]["reason"]
    assert e["P:one"]["candidates"] == [{"claim": "P:both", "by": ["text", "overlap"]}]


def test_each_side_keeps_the_facts_its_own_release_recorded(revisions):
    a, b, old, new = revisions
    facts_a = {"T:thm:edit": {"status": "formal: accepted", "status_code": "formal.accepted"}}
    facts_b = {"T:thm:edit": {"status": "formal: proved, review pending",
                              "status_code": "formal.review-pending"}}
    doc = vm.compare("T", vm.Side(old, a, "r1", facts=facts_a.get),
                     vm.Side(new, b, "r2", facts=facts_b.get))
    edit = by_from(doc)["T:thm:edit"]
    assert edit["from"]["recorded"] == facts_a["T:thm:edit"]
    assert edit["to"]["recorded"] == facts_b["T:thm:edit"]
    assert by_from(doc)["T:thm:keep"]["from"]["recorded"] is None


def test_numbers_give_the_current_counterpart_with_source_and_ambiguity(revisions):
    a, b, old, new = revisions
    doc = vm.compare("T", vm.Side(old, a, "r1"), vm.Side(new, b, "r2"))
    nums = {n["old"]: n for n in doc["numbers"]}
    assert nums["Theorem 3.1"]["new"] == ["Theorem 4.1"]
    assert nums["Theorem 3.1"]["match"] == {"class": "context-changed", "by": ["text"],
                                            "from": "T:thm:standing", "to": ["T:thm:standing"]}
    assert nums["Theorem 3.3"]["new"] == [] and nums["Theorem 3.3"]["match"]["class"] == \
        "removed"
    assert nums["Equation (1)"]["new"] == ["Equation (1)", "Equation (2)"]
    assert "Remark 3.4" not in nums
    index = [{"name": n, "kind": "theorem", "module": "P.Main", "range": {"line": i + 1},
              "doc": d, "uses": [], "value_uses": []}
             for i, (n, d) in enumerate([("P.standing", "Theorem 3.1: the sum."),
                                         ("P.gone", "Theorem 3.3: dropped."),
                                         ("P.c", "Claim 3.2: uniform."),
                                         ("P.moved", "Theorem 2.2: sums.")])]
    claims = [c for c in new]
    out = nb.analyse(index, claims, nb.inventory(claims, True),
                     version_map=vm.numbering_map(doc))
    cur = {o["source"]["declaration"]: o for o in out["references"]}
    standing = cur["P.standing"]["current"]
    assert standing["reference"] == "Theorem 4.1" and standing["claims"] == ["T:thm:standing"]
    assert standing["source"]["schema"] == "prooflens/version-map@1"
    assert standing["matches"][0]["by"] == ["text"]
    assert cur["P.standing"]["message"].endswith("; the version map gives Theorem 4.1")
    assert cur["P.gone"]["current"]["none"] is True
    assert "finds no counterpart" in cur["P.gone"]["message"]
    assert cur["P.c"]["current"]["proposed"] is True
    assert "proposes Claim 4.2, a match not resolved" in cur["P.c"]["message"]
    # A number this revision still has is not taken for a stale one.
    assert cur["P.moved"]["status"] == "exact" and "current" not in cur["P.moved"]
    # The statuses of the references are their own.
    assert {o["status"] for o in out["references"]} == {"absent", "exact"}


# -- the command, on two stored releases -----------------------------------------------------

def body(claims, assessed, regions, anchors, revision):
    return {"inventory": {"claims": claims}, "reviews": {"files": {}, "records": []},
            "dismissals": [], "lean": None,
            "tex": {"T": {"mode": "latex", "regions": regions, "anchors": anchors}},
            "assessment": {"claims": assessed, "findings": [], "gates": {}},
            "provenance": {"project": {"commit": "c" * 40, "dirty": False},
                           "lean_inputs_sha256": None,
                           "papers": {"T": {"revision": revision, "mode": "latex"}}}}


def release(out, name, claims, root, status, printed):
    """A stored release of `claims`, read from the manuscript at `root`: the regions of the
    claims located by line, and an anchor of the compiled paper for each environment, with the
    number the compiled paper prints (`printed`)."""
    from prooflens.source_regions import collect
    regions = collect({"claims": claims}, "T", root)
    text = (root / "paper.tex").read_text()
    anchors = []
    for c in claims:
        if c.get("location") == "paper.tex":
            ln = line_of(text, f"\\label{{{c['label']}}}")
            anchors.append({"env": c["kind"], "label": c["label"], "file": "paper.tex",
                            "line": ln, "number": printed[c["id"]].split()[-1],
                            "source_sha256": sha256_text(norm_ws(statement_at(
                                root / "paper.tex", ln, c["kind"])))})
    assessed = [{"id": c["id"], "status": status.replace(".", ": "), "status_code": status,
                 "clauses": []} for c in claims]
    eid = ev.store(out, body(claims, assessed, regions, anchors, None))
    ev.record_release(out, name, eid)
    return eid


def project(tmp_path, revisions):
    a, b, old, new = revisions
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "paper" / "paper.tex").write_text(later())
    # A repin leaves the inventory's numbers as they were: the compiled paper gives the new ones.
    printed = {c["id"]: c["number"] for c in new}
    numbers = {c["id"]: c["number"] for c in old}
    new = [{**c, "number": numbers.get(c["id"], c["number"])} for c in new]
    (root / "claims.json").write_text(json.dumps({"claims": new}))
    (root / "machinechecked.toml").write_text(
        '[project]\nname = "p"\nlean_root = "."\ninventory = "claims.json"\nmodules = ["P"]\n'
        'scope_roots = ["P"]\nspec_prefix = "P.Spec"\naccept_prefix = "P.Acc"\n'
        '[[paper]]\nid = "T"\ntitle = "T"\nsource = { path = "paper" }\nroot = "paper.tex"\n')
    out = root / ".machinechecked"
    release(out, "r-1", old, a, "formal.accepted", numbers)
    eid = release(out, "r-2", new, b, "formal.open", printed)
    return root, eid


def numbering_of(index, root, eid):
    """The paper-number check a build with Lean keeps beside release `eid` (`content.py`), of
    the declarations `index` against the later paper's numbering."""
    from prooflens import content
    rec = ev.load(root / ".machinechecked", eid)
    claims, inv = content.paper_inventory("T", rec["body"]["tex"],
                                          rec["body"]["inventory"]["claims"], {})
    num = nb.analyse(index, claims, inv)
    content.save(root / ".machinechecked", eid, {"schema": content.SCHEMA, "numbering": num})


def test_command_maps_two_releases(tmp_path, revisions, capsys):
    a, b, old, new = revisions
    root, eid = project(tmp_path, revisions)
    cfg = str(root / "machinechecked.toml")
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a), "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["from"]["release"] == "r-1" and doc["to"]["release"] == "r-2"
    assert doc["to"]["manuscript"] == "the configured folder paper"
    # Every passage each release recorded, those of its environments by their anchors.
    assert doc["from"]["checked"] == len(old) - 1 and doc["to"]["checked"] == len(new)
    e = by_from(doc)
    assert e["T:thm:edit"]["from"]["recorded"]["status_code"] == "formal.accepted"
    assert e["T:thm:edit"]["to"]["recorded"]["status_code"] == "formal.open"
    # The numbers are those each compiled paper prints, not the inventory's older ones.
    assert e["T:thm:moved"]["to"]["number"] == "Theorem 2.2" and e["T:thm:moved"]["renumbered"]
    assert {n["old"]: n["new"] for n in doc["numbers"]}["Theorem 3.1"] == ["Theorem 4.1"]
    assert doc["references"] is None
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a),
              "--match", "T:claim-c=T:claim-c"])
    out = capsys.readouterr().out
    # The inventory kept the claim's earlier number, so its number proposes it too.
    assert "Claim 3.2 (T:claim-c): changed (by the maintainer and the line diff of its file " \
           "and its number and its id)" in out
    assert "Theorem 2.1 (T:thm:moved): moved (by its text): the same text at another place, " \
           "now Theorem 2.2" in out
    assert "Theorem 1.2 (T:thm:keep)" not in out


def test_command_gives_stale_paper_numbers_their_counterparts(tmp_path, revisions, capsys):
    a, b, old, new = revisions
    root, eid = project(tmp_path, revisions)
    index = [{"name": n, "kind": "theorem", "module": "P.Main", "range": {"line": i + 1},
              "doc": d, "uses": [], "value_uses": []}
             for i, (n, d) in enumerate([("P.standing", "Theorem 3.1: the sum."),
                                         ("P.gone", "Theorem 3.3: dropped."),
                                         ("P.moved", "Theorem 2.2: sums.")])]
    numbering_of(index, root, eid)
    cfg = str(root / "machinechecked.toml")
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a), "--json"])
    refs = json.loads(capsys.readouterr().out)["references"]
    by = {o["source"]["declaration"]: o for o in refs["references"]}
    # Only the references that disagree with the later paper; each keeps its status.
    assert set(by) == {"P.standing", "P.gone"}
    assert by["P.standing"]["status"] == "absent"
    assert by["P.standing"]["current"]["reference"] == "Theorem 4.1"
    assert by["P.standing"]["current"]["claims"] == ["T:thm:standing"]
    assert by["P.standing"]["current"]["source"]["from"] == {"release": "r-1"}
    assert by["P.gone"]["current"]["none"] is True
    assert (refs["resolved"], refs["ambiguous"], refs["none"]) == (1, 0, 1)
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a)])
    out = capsys.readouterr().out
    assert "cites Theorem 3.1: this version of the paper has no statement numbered 3.1; the " \
           "version map gives Theorem 4.1" in out


@needs_tex
def test_toy_paper_renumbered_and_edited(toy, capsys):
    """The toy paper built without Lean, then a theorem inserted before its first result (every
    later number of Section 2 moves up one) and the uniform bound's statement edited, and built
    again with the new theorem added to the inventory. The map follows each claim by its text
    or its label, with the numbers each compiled paper prints and each build's own statuses."""
    import shutil
    earlier = toy.parent / "earlier"
    shutil.copytree(toy / "paper", earlier)
    index1, _, _ = build(toy, skip_lean=True)
    tex = toy / "paper" / "toy.tex"
    edit(tex, "\\begin{theorem}[Closure under addition]",
         "\\begin{theorem}\\label{thm:zero}\nZero is even.\n\\end{theorem}\n\n"
         "\\begin{theorem}[Closure under addition]")
    edit(tex, "such that $T_n \\le C n^2$", "such that $T_n \\le C n^2 + 1$")
    inv = json.loads((toy / "claims.json").read_text())
    # The claims located by line move down four lines, as `inventory repin` moves them.
    for c in inv["claims"]:
        if c["location"].startswith("toy.tex:"):
            c["location"] = f"toy.tex:{int(c['location'].split(':')[1]) + 4}"
            if c.get("source_region"):
                c["source_region"]["end_line"] += 4
    inv["claims"].append({"id": "T:thm:zero", "paper": "T", "kind": "theorem",
                          "number": "Theorem 2.1", "label": "thm:zero", "location": "toy.tex",
                          "scope": "expository", "scope_note": "", "scope_reviewed": True,
                          "clauses": []})
    (toy / "claims.json").write_text(json.dumps(inv, indent=2) + "\n")
    index2, _, _ = build(toy, skip_lean=True)
    cli.main(["changes", "-c", str(toy / "machinechecked.toml"), "--map",
              "--from-source", str(earlier), "--json"])
    doc = json.loads(capsys.readouterr().out)
    e = by_from(doc)
    moved = {k: (r["from"]["number"], r["to"]["number"]) for k, r in e.items()
             if r["class"] == "moved"}
    assert moved["T:thm:even-add"] == ("Theorem 2.1", "Theorem 2.2")
    assert moved["T:cor:even-triangle"] == ("Corollary 2.6", "Corollary 2.7")
    assert all(e[k]["by"] == ["text"] and e[k]["renumbered"] for k in moved
               if k.startswith("T:thm"))
    assert e["T:def:even"]["class"] == "unchanged"
    bound = e["T:thm:bound"]
    assert bound["class"] == "changed" and bound["by"] == ["label"]
    assert (bound["from"]["number"], bound["to"]["number"]) == ("Theorem 2.5", "Theorem 2.6")
    assert any("C n^2 + 1" in ln for ln in bound["change"]["diff"])
    assert bound["to"]["pin"] == "differs"
    assert [r["to"]["claim"] for r in doc["claims"] if r["class"] == "new"] == ["T:thm:zero"]
    # Each side's status is the one its own build recorded.
    s1 = {c["id"]: c["status_code"] for c in index1["claims"]}
    s2 = {c["id"]: c["status_code"] for c in index2["claims"]}
    assert all(r["from"]["recorded"]["status_code"] == s1[k] for k, r in e.items())
    assert all(r["to"]["recorded"]["status_code"] == s2[r["to"]["claim"]]
               for r in doc["claims"] if r["to"])
    assert {n["old"]: n["new"] for n in doc["numbers"]}["Theorem 2.5"] == ["Theorem 2.6"]


def test_command_refuses_a_manuscript_that_is_not_the_releases(tmp_path, revisions, capsys):
    root, _ = project(tmp_path, revisions)
    with pytest.raises(SystemExit):
        cli.main(["changes", "-c", str(root / "machinechecked.toml"), "--map"])
    err = capsys.readouterr().err
    assert "does not hold the text release r-1 recorded" in err
    assert "pass --from-source DIR (or git:REV)" in err
    with pytest.raises(SystemExit):
        cli.main(["changes", "-c", str(root / "machinechecked.toml"), "--match", "A=B"])
    assert "add --map" in capsys.readouterr().err
