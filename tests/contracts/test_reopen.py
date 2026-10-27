"""The findings a revision of the paper reopens, through the version map (#120): a moved or
renumbered passage keeps a statement comparison current; a changed passage, a removed one and a
change of what a passage is read with (a macro, the prose opening its section, a definition the
claim's Lean relies on, a passage attached to a requirement) reopen exactly the findings that
rest on them, each naming the change and the dependency; an ambiguous match is not known to be
current; the Lean side is checked against the later build apart from the paper's; and the map
travels with the workspace through its export and import. A synthetic paper in two revisions
and small synthetic builds stand in for real ones, so no Lean runs."""

import json

import pytest

from prooflens import cli
from prooflens import evidence as ev
from prooflens import reopen as ro
from prooflens import review_cli as rc
from prooflens import version_map as vm
from prooflens import workspace as wsp
from prooflens.source_regions import SCHEME, collect, extract
from prooflens.targets import Snapshot
from prooflens.tex import statement_at
from prooflens.util import norm_ws, sha256_text

WHO = rc.parse_reviewer("human:A-Auditor")

PREAMBLE = ("\\documentclass{article}\n\\newcommand{\\dimK}{DIM}\n"
            "\\newtheorem{theorem}{Theorem}[section]\n"
            "\\newtheorem{definition}[theorem]{Definition}\n\\begin{document}\n")
TWICE = "\\begin{equation}\\label{eq:twice}\n  x = y\n\\end{equation}\n\n"
QUANTIFIER_A = "For every $\\varepsilon > 0$,"
QUANTIFIER_B = "For every $\\varepsilon \\in (0,1]$,"
CONSTANT = "with $C$ independent of $\\varepsilon$."


def env(kind, label, body):
    return f"\\begin{{{kind}}}\\label{{{label}}}\n{body}\n\\end{{{kind}}}\n\n"


def manuscript(later: bool) -> str:
    """The paper's earlier or later revision. The later one defines `\\dimK` otherwise, words
    Definition 1.1 otherwise, adds a theorem before the first result of Section 2 (so the
    results after it are renumbered and move down), changes Theorem 2.2's constant, drops
    Theorem 2.4, prints the display of Section 2 twice, changes the standing assumption of
    Section 3 and the quantifier before the display of Section 4, and edits an unrelated
    sentence."""
    b = later
    return (PREAMBLE.replace("DIM", "4" if b else "3")
            + "\\section{Setting}\n\n"
            + env("definition", "def:bounded", "A function $f$ is bounded if $|f| \\le M$ for "
                  "some " + ("constant $M$." if b else "$M$."))
            + env("theorem", "thm:keep", "Every bounded $f$ is integrable.")
            + "\\section{Results}\n\n"
            + (env("theorem", "thm:new", "A result the earlier revision did not have.")
               if b else "")
            + env("theorem", "thm:moved", "Every even number is a sum of two odd numbers.")
            + env("theorem", "thm:edit", f"The bound holds with constant ${3 if b else 2}$.")
            + env("theorem", "thm:macro", "The dimension is $\\dimK$.")
            + TWICE
            + ("" if b else env("theorem", "thm:gone", "A result the later revision drops."))
            + "\\section{Bounds}\nIn this section $n \\ge " + ("0" if b else "1") + "$.\n\n"
            + env("theorem", "thm:standing", "The sum is at most $n^2$.")
            + (TWICE if b else "")
            + "\\section{Estimates}\n\n"
            + env("theorem", "thm:est", "Every solution is bounded.")
            + (QUANTIFIER_B if b else QUANTIFIER_A) + "\n"
            + "\\begin{equation}\\label{eq:young}\n  |u| \\le \\varepsilon + C/\\varepsilon,\n"
              "\\end{equation}\n"
            + CONSTANT + "\n"
            + ("An unrelated remark, edited.\n" if b else "An unrelated remark.\n")
            + "\\end{document}\n")


