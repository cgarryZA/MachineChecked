"""What changed between two releases and which evidence it reopens (`changes.py`, #120).

The first tests compare synthetic evidence records and run no Lean; the last ones build the toy
paper twice or more, changing a definition, a proof, the context of a display, or an unrelated
sentence between builds."""

import copy
import json
import re
from types import SimpleNamespace

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import changes as chg
from prooflens import cli

H = {k: k * 64 for k in "abcdefgh"}


def region(sha, start=1, passage=None, parts=(), notation=()):
    out = {"file": "p.tex", "start_line": start, "end_line": start, "start_column": 1,
           "end_column": 9, "kind": "line", "scheme": "tex-region-v1", "sha256": sha}
    if passage or parts:
        out.update(scheme="tex-regions-v1", passage_sha256=passage or sha,
                   parts=[{"file": "p.tex", "start_line": ln, "sha256": s} for ln, s in parts])
    if notation:
        out["notation"] = [{"macro": m, "sha256": s} for m, s in notation]
    return out


def claim(cid, sha, start=1, clauses=(), scope="formal", number=None, parts=None, lines=None):
    c = {"id": cid, "paper": "P", "number": number, "kind": "theorem", "scope": scope,
         "location": f"p.tex:{start}", "source_hash_scheme": "tex-region-v1",
         "source_sha256": sha, "source_line_sha256": lines or [sha], "clauses": list(clauses)}
    if parts:
        c.update(source_hash_scheme="tex-regions-v1", source_parts=parts)
    return c


def marker(name, fp, cid, sha, by="a.referee", line=3, target="spec"):
    return {"by": by, "kind": "human", "provenance": "self-declared", "file": "reviews.md",
            "line": line, "hash": fp, "name": name, "target": target, "source": {cid: sha},
            "text": "A reading."}


def review(state, current=None, why=None, source_claim=None, readers=None):
    out = {"state": state, "current": [current] if current else [], "stale": [],
           "source_sha256": readers or {}}
    if why:
        out["why"] = why
    if source_claim:
        out["source_claim"] = source_claim
    return out


def decl(name, fp, text, kind="def", source=None):
    out = {"name": name, "kind": kind, "fingerprint": fp, "legacy_hash": fp[-8:],
           "signature": {"text": "Nat → Prop"}, "value": {"text": text}}
    if source:
        out["lean_source"] = {"sha256": source, "text": "…"}
    return out


def record(eid, claims, assessed, decls, specs=None, regions=None, revision="r1",
           commit="c1", lean_inputs="l1"):
    return {"id": eid, "created": "2026-10-21T00:00:00+00:00", "body": {
        "inventory": {"claims": claims},
        "assessment": {"claims": assessed, "findings": [], "gates": {}},
        "lean": {"decls": {d["name"]: d for d in decls}, "specs": specs or {}, "defs": {}},
        "tex": {"P": {"mode": "latex", "regions": regions or {}, "anchors": []}},
        "provenance": {"project": {"commit": commit, "dirty": False},
                       "lean_inputs_sha256": lean_inputs,
                       "papers": {"P": {"revision": revision, "mode": "latex"}}}}}


def assessed(cid, code, clauses=()):
    return {"id": cid, "status": code.replace(".", ": "), "status_code": code,
            "clauses": list(clauses)}


# -- the paper ------------------------------------------------------------------------------

