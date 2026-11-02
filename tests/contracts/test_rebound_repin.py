"""Pinning a passage that changed at a new revision of the paper (#446): after `inventory repin`
moved the inventory, `inventory rebound --repin` pins the claim's text at the new revision, on
synthetic manuscripts."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from prooflens import rebound
from prooflens.assess import Assessor, unpinned_passages
from prooflens.rebound import rebound_plan
from prooflens.review_sources import marker_state
from prooflens.reviews import Review
from prooflens.source_regions import SCHEME, RegionError, collect, extract, matches
from prooflens.util import norm_ws
from prooflens.versions import VersionError, check, manuscript_record
from test_repin import A, NEW, OLD, commit, line_of, pinned, project, run, write  # noqa: F401

PARA = ("First line of the claim.\nSecond line.\nThird line.\nFourth line.\nFifth line.\n"
        "Sixth line.\nLast line of the claim.\n")
EDITED = PARA.replace("Sixth line.", "Sixth line, edited.")
AFTER = "\nA later paragraph.\n"


def span_claim(root, cid="p", passage=PARA, **extra):
    first = line_of(root, passage)
    end = first + passage.count("\n") - 1
    return pinned(root, cid, passage, scope_reviewed=True,
                  source_region={"end_line": end}, **extra)


def rebound_run(proj, *args, capsys):
    try:
        code = rebound.main(["--config", str(proj / "machinechecked.toml"), "--paper", "T",
                             *args])
    except SystemExit as exit:
        code = exit.code
    out = capsys.readouterr()
    return code, out.out, out.err


def inventory_of(proj):
    return json.loads((proj / "claims.json").read_text(encoding="utf-8"))


def by_id(inv):
    return {c["id"]: c for c in inv["claims"]}


def assessment(inv, regions, read):
    """The assessment of the inventory's claims at a revision whose regions are `regions`, with
    one review of each claim's proposition that read the passage digest `read[claim]`."""
    fp = "synthetic-fingerprint"
    claims = [{**c, "clauses": [{"name": "main", "spec": f"S.{c['id'][2:]}",
                                 "accept": f"A.{c['id'][2:]}"}]} for c in inv["claims"]]
    lean = {"specs": {f"S.{c['id'][2:]}": {"fingerprint": fp, "errors": [], "closure": [],
                                          "binders": [], "consts": []} for c in claims},
            "proofs": {f"accept:A.{c['id'][2:]}:S.{c['id'][2:]}": {
                "errors": [], "sorry": False, "axioms": []} for c in claims},
            "decls": {}, "defs": {}, "layering": []}
    reviews = [Review("spec", f"S.{cid[2:]}", fp, "a-referee", "human", "self-declared",
                      "reviews.md", 1, "Synthetic review.", source={cid: sha})
               for cid, sha in read.items()]
    tex = {"T": {"mode": "latex", "anchors": [], "envs": [], "regions": regions}}
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)
    return Assessor(cfg, {"claims": claims}, lean, tex, reviews, []).run()