def line_of(text, needle, nth=1):
    i = -1
    for _ in range(nth):
        i = text.index(needle, i + 1)
    return text[:i].count("\n") + 1


def env_claim(root, label, kind, number):
    text = (root / "paper.tex").read_text()
    body = statement_at(root / "paper.tex", line_of(text, f"\\label{{{label}}}"), kind)
    return {"id": f"T:{label}", "paper": "T", "kind": kind, "number": number,
            "location": "paper.tex", "label": label, "scope": "formal", "clauses": [],
            "source_sha256": sha256_text(norm_ws(body))}


def line_claim(root, cid, needle, number, nth=1):
    text = (root / "paper.tex").read_text()
    c = {"id": f"T:{cid}", "paper": "T", "kind": "equation", "number": number,
         "location": f"paper.tex:{line_of(text, needle, nth)}", "scope": "formal",
         "clauses": []}
    r = extract(root, c)
    c.update(source_hash_scheme=SCHEME, source_sha256=r.sha256, source_line_sha256=r.line_sha256)
    return c


def inventories(a, b):
    old = [env_claim(a, "def:bounded", "definition", "Definition 1.1"),
           env_claim(a, "thm:keep", "theorem", "Theorem 1.2"),
           env_claim(a, "thm:moved", "theorem", "Theorem 2.1"),
           env_claim(a, "thm:edit", "theorem", "Theorem 2.2"),
           env_claim(a, "thm:macro", "theorem", "Theorem 2.3"),
           line_claim(a, "eq:twice", "\\label{eq:twice}", "Equation (1)"),
           env_claim(a, "thm:gone", "theorem", "Theorem 2.4"),
           env_claim(a, "thm:standing", "theorem", "Theorem 3.1"),
           env_claim(a, "thm:est", "theorem", "Theorem 4.1"),
           line_claim(a, "eq:young", "\\label{eq:young}", "Equation (2)")]
    new = [env_claim(b, "def:bounded", "definition", "Definition 1.1"),
           env_claim(b, "thm:keep", "theorem", "Theorem 1.2"),
           env_claim(b, "thm:new", "theorem", "Theorem 2.1"),
           env_claim(b, "thm:moved", "theorem", "Theorem 2.2"),
           env_claim(b, "thm:edit", "theorem", "Theorem 2.3"),
           env_claim(b, "thm:macro", "theorem", "Theorem 2.4"),
           line_claim(b, "eq:twice-1", "\\label{eq:twice}", "Equation (1)"),
           env_claim(b, "thm:standing", "theorem", "Theorem 3.1"),
           line_claim(b, "eq:twice-2", "\\label{eq:twice}", "Equation (2)", nth=2),
           env_claim(b, "thm:est", "theorem", "Theorem 4.1"),
           line_claim(b, "eq:young", "\\label{eq:young}", "Equation (3)")]
    return old, new


# The Lean of the synthetic build: each claim's linked declaration, the definitions its statement
# uses, and a declaration the build shows nothing of what its statement uses.
LINKS = {"T:thm:keep": ("Ex.keep", ["Ex.Bounded"]), "T:thm:moved": ("Ex.moved", []),
         "T:thm:edit": ("Ex.edit", []), "T:thm:macro": ("Ex.macro", []),
         "T:eq:young": ("Ex.young", []), "T:thm:standing": ("Ex.standing", []),
         "T:def:bounded": ("Ex.Bounded", [])}
FPS = {"Ex.keep": "fp:keep-1", "Ex.moved": "fp:moved-1", "Ex.edit": "fp:edit-1",
       "Ex.macro": "fp:macro-1", "Ex.young": "fp:young-1", "Ex.standing": "fp:standing-1",
       "Ex.Bounded": "fp:bounded-1", "Ex.other": "fp:other-1"}