def test_every_class_of_passage_change_and_both_statuses_kept_apart():
    old_claims = [claim("P:same", H["a"]), claim("P:moved", H["b"], 5),
                  claim("P:edit", H["c"], 9), claim("P:eq", H["d"], 12),
                  claim("P:gone", H["e"], 20), claim("P:twice", H["f"], 22),
                  claim("P:lost", H["g"], 30)]
    old_regions = {"P:same": region(H["a"]), "P:moved": region(H["b"], 5),
                   "P:edit": region(H["c"], 9), "P:gone": region(H["e"], 20),
                   "P:twice": region(H["f"], 22), "P:lost": region(H["g"], 30),
                   "P:eq": region("1" * 64, 12, passage=H["d"], parts=[(11, "2" * 64)])}
    new_claims = [claim("P:same", H["a"]), claim("P:moved", H["b"], 6),
                  claim("P:edit", H["c"], 9), claim("P:eq", H["d"], 12),
                  claim("P:renamed", H["e"], 21), claim("P:copy1", H["f"], 23),
                  claim("P:copy2", H["f"], 25), claim("P:lost", H["g"], 30),
                  claim("P:fresh", H["h"], 40)]
    new_regions = {"P:same": region(H["a"]), "P:moved": region(H["b"], 6),
                   "P:edit": region("9" * 64, 9), "P:renamed": region(H["e"], 21),
                   "P:copy1": region(H["f"], 23), "P:copy2": region(H["f"], 25),
                   "P:lost": {"error": "the region does not hold a passage"},
                   "P:fresh": region(H["h"], 40),
                   "P:eq": region("3" * 64, 12, passage=H["d"], parts=[(11, "4" * 64)])}
    old = record("e1", old_claims, [assessed(c["id"], "formal.accepted") for c in old_claims],
                 [], regions=old_regions)
    new = record("e2", new_claims, [assessed(c["id"], "formal.open") for c in new_claims],
                 [], regions=new_regions)
    doc = chg.compare(old, "r-1", new, "r-2")
    by = {c["claim"]: c for c in doc["claims"]}
    cls = {k: v["paper_change"]["class"] for k, v in by.items()}
    assert cls == {"P:same": "unchanged", "P:moved": "moved", "P:edit": "changed",
                   "P:eq": "context-changed", "P:gone": "removed", "P:twice": "ambiguous",
                   "P:lost": "unknown", "P:renamed": "new", "P:copy1": "new", "P:copy2": "new",
                   "P:fresh": "new"}
    # Renumbering proposes a match and carries nothing over; two candidates are never chosen.
    assert by["P:gone"]["paper_change"]["proposed"] == "P:renamed"
    assert "carries no evidence over" in by["P:gone"]["paper_change"]["reason"]
    assert by["P:twice"]["paper_change"]["candidates"] == ["P:copy1", "P:copy2"]
    ctx = by["P:eq"]["paper_change"]["context"]
    assert ctx[0]["what"] == "passage" and ctx[0]["to"]["location"] == "p.tex:11"
    # The changed text no longer matches its pin: that is said, not left implicit.
    assert "still pins the earlier text" in by["P:edit"]["paper_change"]["pin"]
    # Each build's status as it computed it.
    assert by["P:same"]["status"] == {
        "from": {"status": "formal: accepted", "status_code": "formal.accepted"},
        "to": {"status": "formal: open", "status_code": "formal.open"}}
    assert by["P:gone"]["status"]["to"] is None and by["P:fresh"]["status"]["from"] is None
    assert doc["counts"]["claims"]["new"] == 4 and doc["counts"]["status_changed"] == 11
    assert doc["paper_changed"] == {"P": False} and doc["lean_changed"] is False


# -- the Lean and the reviews -----------------------------------------------------------------

SPEC, DEF, THM = "Ex.Spec.main", "Ex.Bounded", "Ex.Acc.main"