def test_a_passage_given_its_proposed_bounds_is_pinned_at_the_new_revision(project, capsys):
    repo, proj, first = project
    old_rev = commit(repo, A, "Before.\n\n", PARA, AFTER)
    claims = [pinned(repo, "a", A, scope_reviewed=True), span_claim(repo)]
    inv = {"papers": {"T": {"commit": old_rev[:7]}}, "claims": claims}
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    toml = proj / "machinechecked.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(first, old_rev), encoding="utf-8")
    read = {c["id"]: c["source_sha256"] for c in claims}
    second = commit(repo, A, "Inserted.\n", "Before.\n\n", EDITED, AFTER)
    start = line_of(repo, EDITED)
    code, out, err = run(proj, "--to", second, "--accept-bounds", "T:p", "--write",
                         capsys=capsys)
    assert code == 0, err

    # The claim has the new bounds and the old digests and revision: the source check reports
    # it at the new revision, and plain `rebound` at that revision refuses it.
    moved = inventory_of(proj)
    p = by_id(moved)["T:p"]
    assert p["location"] == f"paper.tex:{start}" and p["commit"] == old_rev[:7]
    assert p["source_sha256"] == read["T:p"]
    regions = collect(moved, "T", repo)
    assert not matches(p, {"regions": regions})
    assert "T:p" in unpinned_passages(moved, {"T": {"mode": "latex", "regions": regions}})
    findings = assessment(moved, regions, read)["findings"]
    assert any(f["code"] == "source-changed" and f["subject"] == "T:p" for f in findings)
    with pytest.raises(VersionError, match="pinned to"):
        check(SimpleNamespace(id="T"), manuscript_record(second), True, moved)
    code, _, err = rebound_run(proj, "--claim", "T:p", "--lines", f"{start}-{start + 6}",
                               capsys=capsys)
    assert code == 2 and "it is pinned at revision" in err and "--repin" in err

    # Pinned again: the plan first, then the write.
    before = (proj / "claims.json").read_bytes()
    code, out, err = rebound_run(proj, "--claim", "T:p", "--repin", capsys=capsys)
    assert code == 0, err
    assert (proj / "claims.json").read_bytes() == before, "a plan writes nothing"
    (entry,) = json.loads(out)["changes"]
    assert entry["commit"] == {"before": old_rev[:7], "after": second[:7]}
    assert entry["old"] == {"file": "paper.tex", "start_line": start, "end_line": start + 6,
                            "revision": old_rev[:7]}
    assert entry["new"]["first"] == "First line of the claim."
    assert entry["new"]["last"] == "Last line of the claim."
    assert entry["where"] == f"line 6 of the passage (line {start + 5} of paper.tex) changed"
    assert entry["scope_reviewed"] == {"before": True, "after": False}
    assert entry["old_sha256"] == read["T:p"] != entry["sha256"]
    code, out, err = rebound_run(proj, "--claim", "T:p", "--repin", "--write", capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is True, err

    after = inventory_of(proj)
    p = by_id(after)["T:p"]
    region = extract(repo, p)
    assert p["commit"] == second[:7] and p["location"] == f"paper.tex:{start}"
    assert p["source_sha256"] == region.sha256 and p["source_line_sha256"] == region.line_sha256
    assert p["source_hash_scheme"] == SCHEME and p["scope_reviewed"] is False
    assert by_id(after)["T:a"] == by_id(moved)["T:a"]
    regions = collect(after, "T", repo)
    assert matches(p, {"regions": regions})
    assert unpinned_passages(after, {"T": {"mode": "latex", "regions": regions}}) == {}
    check(SimpleNamespace(id="T"), manuscript_record(second), True, after)

    # The new text stays visible as changed: the reading of the old text no longer counts, the
    # scope decision is open, and a reading at the new pin is what restores the review.
    marker = SimpleNamespace(source={"T:p": read["T:p"]})
    assert marker_state(marker, "T:p", p["source_sha256"]) == "changed"
    out = assessment(after, regions, read)
    assert not any(f["code"] == "source-changed" for f in out["findings"])
    row = next(c for c in out["claims"] if c["id"] == "T:p")
    assert row["status"] == "formal: proved, review pending"
    assert row["clauses"][0]["spec_review"]["why"] == "source-changed"
    assert next(c for c in out["claims"] if c["id"] == "T:a")["status"] == "formal: accepted"
    out = assessment(after, regions, {**read, "T:p": p["source_sha256"]})
    row = next(c for c in out["claims"] if c["id"] == "T:p")
    assert row["status"] == "formal: accepted"
    # Its scope decision, taken on the earlier text, is still to be read again.
    assert any("not checked by reading" in b for b in row["blockers"])

    # Again: nothing more is written, and a repin to the same revision finds every claim
    # unchanged.
    done = (proj / "claims.json").read_bytes()
    code, out, err = rebound_run(proj, "--claim", "T:p", "--repin", "--write", capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is False, err
    assert json.loads(out)["changes"][0]["unchanged"] is True
    assert (proj / "claims.json").read_bytes() == done
    code, out, err = run(proj, "--to", second, capsys=capsys)
    assert code == 0 and json.loads(out)["counts"] == {"unchanged": 2}, err


def test_new_bounds_at_the_new_revision_and_the_advice_a_build_gives(tmp_path):
    """A passage that is not found, or whose proposal is flagged, takes bounds given by hand;
    the plan gives the region advice and the macros its text uses."""
    old = write(tmp_path / "old", "\\newcommand{\\rate}{1/2}\n", PARA, AFTER)
    claim = span_claim(old)
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [{**claim, "commit": OLD[:7]}]}
    new = write(tmp_path / "new", "\\newcommand{\\rate}{1/2}\n\\newcommand{\\R}{x}\n\n",
                "Rewritten opening, at rate $\\rate$ in $\\R$, and\n", "a second line.\n",
                AFTER)
    first = line_of(new, "Rewritten")
    req = {"claim": "T:p", "start": first, "end": first}
    result, (entry,) = rebound_plan(inv, "T", new, NEW, [req], repin=True)
    c = result["claims"][0]
    assert c["location"] == f"paper.tex:{first}" and c["source_region"] == {"end_line": first}
    assert c["source_sha256"] == extract(new, c).sha256 and c["commit"] == NEW[:7]
    assert [a["kind"] for a in entry["advice"]] == ["ends-mid-sentence"]
    assert "ends inside a sentence" in entry["advice"][0]["message"]
    assert [m["macro"] for m in entry["macros"]] == ["\\R", "\\rate"]
    # The paper's notation macros give no advice, as in a build.
    _, (entry,) = rebound_plan(inv, "T", new, NEW, [req], repin=True, notation=["\\R"])
    assert [m["macro"] for m in entry["macros"]] == ["\\rate"]
    # The checks of any new bounds apply.
    with pytest.raises(RegionError, match="blank or comment-only"):
        rebound_plan(inv, "T", new, NEW, [{**req, "end": first + 2}], repin=True)


def test_a_passage_whose_text_is_the_same_keeps_its_scope_decision(tmp_path):
    old = write(tmp_path / "old", PARA, AFTER)
    claim = {**span_claim(old), "commit": OLD[:7]}
    new = write(tmp_path / "new", "Inserted.\n", PARA, AFTER)
    first = line_of(new, PARA)
    claim.update(location=f"paper.tex:{first}", source_region={"end_line": first + 6})
    inv = {"papers": {"T": {"commit": NEW}}, "claims": [claim]}
    result, (entry,) = rebound_plan(inv, "T", new, NEW, [{"claim": "T:p", "start": None}],
                                    repin=True)
    c = result["claims"][0]
    assert c["commit"] == NEW and c["source_sha256"] == claim["source_sha256"]
    assert c["scope_reviewed"] is True and "scope_reviewed" not in entry
    assert "where" not in entry


def test_what_repin_refuses(tmp_path):
    old = write(tmp_path / "old", PARA, AFTER)
    claim = span_claim(old)
    new = write(tmp_path / "new", EDITED, AFTER)
    keep = {"claim": "T:p", "start": None}
    # The paper itself must be pinned at the snapshot's revision.
    inv = {"papers": {"T": {"commit": OLD[:7]}}, "claims": [claim]}
    with pytest.raises(RegionError, match="paper is pinned at revision"):
        rebound_plan(inv, "T", new, NEW, [keep], repin=True)
    # Without --repin, a claim of another revision is refused, as before.
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [{**claim, "commit": OLD[:7]}]}
    with pytest.raises(RegionError, match="pin it at this one with --repin"):
        rebound_plan(inv, "T", new, NEW, [{"claim": "T:p", "start": 1}])
    # A claim already pinned at this revision must match it here: a snapshot that is not that
    # revision's text is never given its digests.
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [claim]}
    with pytest.raises(RegionError, match="differs from its pin"):
        rebound_plan(inv, "T", new, NEW, [keep], repin=True)
    # A claim without a pin or a recorded revision.
    bare = {k: v for k, v in claim.items() if not k.startswith("source_")}
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [{**bare, "commit": OLD[:7]}]}
    with pytest.raises(RegionError, match="no source pin"):
        rebound_plan(inv, "T", new, NEW, [keep], repin=True)
    with pytest.raises(RegionError, match="records no paper revision"):
        rebound_plan({"claims": [claim]}, "T", new, NEW, [keep], repin=True)


