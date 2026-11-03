"""#507: a change to the notation macros reopens the readings of the passages that use them; the
plan (`machinechecked inventory notation`) reports which, before the configuration changes, and
writes nothing. Synthetic manuscript and reviews."""

import json
from types import SimpleNamespace

import pytest

from prooflens import evidence as ev
from prooflens.assess import Assessor
from prooflens.notation_plan import lists, main, plan
from prooflens.review_sources import attribute, digests
from prooflens.reviews import Review
from prooflens.source_regions import SCHEME, RegionError, collect, extract

REV = "a" * 40
MAIN = ("\\documentclass{article}\n\\input{values}\n\\begin{document}\n"        # 1-3
        "The estimator is unbiased, and it converges in $\\iterCount$ steps.\n"  # 4
        "The variance of the estimator is of order $1/n$.\n"                     # 5
        "\\end{document}\n")
VALUES = "% generated\n\\newcommand{\\iterCount}{42}\n"
FP = {"Synthetic.est": "synthetic-fingerprint-est", "Synthetic.var": "synthetic-fingerprint-var"}


def manuscript(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(MAIN, encoding="utf-8")
    (root / "values.tex").write_text(VALUES, encoding="utf-8")
    return root


def claims(root):
    """Two formal claims: one whose passage uses \\iterCount, one whose passage does not."""
    out = []
    for cid, line, spec in (("T:est", 4, "Synthetic.est"), ("T:var", 5, "Synthetic.var")):
        c = {"id": cid, "paper": "T", "location": f"main.tex:{line}", "scope": "formal",
             "scope_reviewed": True,
             "clauses": [{"name": "main", "spec": spec, "accept": spec + "_proof"}]}
        r = extract(root, c)
        out.append({**c, "source_hash_scheme": SCHEME, "source_sha256": r.sha256,
                    "source_line_sha256": r.line_sha256})
    return {"papers": {"T": {"commit": REV[:7]}}, "claims": out}


LEAN = {"specs": {n: {"fingerprint": fp, "errors": [], "closure": [], "binders": [],
                      "consts": []} for n, fp in FP.items()},
        "proofs": {f"accept:{n}_proof:{n}": {"errors": [], "sorry": False, "axioms": []}
                   for n in FP},
        "decls": {}, "defs": {}, "layering": []}
COMPARATOR = json.dumps({"commit": REV, "replayed": [n + "_proof" for n in FP]})


def cfg(root):
    return SimpleNamespace(statement_authors=[], papers=[SimpleNamespace(id="T")],
                           lean_root=root)


def body_of(root, inv, notation):
    """The evidence a build with the notation macros `notation` stores (its source evidence
    and Lean facts)."""
    tex = {"T": {"mode": "latex", "envs": [], "anchors": [],
                 "regions": collect(inv, "T", root, notation)}}
    return {"tex": tex, "lean": LEAN, "provenance": {"project": {"commit": REV}}}


def reviews_read(inv, body):
    """A review of each proposition, each recording the digests a reading made under the
    build `body` records."""
    return [Review("spec", n, fp, "synthetic-reviewer", "human", "self-declared", "reviews.md",
                   10 * k + 5, "Synthetic review.", source=digests(inv, "spec", n, body["tex"]))
            for k, (n, fp) in enumerate(FP.items())]


def test_listing_a_macro_reports_the_readings_it_reopens(tmp_path):
    root = manuscript(tmp_path)
    inv = claims(root)
    body = body_of(root, inv, [])
    reviews = reviews_read(inv, body)
    # Today both claims are accepted, and the readings recorded the pins alone.
    now = Assessor(cfg(root), inv, LEAN, body["tex"], reviews, [], COMPARATOR, REV).run()
    assert [c["status"] for c in now["claims"]] == ["formal: accepted"] * 2
    out = plan(cfg(root), inv, body, reviews, [], COMPARATOR, {"T": root},
               {"T": ([], ["\\iterCount"])})
    assert out["passages"] == [{"claim": "T:est",
                                "notation": {"now": [], "proposed": ["\\iterCount"]}}]
    (m,) = out["reopened"]
    assert (m["file"], m["line"], m["by"], m["target"], m["name"]) == (
        "reviews.md", 5, "synthetic-reviewer", "spec", "Synthetic.est")
    assert m["reviews"] == [{"claim": "T:est", "passages": ["T:est"], "state": "stale",
                             "why": "source-notation-unrecorded", "source_claim": "T:est"}]
    assert out["restored"] == []
    assert out["statuses"] == [{"claim": "T:est", "now": "formal: accepted",
                                "proposed": "formal: proved, review pending"}]
    # The plan changes nothing it read.
    assert body == body_of(root, inv, []) and reviews == reviews_read(inv, body)


def test_leaving_a_macro_out_reopens_the_readings_that_recorded_it(tmp_path):
    root = manuscript(tmp_path)
    inv = claims(root)
    body = body_of(root, inv, ["\\iterCount"])
    reviews = reviews_read(inv, body)
    assert "T:est" in attribute(reviews[0].source)
    out = plan(cfg(root), inv, body, reviews, [], COMPARATOR, {"T": root},
               {"T": (["\\iterCount"], [])})
    (m,) = out["reopened"]
    assert m["name"] == "Synthetic.est" and m["reviews"][0]["why"] == "source-changed"
    assert [s["claim"] for s in out["statuses"]] == ["T:est"]
    # Readings that recorded only the pin count again without the macro: none here, since
    # each recorded the notation; a marker that recorded the pin is restored.
    old = [Review("spec", "Synthetic.est", FP["Synthetic.est"], "earlier-reviewer", "human",
                  "self-declared", "reviews.md", 2, "An earlier review.",
                  source={"T:est": inv["claims"][0]["source_sha256"]})]
    out = plan(cfg(root), inv, body, old, [], COMPARATOR, {"T": root},
               {"T": (["\\iterCount"], [])})
    assert [(m["line"], m["by"]) for m in out["restored"]] == [(2, "earlier-reviewer")]
    assert out["reopened"] == []


def test_a_release_made_with_another_list_or_text_is_refused(tmp_path):
    root = manuscript(tmp_path)
    inv = claims(root)
    body = body_of(root, inv, ["\\iterCount"])
    with pytest.raises(RegionError, match="run `machinechecked build` first"):
        plan(cfg(root), inv, body, [], [], COMPARATOR, {"T": root},
             {"T": ([], ["\\iterCount"])})
    config = SimpleNamespace(paper=lambda pid: SimpleNamespace(notation_macros=["\\R"]))
    assert lists(config, ["T"], ["iterCount", "R"], []) == {
        "T": (["\\R"], ["\\R", "\\iterCount"])}
    assert lists(config, ["T"], [], ["\\R"]) == {"T": (["\\R"], [])}
    with pytest.raises(RegionError, match="is not a notation macro"):
        lists(config, ["T"], [], ["E"])


def project(tmp_path, notation=""):
    """A synthetic project with a stored release, as a build of it leaves it."""
    paper = manuscript(tmp_path / "paper")
    inv = claims(paper)
    (tmp_path / "claims.json").write_text(json.dumps(inv), encoding="utf-8")
    (tmp_path / "machinechecked.toml").write_text(
        '[project]\nname = "t"\nmodules = []\nscope_roots = []\nspec_prefix = "Synthetic"\n'
        'accept_prefix = "Synthetic"\ninventory = "claims.json"\nreviews = ["reviews.md"]\n'
        + notation + '[[paper]]\nid = "T"\nsource = { path = "paper" }\nroot = "main.tex"\n',
        encoding="utf-8")
    body = body_of(paper, inv, ["\\iterCount"] if notation else [])
    text = "".join(
        f"## {n}\n\nSynthetic review of {n}.\n\n<!-- spec-review: {n} {fp} "
        f"by=synthetic-reviewer kind=human {attribute(digests(inv, 'spec', n, body['tex']))} "
        "-->\n\n" for n, fp in FP.items())
    (tmp_path / "reviews.md").write_text(text, encoding="utf-8")
    out = tmp_path / ".machinechecked"
    eid = ev.store(out, {**body, "inventory": {"claims": inv["claims"]},
                         "provenance": {"tool": {}, "project": {"commit": REV}, "papers": {}}})
    ev.record_release(out, "r-synthetic", eid)
    return tmp_path


def test_the_command_reports_from_the_latest_release_and_writes_nothing(tmp_path, capsys):
    proj = project(tmp_path)
    before = {p: p.read_bytes() for p in proj.rglob("*") if p.is_file()}
    code = main(["--config", str(proj / "machinechecked.toml"), "--add", "iterCount"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["release"] == "r-synthetic"
    assert out["notation_macros"] == {"T": {"now": [], "proposed": ["\\iterCount"]}}
    assert out["counts"] == {"passages": 1, "reopened": 1, "restored": 0, "statuses": 1}
    assert (out["reopened"][0]["file"], out["reopened"][0]["line"]) == ("reviews.md", 5)
    assert {p: p.read_bytes() for p in proj.rglob("*") if p.is_file()} == before
    # The list as configured: the release was made with it.
    proj2 = project(tmp_path / "listed", 'notation_macros = ["iterCount"]\n')
    code = main(["--config", str(proj2 / "machinechecked.toml"), "--remove", "\\iterCount"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["counts"]["reopened"] == 1
    assert out["reopened"][0]["reviews"][0]["why"] == "source-changed"
    # Nothing to change, or no release to read: refused.
    with pytest.raises(SystemExit) as e:
        main(["--config", str(proj / "machinechecked.toml")])
    assert e.value.code == 2 and "--add" in capsys.readouterr().err