def lean_pair(def_text_new="m + 4", proof_new="p2", def_fp_new="fp:def-2"):
    """The same claim in two builds: a proposition whose closure holds a definition. Between
    them the definition's value changes (its name and type do not) and the theorem's proof
    changes (its statement does not)."""
    c = claim("P:main", H["a"], clauses=[{"name": "statement", "spec": SPEC, "accept": THM}],
              number="Theorem 1")
    spec_m = marker(SPEC, "fp:spec", "P:main", H["a"])
    def_m = marker(DEF, "fp:def-1", "P:main", H["a"], line=9, target="def")
    specs = {SPEC: {"fingerprint": "fp:spec", "closure": [DEF], "exact": {"text": "∀ m, Bounded m"}}}

    def cl(def_state, why=None):
        return {"name": "statement", "spec": SPEC, "accept": THM, "accept_ok": True,
                "spec_review": review("reviewed", spec_m, readers={"P:main": H["a"]}),
                "def_reviews": {DEF: review(def_state, def_m if def_state == "reviewed" else None,
                                            why)}}
    old = record("e1", [c], [assessed("P:main", "formal.accepted", [cl("reviewed")])],
                 [decl(DEF, "fp:def-1", "fun m => m + 5"),
                  decl(THM, "fp:thm", "", "theorem", source="p1"),
                  decl(SPEC, "fp:spec", "∀ m, Bounded m")], specs, {"P:main": region(H["a"])})
    stale = cl("stale", "declaration")
    stale["def_reviews"][DEF]["stale"] = [def_m]
    new = record("e2", [c], [assessed("P:main", "formal.review-pending", [stale])],
                 [decl(DEF, def_fp_new, f"fun m => {def_text_new}"),
                  decl(THM, "fp:thm", "", "theorem", source=proof_new),
                  decl(SPEC, "fp:spec", "∀ m, Bounded m")], specs, {"P:main": region(H["a"])},
                 lean_inputs="l2")
    return old, new


def test_a_changed_definition_reopens_the_review_that_read_it_and_not_the_statement_review():
    old, new = lean_pair()
    doc = chg.compare(old, "r-1", new, "r-2")
    c = doc["claims"][0]
    assert c["paper_change"]["class"] == "unchanged" and c["due"]
    ev = {e["name"]: e for e in c["evidence"]}
    # The proposition's own review stands: nothing it read changed, and a review of a
    # statement never reads a proof.
    assert ev[SPEC]["outcome"] == "kept"
    assert ev[SPEC]["kept_through"] == [f"the proof {THM} (accept)"]
    d = ev[DEF]
    assert d["outcome"] == "reopened"
    dep = d["because"][0]
    assert dep["dependency"] == "lean" and dep["name"] == DEF
    assert dep["was"] == "fp:def-1" and dep["now"] == "fp:def-2"
    assert "m + 5" in dep["from"]["text"] and "m + 4" in dep["to"]["text"]
    assert d["question"] == (f"Does {DEF} still mean what Theorem 1 (P:main) needs, now that "
                             "its definition has changed?")
    lean = c["lean"][0]
    assert lean["proposition"]["change"] == "unchanged"
    assert [x["name"] for x in lean["definitions"]] == [DEF]
    assert lean["proofs"][0]["change"] == "proof"
    assert {d["name"]: d["change"] for d in doc["declarations"]} == {DEF: "statement",
                                                                      THM: "proof"}
    assert doc["declarations"][0]["claims"] == ["P:main"]
    assert chg.due(doc)[0]["name"] == DEF
    assert doc["counts"]["evidence"] == {"reopened": 1, "kept": 1}
    out = chg.text(doc)
    assert "due for review" in out and "was: Ex.Bounded : Nat → Prop :=" in out


def test_a_removed_declaration_is_never_rebound_to_another():
    old, new = lean_pair()
    body = new["body"]
    # The later inventory states the claim by another proposition of the same meaning: the
    # earlier review does not move to it.
    body["inventory"]["claims"][0]["clauses"][0]["spec"] = "Ex.Spec.main'"
    cl = body["assessment"]["claims"][0]["clauses"][0]
    cl["spec"] = "Ex.Spec.main'"
    cl["spec_review"] = review("pending")
    doc = chg.compare(old, "r-1", new, "r-2")
    ev = {(e["name"], e["outcome"]) for e in doc["claims"][0]["evidence"]}
    assert (SPEC, "dropped") in ev and ("Ex.Spec.main'", "open") in ev
    assert doc["claims"][0]["lean"][0]["proposition"]["change"] == "renamed"
    # A declaration that is gone reopens its review with the question of which one states it.
    old, new = lean_pair()
    del new["body"]["lean"]["decls"][DEF]
    doc = chg.compare(old, "r-1", new, "r-2")
    d = next(e for e in doc["claims"][0]["evidence"] if e["name"] == DEF)
    assert d["outcome"] == "reopened" and d["because"][0]["to"] is None
    assert "A review is not moved to another declaration" in d["question"]