def site(work, release, claims, manuscript_root, fps=None):
    """A synthetic build of `claims`: its site data, and its snapshot of the paper's source."""
    fps = {**FPS, **(fps or {})}
    data = work / "site" / "data"
    for d in ("claims", "decls"):
        (data / d).mkdir(parents=True, exist_ok=True)
    for p in (data / "claims").glob("*.json"):
        p.unlink()
    src = work / "sources" / "T"
    src.mkdir(parents=True, exist_ok=True)
    (src / "paper.tex").write_text((manuscript_root / "paper.tex").read_text())
    rows = []
    for c in claims:
        key = c["id"].split(":", 1)[1]
        name, closure = LINKS.get(c["id"], (None, []))
        links = [{"name": name, "fingerprint": fps[name],
                  "statement": {"binders": [], "closure": closure,
                                "conclusion": {"text": "P", "segments": [{"t": "P"}],
                                               "terms": [], "id": "/"}}}] if name else []
        chunk = {"id": c["id"], "paper": "T", "number": c["number"], "kind": c["kind"],
                 "key": key, "source_sha256": c.get("source_sha256"), "links": links,
                 "suggestions": [], "clauses": [],
                 "decls": {"Ex.Bounded": "k-bounded"} if closure else {}}
        f = key.replace(":", "_") + ".json"
        (data / "claims" / f).write_text(json.dumps(chunk))
        rows.append({"id": c["id"], "paper": "T", "number": c["number"], "kind": c["kind"],
                     "file": f})
    (data / "decls" / "k-bounded.json").write_text(json.dumps(
        {"name": "Ex.Bounded", "fingerprint": fps["Ex.Bounded"], "kind": "def", "uses": []}))
    (data / "index.json").write_text(json.dumps(
        {"schema": "prooflens/manifest@1", "release": release,
         "project": {"name": "ex", "commit": "abc123"},
         "papers": [{"id": "T", "title": "Synthetic", "revision": release}], "claims": rows}))
    (data / "lean-index.json").write_text(json.dumps(
        [{"name": n, "kind": "theorem", "module": "Ex.Basic"} for n in fps]))
    return Snapshot(data)


def put(rec):
    return {"op": "put", "record": rec}


def submit(*ids):
    return [{"op": "submit", "id": i, "base_rev": 1} for i in ids]


def region(text, needle):
    return {"file": "paper.tex", "start_line": line_of(text, needle)}