def test_a_pinned_macro_definition_is_delimited_again_at_the_new_revision(tmp_path):
    macro = "\\newcommand{\\bound}{C}\n"
    old = write(tmp_path / "old", macro, PARA, AFTER)
    claim = span_claim(old)
    part = extract(old, {"location": "paper.tex:4"})
    claim.update(source_hash_scheme="tex-regions-v1", source_parts=[
        {"location": "paper.tex:4", "macro": "\\bound", "sha256": part.sha256,
         "line_sha256": part.line_sha256}], commit=OLD[:7])
    new = write(tmp_path / "new", "\\newcommand{\\bound}{%\n  2C}\n", PARA, AFTER)
    first = line_of(new, PARA)
    claim.update(location=f"paper.tex:{first}", source_region={"end_line": first + 6})
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [claim]}
    result, (entry,) = rebound_plan(inv, "T", new, NEW, [{"claim": "T:p", "start": None}],
                                    repin=True)
    (stored,) = result["claims"][0]["source_parts"]
    assert stored["location"] == "paper.tex:4" and stored["end_line"] == 5
    assert entry["where"] == "line 1 of part 1 (the definition of \\bound) (line 4 of " \
        "paper.tex) changed"
    assert result["claims"][0]["scope_reviewed"] is False


# -- a claim pinned by its environment -------------------------------------------------------