def test_a_context_change_reopens_with_the_context_named():
    parts_old = [{"location": "p.tex:4", "sha256": H["b"]}]
    parts_new = [{"location": "p.tex:4", "sha256": H["c"]}]
    # The display's own lines keep their pins; the pin of the sentence before it changes.
    c_old = claim("P:eq", H["d"], 5, [{"name": "estimate", "spec": SPEC}], parts=parts_old,
                  lines=[H["a"]])
    c_new = claim("P:eq", H["e"], 5, [{"name": "estimate", "spec": SPEC}], parts=parts_new,
                  lines=[H["a"]])
    m = marker(SPEC, "fp:spec", "P:eq", H["d"])
    specs = {SPEC: {"fingerprint": "fp:spec", "closure": [], "exact": {"text": "S"}}}
    reg = region(H["e"], 5, passage=H["a"], parts=[(4, H["c"])])
    old = record("e1", [c_old], [assessed("P:eq", "formal.accepted", [
        {"name": "estimate", "spec": SPEC, "spec_review": review("reviewed", m),
         "def_reviews": {}}])], [decl(SPEC, "fp:spec", "S")], specs,
        {"P:eq": region(H["d"], 5, passage=H["a"], parts=[(4, H["b"])])})
    # The auditor pinned the changed sentence: the review read the earlier one.
    new = record("e2", [c_new], [assessed("P:eq", "formal.review-pending", [
        {"name": "estimate", "spec": SPEC,
         "spec_review": review("stale", None, "source-changed", "P:eq", {"P:eq": H["e"]}),
         "def_reviews": {}}])], [decl(SPEC, "fp:spec", "S")], specs, {"P:eq": reg})
    doc = chg.compare(old, "r-1", new, "r-2")
    c = doc["claims"][0]
    assert c["paper_change"]["class"] == "context-changed"
    assert c["paper_change"]["repinned"]["passage"] is False
    e = c["evidence"][0]
    assert e["outcome"] == "reopened"
    dep = e["because"][0]
    assert dep == {"dependency": "paper", "claim": "P:eq", "was": H["d"], "now": H["e"],
                   "change": "context-changed", "context": c["paper_change"]["context"]}
    assert e["question"] == f"Does {SPEC} still state P:eq under its changed context (p.tex:4)?"


def test_a_comparison_publishes_only_what_the_papers_allow():
    old, new = lean_pair()
    doc = chg.compare(old, "r-1", new, "r-2")
    closed = SimpleNamespace(source_text=False, lean=False, reviews=False)
    out = chg.public(doc, {"P": closed}, lean_ok=False, reviews_ok=False)
    text = json.dumps(out)
    assert "m + 5" not in text and "p.tex" not in text and "reviews.md" not in text
    assert out["claims"][0]["evidence"][1]["outcome"] == "reopened"
    opened = SimpleNamespace(source_text=True, lean=True, reviews=True)
    assert "m + 5" in json.dumps(chg.public(doc, {"P": opened}, True, True))
    assert chg.public(doc, {"P": opened}, True, True, paper="Q")["claims"] == []
    # The comparison itself is never changed by publishing it.
    assert "m + 5" in json.dumps(doc)


# -- the toy paper, built again after each change -------------------------------------------------

def changes_json(root, capsys, *args):
    capsys.readouterr()
    cli.main(["changes", "-c", str(root / "machinechecked.toml"), "--json", *args])
    return json.loads(capsys.readouterr().out)