def investigation(work, a):
    """A workspace made against the earlier build: findings on every kind of change."""
    snap = Snapshot(work / "site" / "data")
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    text = (a / "paper.tex").read_text()
    ops = [
        put({"id": "e-keep", "kind": "evidence", "claim": "T:thm:keep", "role": "supports",
             "ref": {"decl": "Ex.keep"}}),
        put({"id": "e-other", "kind": "evidence", "claim": "T:thm:keep", "role": "supports",
             "ref": {"decl": "Ex.other"}}),
        put({"id": "e-moved", "kind": "evidence", "claim": "T:thm:moved", "role": "supports",
             "ref": {"decl": "Ex.moved"}}),
        put({"id": "e-quote", "kind": "evidence", "claim": "T:thm:moved", "role": "context",
             "ref": {"paper": {"claim": "T:thm:edit", "quote": "with constant $2$"}}}),
        put({"id": "e-young", "kind": "evidence", "claim": "T:eq:young", "role": "supports",
             "ref": {"decl": "Ex.young"}}),
        put({"id": "q-eps", "kind": "requirement", "claim": "T:eq:young", "local_id": "r1",
             "form": "for every", "binds": ["ε"], "domain": "ε > 0", "text": "for every ε > 0"}),
        put({"id": "q-c", "kind": "requirement", "claim": "T:eq:young", "local_id": "r2",
             "form": "constant dependence", "binds": ["C"], "independent_of": ["ε"],
             "text": "C independent of ε"}),
        put({"id": "p-eps", "kind": "fragment", "claim": "T:eq:young", "requirement": "r1",
             "role": "quantifier domain", "region": region(text, QUANTIFIER_A)}),
        put({"id": "p-c", "kind": "fragment", "claim": "T:eq:young", "requirement": "r2",
             "role": "constant dependence", "region": region(text, CONSTANT)}),
        # A statement comparison resting on a declaration whose statement uses the definition
        # of Definition 1.1; a note on the same claim that rests on no Lean; and one citing a
        # declaration the build shows nothing of what its statement uses.
        put({"id": "f-keep-lean", "kind": "finding", "claim": "T:thm:keep", "coverage": "full",
             "basis": "direct", "evidence": ["e-keep"], "note": "Ex.keep states it."}),
        put({"id": "f-keep-note", "kind": "finding", "claim": "T:thm:keep",
             "coverage": "partial", "note": "Only the integrability part."}),
        put({"id": "f-keep-other", "kind": "finding", "claim": "T:thm:keep",
             "coverage": "related", "evidence": ["e-other"], "note": "A related result."}),
        put({"id": "f-moved", "kind": "finding", "claim": "T:thm:moved", "coverage": "full",
             "basis": "direct", "evidence": ["e-moved"], "note": "Ex.moved states it."}),
        put({"id": "f-moved-quote", "kind": "finding", "claim": "T:thm:moved",
             "coverage": "partial", "evidence": ["e-moved", "e-quote"],
             "note": "Read with the constant of the next theorem."}),
        put({"id": "f-edit", "kind": "finding", "claim": "T:thm:edit", "coverage": "full",
             "note": "The constant is 2."}),
        put({"id": "f-macro", "kind": "finding", "claim": "T:thm:macro", "coverage": "full",
             "note": "Dimension three."}),
        put({"id": "f-twice", "kind": "finding", "claim": "T:eq:twice", "coverage": "full",
             "note": "x = y."}),
        put({"id": "f-gone", "kind": "finding", "claim": "T:thm:gone", "coverage": "full",
             "note": "Dropped later."}),
        put({"id": "f-standing", "kind": "finding", "claim": "T:thm:standing",
             "coverage": "full", "note": "For n at least one."}),
        put({"id": "f-domain", "kind": "finding", "claim": "T:eq:young", "requirement": "r1",
             "coverage": "full", "evidence": ["e-young"], "note": "Every positive ε."}),
        put({"id": "f-const", "kind": "finding", "claim": "T:eq:young", "requirement": "r2",
             "coverage": "full", "evidence": ["e-young"], "note": "C is uniform."}),
        put({"id": "f-young", "kind": "finding", "claim": "T:eq:young", "coverage": "partial",
             "basis": "direct", "evidence": ["e-young"], "note": "The display."}),
    ]
    wsp.update(p, ops, snap)
    findings = [o["record"]["id"] for o in ops if o["record"]["kind"] == "finding"]
    wsp.update(p, submit(*findings), snap)
    return p