THM = "\\begin{theorem}\\label{thm:t}\nEvery even number is a sum of two even numbers.\n" \
      "\\end{theorem}\n"
NOLABEL = "\\begin{theorem}\nZero is even.\n\\end{theorem}\n"


def env_hash(body):
    return hashlib.sha256(norm_ws(body).encode("utf-8")).hexdigest()


def test_a_changed_environment_is_pinned_by_its_label(tmp_path):
    thm = {"id": "T:thm:t", "paper": "T", "kind": "theorem", "label": "thm:t",
           "location": "paper.tex", "scope": "formal", "scope_reviewed": True,
           "source_sha256": env_hash("\\label{thm:t}\nEvery even number is a sum of two even "
                                     "numbers."), "commit": OLD[:7], "clauses": []}
    numbered = {"id": "T:thm:zero", "paper": "T", "kind": "theorem", "number": "Theorem 2",
                "location": "paper.tex", "scope": "formal", "commit": OLD[:7], "clauses": [],
                "source_sha256": env_hash("Zero is even.")}
    new = write(tmp_path / "new", "Intro.\n", THM.replace("two even", "two even or two odd"),
                NOLABEL)
    (new / "paper.tex").write_text("\\newtheorem{theorem}{Theorem}\n"
                                   + (new / "paper.tex").read_text(), encoding="utf-8")
    inv = {"papers": {"T": {"commit": NEW[:7]}}, "claims": [thm, numbered]}
    keep = {"claim": "T:thm:t", "start": None}
    result, (entry,) = rebound_plan(inv, "T", new, NEW, [keep], repin=True)
    c = result["claims"][0]
    body = "\\label{thm:t}\nEvery even number is a sum of two even or two odd numbers."
    assert c["source_sha256"] == env_hash(body) == entry["sha256"]
    assert c["commit"] == NEW[:7] and c["location"] == "paper.tex"
    assert c["scope_reviewed"] is False and entry["pin"] == "environment"
    assert entry["new"] == {"file": "paper.tex", "start_line": line_of(new, "\\begin{theorem}"
                                                                      "\\label"),
                            "environment": "theorem"}
    # Pinned at this revision, it is verified here and left as it is.
    _, (again,) = rebound_plan(result, "T", new, NEW, [keep], repin=True)
    assert again["unchanged"] is True
    # Its bounds are the environment's own; a claim found only by its number is refused.
    with pytest.raises(RegionError, match="whose bounds are the environment's own"):
        rebound_plan(inv, "T", new, NEW, [{"claim": "T:thm:t", "start": 3}], repin=True)
    with pytest.raises(RegionError, match="printed number"):
        rebound_plan(inv, "T", new, NEW, [{"claim": "T:thm:zero", "start": None}], repin=True)


def test_command_options(project, capsys):
    repo, proj, _ = project
    code, _, err = rebound_run(proj, "--claim", "T:a", capsys=capsys)
    assert code == 2 and "give one --lines for each --claim" in err
    code, _, err = rebound_run(proj, "--claim", "T:a", "--repin", "--file", "x.tex",
                               capsys=capsys)
    assert code == 2 and "give --lines" in err
    code, _, err = rebound_run(proj, "--claim", "T:a", "--claim", "T:b", "--lines", "4",
                               "--repin", capsys=capsys)
    assert code == 2 and "or none to keep their present bounds" in err