@needs_lean
@needs_tex
def test_toy_a_definition_change_and_a_proof_edit(toy, capsys):
    from prooflens import review_cli as rc
    from prooflens import workspace as wsp
    from prooflens.targets import Snapshot
    _, _, cfg = build(toy)
    data = cfg.out_dir / "site" / "data"
    assert not (data / "changes.json").exists(), "a first release has nothing to compare with"
    p = wsp.open_for(cfg.out_dir, rc.parse_reviewer("human:A-Auditor"), "informed")
    wsp.update(p, [
        {"op": "put", "record": {"id": "e-even", "kind": "evidence", "claim": "T:thm:even-add",
                                 "ref": {"decl": "Toy.IsEven"}, "role": "supports"}},
        {"op": "put", "record": {"id": "f-even", "kind": "finding", "claim": "T:thm:even-add",
                                 "coverage": "full", "evidence": ["e-even"], "note": "Direct."}},
        {"op": "put", "record": {"id": "f-tri", "kind": "finding", "claim": "T:thm:triangle",
                                 "coverage": "full", "note": "Direct."}}],
        Snapshot(data), cfg.lean_root)
    # The definition keeps its name and type; a proof changes and its statement does not.
    edit(toy / "lean/Toy/Defs.lean", "∃ k, n = 2 * k", "∃ k, n = k + k")
    edit(toy / "lean/Toy/Acceptance.lean", "intro n hn\n  omega", "intro _ _\n  omega")
    index, body, cfg = build(toy)
    doc = changes_json(toy, capsys, "--workspace", wsp.read(p)["id"])
    by = {c["claim"]: c for c in doc["claims"]}
    assert all(c["paper_change"]["class"] == "unchanged" for c in doc["claims"])
    even = {e["name"]: e for e in by["T:thm:even-add"]["evidence"]}
    assert even["Toy.PaperSpec.thm_even_add"]["outcome"] == "kept"
    assert even["Toy.IsEven"]["outcome"] == "reopened"
    dep = even["Toy.IsEven"]["because"][0]
    assert "2 * k" in dep["from"]["text"] and "k + k" in dep["to"]["text"]
    assert by["T:thm:even-add"]["status"] == {
        "from": {"status": "formal: accepted", "status_code": "formal.accepted"},
        "to": {"status": "formal: proved, review pending",
               "status_code": "formal.review-pending"}}
    assert {e["outcome"] for e in by["T:thm:triangle"]["evidence"]} == {"kept"}
    assert {e["outcome"] for e in by["T:prop:pred"]["evidence"]} == {"kept"}
    # Only the definition's readings are due.
    assert {(d["claim"], d["name"]) for d in chg.due(doc)} == {
        ("T:def:even", "Toy.IsEven"), ("T:thm:even-add", "Toy.IsEven"),
        ("T:cor:even-triangle", "Toy.IsEven")}
    # The workspace's finding that cites the definition is stale; the other stays current.
    rows = {r["id"]: r for r in doc["workspace"]["records"]}
    assert rows["f-even"]["state"] == "stale" and "f-tri" not in rows
    assert rows["e-even"]["changes"][0]["decl"] == "Toy.IsEven"
    # The reader's data and the export carry the same records.
    site = json.loads((cfg.out_dir / "site/data/changes.json").read_text())
    assert chg.due(site) == chg.due({k: v for k, v in doc.items() if k != "workspace"})
    assert json.loads((cfg.out_dir / "site/data/index.json").read_text())["changes"] == \
        "data/changes.json"
    # The review queue offers the reopened definition first, with why (#128).
    queue = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    first = next(u for u in queue["units"] if u["state"] != "reviewed")
    assert first["id"] == "def:Toy.IsEven" and first["priority"]["tier"] == "reopened"
    assert first["reason"].startswith("Reopened since the last release: this definition's Lean "
                                      "changed;")
    assert queue["order"]["signals"]["changes"]["state"] == "read"
    out = toy.parent / "export"
    cli.main(["export", "-c", str(toy / "machinechecked.toml"), "--out", str(out),
              "--data-only"])
    exported = json.loads((out / "data/changes.json").read_text())
    assert json.loads((out / "data/index.json").read_text())["changes"] == "data/changes.json"
    assert chg.due(exported) == chg.due(site)
    # Statuses are those of each build: the comparison changed nothing.
    assert {c["id"]: c["status_code"] for c in index["claims"]} == {
        c["claim"]: c["status"]["to"]["status_code"] for c in doc["claims"]}