@pytest.fixture
def setting(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root, later in ((a, False), (b, True)):
        root.mkdir()
        (root / "paper.tex").write_text(manuscript(later))
    old, new = inventories(a, b)
    work = tmp_path / ".machinechecked"
    site(work, "r-1", old, a)
    p = investigation(work, a)
    uses = {"T:thm:keep": {"T:def:bounded": ["Ex.Bounded"]}}
    ws = wsp.read(p)
    doc = vm.compare("T", vm.Side(old, a, "r1", uses=uses, identity={"release": "r-1"}),
                     vm.Side(new, b, "r2", uses=uses, identity={"release": "r-2"}),
                     regions=ro.regions_of(ws, "T"))
    return {"a": a, "b": b, "old": old, "new": new, "work": work, "path": p, "map": doc}


def by_id(doc):
    return {f["id"]: f for f in doc["findings"]}


def test_each_finding_is_reopened_exactly_when_what_it_rests_on_changed(setting):
    doc = ro.reopen(setting["map"], wsp.read(setting["path"]))
    assert doc["schema"] == "prooflens/reopened@1" and doc["build_checked"] is False
    f = by_id(doc)
    assert {k: v["state"] for k, v in f.items()} == {
        "f-keep-lean": "reopened", "f-keep-note": "current", "f-keep-other": "unchecked",
        "f-moved": "current", "f-moved-quote": "reopened", "f-edit": "reopened",
        "f-macro": "reopened", "f-twice": "unchecked", "f-gone": "reopened",
        "f-standing": "reopened", "f-domain": "reopened", "f-const": "current",
        "f-young": "current"}
    assert doc["counts"] == {"reopened": 7, "unchecked": 2, "current": 4}
    # Moved and renumbered, the same text: a statement comparison stays current, and says where
    # the passage now is.
    (o,) = f["f-moved"]["paper"]
    assert o["state"] == "current" and o["dependency"]["dependency"] == "passage"
    assert o["note"].startswith("the same text at another place, now Theorem 2.2")
    assert (f["f-moved"]["earlier"]["number"], f["f-moved"]["later"]["number"]) == (
        "Theorem 2.1", "Theorem 2.2")
    # A changed passage: the diff, the dependency and the question.
    (o,) = f["f-edit"]["paper"]
    assert o["state"] == "reopened" and o["text"] == "the passage of T:thm:edit"
    assert "-The bound holds with constant $2$." in o["change"]["diff"]
    assert "+The bound holds with constant $3$." in o["change"]["diff"]
    assert o["question"] == ("Does finding f-edit still hold for the changed text of "
                             "Theorem 2.3 (T:thm:edit)?")
    # A finding on a moved claim that quotes a changed passage is reopened through the quote.
    ch = [o for o in f["f-moved-quote"]["paper"] if o["state"] == "reopened"]
    assert [o["text"] for o in ch] == ["the passage of T:thm:edit it quotes"]
    # The definition of a macro the passage uses.
    (o,) = f["f-macro"]["paper"]
    assert o["change"]["reason"] == "the definition of \\dimK changed"
    assert "+\\newcommand{\\dimK}{4}" in o["change"]["context"][0]["diff"]
    # The standing assumption of its section.
    (o,) = f["f-standing"]["paper"]
    assert o["change"]["reason"] == "the prose opening its section changed"
    # Removed: no other claim takes the finding.
    (o,) = f["f-gone"]["paper"]
    assert o["change"]["class"] == "removed" and f["f-gone"]["later"] is None
    assert o["question"].startswith("Theorem 2.4 (T:thm:gone) is not in the later revision")
    assert o["question"].endswith("A finding is not moved to another claim.")
    # Ambiguous: two later claims carry its label; neither is taken.
    (o,) = f["f-twice"]["paper"]
    assert o["state"] == "unchecked" and "--match" in o["why"]
    assert {x["claim"] for x in o["candidates"]} == {"T:eq:twice-1", "T:eq:twice-2"}


def test_a_definition_the_lean_relies_on_reopens_only_what_cites_that_lean(setting):
    f = by_id(ro.reopen(setting["map"], wsp.read(setting["path"])))
    (o,) = f["f-keep-lean"]["paper"]
    assert o["change"]["reason"] == ("the definition it relies on, Definition 1.1, is changed "
                                     "(through Ex.keep, whose statement uses Ex.Bounded)")
    assert o["question"] == ("Does finding f-keep-lean still hold for Theorem 1.2 (T:thm:keep) "
                             "now that the definition it relies on, Definition 1.1, is changed "
                             "(through Ex.keep, whose statement uses Ex.Bounded)?")
    (x,) = o["change"]["context"]
    assert x["names"] == ["Ex.Bounded"] and x["via"] == ["lean"]
    assert x["through"] == [{"decl": "Ex.keep", "uses": ["Ex.Bounded"]}]
    # The definition's own change comes with it.
    assert any("constant $M$" in ln for ln in x["claim_change"]["diff"])
    # A note that cites no Lean does not rest on it; a declaration whose statement's
    # definitions were not recorded leaves it unknown.
    (o,) = f["f-keep-note"]["paper"]
    assert o["state"] == "current" and "does not rest on" in o["note"]
    (o,) = f["f-keep-other"]["paper"]
    assert o["state"] == "unchecked" and "Ex.other" in o["why"]


def test_a_changed_governing_passage_reopens_the_finding_on_that_reading_only(setting):
    doc = ro.reopen(setting["map"], wsp.read(setting["path"]))
    f = by_id(doc)
    # The display itself moved unchanged, and the sentence that sets its quantifier changed.
    young = next(r for r in setting["map"]["claims"]
                 if (r["from"] or {}).get("claim") == "T:eq:young")
    assert young["class"] == "moved" and young.get("surroundings_changed")
    domain = {o["dependency"].get("record") or o["dependency"]["dependency"]: o
              for o in f["f-domain"]["paper"]}
    o = domain["p-eps"]
    assert o["state"] == "reopened" and o["change"]["class"] == "changed"
    assert "-" + QUANTIFIER_A in o["change"]["diff"] and "+" + QUANTIFIER_B in o["change"]["diff"]
    assert o["question"].startswith("Does finding f-domain (on r1) still hold now that the "
                                    "passage it reads as the quantifier domain of r1")
    assert domain["passage"]["state"] == "current"
    # The constant's sentence moved with its text; the finding on it and the one on the whole
    # display stay current, though an unrelated sentence beside them changed.
    (c,) = [o for o in f["f-const"]["paper"] if o["dependency"].get("record") == "p-c"]
    assert c["state"] == "current" and c["note"].startswith("the same text, now at paper.tex:")
    assert all(o["state"] == "current" for o in f["f-young"]["paper"])
    # The passages attached to requirements, and the evidence quoting the paper.
    assert {r["id"]: r["state"] for r in doc["passages"]} == {"p-eps": "reopened",
                                                              "p-c": "current"}
    assert {r["id"]: r["state"] for r in doc["evidence"]} == {"e-quote": "reopened"}


def test_the_lean_side_is_checked_against_the_later_build_and_kept_apart(setting, tmp_path):
    later = site(tmp_path / "later", "r-2", setting["new"], setting["b"],
                 fps={"Ex.moved": "fp:moved-2"})
    texts = {"Ex.moved": {"from": "Ex.moved : Even = Odd + Odd", "to": "Ex.moved : Even = 2"}}
    doc = ro.reopen(setting["map"], wsp.read(setting["path"]), later, texts=texts.get)
    f = by_id(doc)
    assert doc["build_checked"] is True
    # The paper side of f-moved is current; its declaration changed in the later build.
    assert [o["state"] for o in f["f-moved"]["paper"]] == ["current"]
    assert f["f-moved"]["build"]["state"] == "stale" and f["f-moved"]["state"] == "reopened"
    (ch,) = f["f-moved"]["build"]["changes"]
    assert ch["decl"] == "Ex.moved" and ch["statement"] == texts["Ex.moved"]
    assert ch["question"] == "Does finding f-moved still hold now that Ex.moved changed?"
    # A finding whose Lean did not change keeps the paper's verdict alone.
    assert f["f-young"]["build"]["state"] == "current" and f["f-young"]["state"] == "current"
    # The other build of another release is not taken for the later one.
    other = site(tmp_path / "other", "r-3", setting["new"], setting["b"])
    assert ro.reopen(setting["map"], wsp.read(setting["path"]), other)["build_checked"] is False


def test_the_map_travels_with_the_workspace(setting, tmp_path):
    p, work = setting["path"], setting["work"]
    snap = Snapshot(work / "site" / "data")
    wsp.update(p, [{"op": "version-map", "map": {**setting["map"], "references": None}}], snap)
    ws = wsp.read(p)
    (kept,) = ws["version_maps"]
    assert "references" not in kept and kept["kept_by"] == WHO["id"] and kept["kept_at"]
    assert kept["passages"] == setting["map"]["passages"]
    # Kept again with the same revisions, it replaces the earlier copy.
    wsp.update(p, [{"op": "version-map", "map": setting["map"]}], snap)
    assert len(wsp.read(p)["version_maps"]) == 1
    with pytest.raises(wsp.WorkspaceError, match="schema prooflens/version-map@1"):
        wsp.update(p, [{"op": "version-map", "map": {"claims": []}}], snap)
    data = json.loads(json.dumps(wsp.export(p)))
    other = tmp_path / "elsewhere" / ".machinechecked"
    later = site(other, "r-2", setting["new"], setting["b"])
    res = wsp.import_(other, data, later, "human:B-Auditor")
    assert any(x.startswith("version map ") for x in res["added"])
    got = wsp.read(wsp.find(other, data["id"]))
    assert got["version_maps"] == wsp.read(p)["version_maps"]
    # The importer sees the same reopened findings, without the manuscripts.
    shown = ro.for_site(got, later)
    (m,) = shown["maps"]
    assert m["map"]["from"] == {"release": "r-1"} and m["map"]["to"] == {"release": "r-2"}
    here = ro.reopen(wsp.read(p)["version_maps"][0], wsp.read(p), later)
    assert {f["id"]: f["state"] for f in m["findings"]} == \
        {f["id"]: f["state"] for f in here["findings"]}
    # A build of the earlier release shows the map as kept, for another release.
    assert ro.for_site(got, snap)["maps"] == [] and ro.for_site(got, snap)["other"]
    # Imported again, nothing changes; a differing copy is a conflict, kept as here.
    again = wsp.import_(other, data, later)
    assert again["conflicts"] == []
    data["version_maps"][0]["claims"] = data["version_maps"][0]["claims"][:1]
    clash = wsp.import_(other, data, later)
    assert [c["id"] for c in clash["conflicts"]] == ["version_map"]
    assert wsp.read(wsp.find(other, data["id"]))["version_maps"] == \
        wsp.read(p)["version_maps"]


def test_the_reader_s_route_gives_the_reopened_findings(setting, tmp_path):
    p, work = setting["path"], setting["work"]
    wsp.update(p, [{"op": "version-map", "map": setting["map"]}],
               Snapshot(work / "site" / "data"))
    site(work, "r-2", setting["new"], setting["b"])
    gets, _ = wsp.api(work, work / "site" / "data")
    out = gets["/api/workspace/revision"]({"id": [wsp.read(p)["id"]]})
    (m,) = out["maps"]
    assert out["release"] == "r-2" and m["build_checked"] is True
    assert by_id(m)["f-edit"]["state"] == "reopened"
    assert by_id(m)["f-edit"]["finding"]["note"] == "The constant is 2."


# -- the command, on two stored releases -----------------------------------------------------

def body(claims, regions, anchors, revision):
    assessed = [{"id": c["id"], "status": "formal: open", "status_code": "formal.open",
                 "clauses": []} for c in claims]
    return {"inventory": {"claims": claims}, "reviews": {"files": {}, "records": []},
            "dismissals": [], "lean": None,
            "tex": {"T": {"mode": "latex", "regions": regions, "anchors": anchors}},
            "assessment": {"claims": assessed, "findings": [], "gates": {}},
            "provenance": {"project": {"commit": "c" * 40, "dirty": False},
                           "lean_inputs_sha256": None,
                           "papers": {"T": {"revision": revision, "mode": "latex"}}}}


def release(out, name, claims, root):
    regions = collect({"claims": claims}, "T", root)
    text = (root / "paper.tex").read_text()
    anchors = []
    for c in claims:
        if c.get("location") == "paper.tex":
            ln = line_of(text, f"\\label{{{c['label']}}}")
            anchors.append({"env": c["kind"], "label": c["label"], "file": "paper.tex",
                            "line": ln, "number": c["number"].split()[-1],
                            "source_sha256": sha256_text(norm_ws(statement_at(
                                root / "paper.tex", ln, c["kind"])))})
    ev.record_release(out, name, ev.store(out, body(claims, regions, anchors, None)))


def test_command_reopens_the_workspace_s_findings_and_keeps_the_map(setting, tmp_path, capsys,
                                                                    monkeypatch):
    a, b = setting["a"], setting["b"]
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "paper" / "paper.tex").write_text(manuscript(True))
    (root / "claims.json").write_text(json.dumps({"claims": setting["new"]}))
    (root / "machinechecked.toml").write_text(
        '[project]\nname = "p"\nlean_root = "."\ninventory = "claims.json"\nmodules = ["P"]\n'
        'scope_roots = ["P"]\nspec_prefix = "P.Spec"\naccept_prefix = "P.Acc"\n'
        '[[paper]]\nid = "T"\ntitle = "T"\nsource = { path = "paper" }\nroot = "paper.tex"\n')
    out = root / ".machinechecked"
    release(out, "r-1", setting["old"], a)
    release(out, "r-2", setting["new"], b)
    site(out, "r-1", setting["old"], a)
    p = investigation(out, a)
    wid = wsp.read(p)["id"]
    cfg = str(root / "machinechecked.toml")
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a), "--workspace", wid,
              "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema"] == "prooflens/version-map@1"
    assert {r["region"]["start_line"] for r in doc["passages"]} == {
        line_of(manuscript(False), QUANTIFIER_A), line_of(manuscript(False), CONSTANT)}
    shown = doc["workspace"]
    assert shown["schema"] == "prooflens/reopened@1" and shown["workspace"] == wid
    assert by_id(shown)["f-edit"]["state"] == "reopened"
    # Without --save the workspace keeps nothing.
    assert "version_maps" not in wsp.read(p)
    with pytest.raises(SystemExit):
        cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a), "--save"])
    assert "add --workspace ID" in capsys.readouterr().err
    cli.main(["changes", "-c", cfg, "--map", "--from-source", str(a), "--workspace", wid,
              "--save"])
    text = capsys.readouterr().out
    assert f"workspace {wid} across paper T from release r-1 to release r-2: " in text
    assert "  finding f-edit (T:thm:edit, Theorem 2.2 -> Theorem 2.3): due for review" in text
    assert "    question: Does finding f-edit still hold for the changed text of " \
           "Theorem 2.3 (T:thm:edit)?" in text
    assert "the Lean is not checked here: no site of the later release" in text
    assert f"kept the version map in workspace {wid}" in text
    (kept,) = wsp.read(p)["version_maps"]
    assert kept["from"]["release"] == "r-1" and "workspace" not in kept
    # `workspace show` against a build of the later release judges the findings with the map
    # it keeps, with no manuscript.
    site(out, "r-2", setting["new"], b)
    monkeypatch.chdir(root)
    cli.main(["workspace", "show", "-c", cfg, "--id", wid])
    text = capsys.readouterr().out
    assert "  finding f-gone (T:thm:gone, Theorem 2.4): due for review" in text
    assert "  finding f-moved (T:thm:moved, Theorem 2.1 -> Theorem 2.2): still current" in text
    cli.main(["workspace", "show", "-c", cfg, "--id", wid, "--json"])
    v = json.loads(capsys.readouterr().out)
    assert v["kept_maps"][0]["to"]["release"] == "r-2"
    assert by_id(v["revisions"]["maps"][0])["f-twice"]["state"] == "unchecked"