def pin_context(root, line, marker=False):
    """Pin the proof step T:eq:bound-range with the sentence at `line` of the toy paper as a
    further passage, as `inventory rebound` does; with `marker`, point its step review at the
    new pin, as a new reading would."""
    from prooflens.source_regions import MULTI, extract, part_claim, pin
    inv = json.loads((root / "claims.json").read_text())
    c = next(c for c in inv["claims"] if c["id"] == "T:eq:bound-range")
    part = {"location": f"toy.tex:{line}"}
    r = extract(root / "paper", part_claim(part))
    part.update(sha256=r.sha256, line_sha256=r.line_sha256)
    c.update(source_parts=[part], source_hash_scheme=MULTI)
    c["source_sha256"] = pin(root / "paper", c).sha256
    (root / "claims.json").write_text(json.dumps(inv, indent=2) + "\n")
    if marker:
        p = root / "reviews" / "T.md"
        p.write_text(re.sub(r"(step-review: T:eq:bound-range )[0-9a-f]{64}",
                            r"\g<1>" + c["source_sha256"], p.read_text()))


@needs_lean
@needs_tex
def test_toy_a_context_change_beside_an_unchanged_display(toy, capsys):
    tex = toy / "paper" / "toy.tex"
    assert tex.read_text().split("\n")[70] == r"Fix $n$. By Theorem~\ref{thm:triangle},"
    pin_context(toy, 71, marker=True)
    build(toy)
    # An unrelated sentence changes: the step's reading stays current.
    edit(tex, "A synthetic paper used to develop", "A synthetic paper written to develop")
    build(toy)
    doc = changes_json(toy, capsys)
    current = doc["to"]["release"]
    step = next(c for c in doc["claims"] if c["claim"] == "T:eq:bound-range")
    assert step["paper_change"]["class"] == "unchanged"
    assert [e["outcome"] for e in step["evidence"]] == ["kept"]
    assert "caveat" not in step["evidence"][0]
    # The sentence that fixes n changes; the display does not.
    edit(tex, r"Fix $n$.", r"Fix $n \ge 1$.")
    build(toy)
    doc = changes_json(toy, capsys)
    step = next(c for c in doc["claims"] if c["claim"] == "T:eq:bound-range")
    p = step["paper_change"]
    assert p["class"] == "context-changed"
    assert p["context"][0]["to"]["location"] == "toy.tex:71"
    # The sentence that changed, in both versions, from the builds' own records.
    assert [(w, t.split(".")[0]) for w, _, t in chg.shown_texts(p)] == [
        ("earlier", "Fix $n$"), ("later", r"Fix $n \ge 1$")]
    # The manuscript no longer matches the step's pin: its reading is unread until the passage
    # is pinned again and read, and the comparison names the passage.
    e = step["evidence"][0]
    assert e["outcome"] == "reopened" and "pin" in p and "caveat" not in e
    assert e["because"][0]["dependency"] == "paper"
    assert e["because"][0]["change"] == "context-changed"
    # Pinned again after the change: from the last build in which it counted, the reading is
    # due, with the changed sentence named.
    pin_context(toy, 71)
    build(toy)
    doc = changes_json(toy, capsys)
    step = next(c for c in doc["claims"] if c["claim"] == "T:eq:bound-range")
    assert [e["outcome"] for e in step["evidence"]] == ["open"]
    doc = changes_json(toy, capsys, "--from", current)
    step = next(c for c in doc["claims"] if c["claim"] == "T:eq:bound-range")
    e = step["evidence"][0]
    assert e["outcome"] == "reopened"
    assert e["because"][0]["change"] == "context-changed"
    assert e["question"] == ("Does the step Equation (3) (T:eq:bound-range) still hold under "
                             "its changed context (toy.tex:71)?")
    capsys.readouterr()
    cli.main(["changes", "-c", str(toy / "machinechecked.toml"), "--from", current])
    assert "question: Does the step Equation (3)" in capsys.readouterr().out
