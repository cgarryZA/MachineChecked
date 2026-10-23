"""The full assessment builds the content index and checks the Lean's references to the paper's
numbers, as zero configuration does (#179): from the Lean facts store, beside the evidence and
never inside it, published only with the Lean, and left out of a bundle above a size limit. It
changes no status.

The toy formalisation's docstrings cite numbers of an earlier version of its paper: the
docstring of `Toy.PaperSpec.thm_bound` says Theorem 2.4, where the paper has Remark 2.4."""

import json

from conftest import ROOT, edit, needs_lean, needs_tex
from prooflens import cli
from prooflens import config as cfgmod
from prooflens import evidence as ev
from prooflens.compare import Site, search
from prooflens.pipeline import build, rebuild_site, reassess

WEB = ROOT / "engine" / "python" / "prooflens" / "web"


def run(root, **kw):
    lines = []
    cfg = cfgmod.load(root / "machinechecked.toml")
    res = build(cfg, log=lambda *a: lines.append(" ".join(map(str, a))), **kw)
    return res, cfg, lines


def stale(num):
    return [o for o in num["references"] if o["source"].get("declaration") ==
            "Toy.PaperSpec.thm_bound" and o["source"]["where"] == "docstring"]


@needs_lean
@needs_tex
def test_the_full_assessment_searches_content_and_checks_paper_numbers(toy, monkeypatch, capsys):
    res, cfg, lines = run(toy)
    data = cfg.out_dir / "site" / "data"
    index = json.loads((data / "index.json").read_text())

    # The content index of every declaration of the built modules, read by the reader and by
    # `compare`; the specification and acceptance layers are in it, and so is the rest.
    assert index["retrieval"] == "data/retrieval.json"
    names = {d["name"] for d in json.loads((data / "retrieval.json").read_text())["docs"]}
    assert {"Toy.PaperSpec.thm_bound", "Toy.Acceptance.thm_bound", "Toy.triangle"} <= names
    found = search(Site(data), "T:thm:triangle")
    assert found["available"] and found["results"]
    assert "Toy.Acceptance.thm_triangle" in [r["name"] for r in found["results"][:3]]

    # The stale citation, with its source, on its claim and in the project-level pattern.
    (o,) = stale(res["content"]["numbering"])
    assert (o["reference"], o["status"]) == ("Theorem 2.4", "other-kind")
    assert o["source"]["file"] == "Toy/PaperSpec.lean" and o["source"]["line"]
    assert index["numbering"]["other_kind"] >= 1
    chunk = json.loads((data / "claims" / next(
        c["file"] for c in index["claims"] if c["id"] == "T:thm:bound")).read_text())
    assert o["id"] in [r["id"] for r in chunk["references"]]
    assert Site(data).numbering()["references"]

    # Display only: the evidence record holds none of it, and no status depends on it.
    body = ev.load(cfg.out_dir, res["evidence"])["body"]
    assert "retrieval" not in json.dumps(body["assessment"])
    assert not any(k in body for k in ("retrieval", "numbering", "content"))

    # A second build reads the index from the facts store: no Lean session indexes a module.
    res2, _, lines = run(toy)
    assert res2["evidence"] == res["evidence"]
    assert not any("indexing" in l for l in lines)
    assert any("reusing the stored index" in l for l in lines)

    # `check` lists the stale reference with its source; `check --json` gives it as a warning.
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert any("Toy/PaperSpec.lean" in l and "Theorem 2.4" in l and "warning" in l
               for l in out.splitlines())
    try:
        cli.main(["check", "--json"])
    except SystemExit:
        pass
    doc = json.loads(capsys.readouterr().out)
    (w,) = [w for w in doc["warnings"] if w["id"] == o["id"]]
    assert (w["kind"], w["file"], w["reference"]) == ("paper-reference", "Toy/PaperSpec.lean",
                                                       "Theorem 2.4")
    assert doc["numbering"]["pattern"]["references"] >= 1


@needs_lean
@needs_tex
def test_content_follows_its_evidence_and_the_lean_publication(toy, tmp_path):
    res, cfg, _ = run(toy)
    data = cfg.out_dir / "site" / "data"

    # The site rebuilt from the release, and a reassessment of it, keep the content.
    (data / "retrieval.json").unlink()
    rebuild_site(cfg)
    assert (data / "retrieval.json").exists() and (data / "numbering.json").exists()
    reassess(cfg)
    assert json.loads((data / "index.json").read_text())["retrieval"] == "data/retrieval.json"

    # The public export carries it while the paper publishes its Lean ...
    from prooflens.export import export
    export(cfg, tmp_path / "pub")
    pidx = json.loads((tmp_path / "pub/data/index.json").read_text())
    assert pidx["retrieval"] == "data/retrieval.json"
    assert (tmp_path / "pub/data/retrieval.json").exists()
    assert (tmp_path / "pub/data/numbering.json").exists()
    # ... and not otherwise.
    edit(toy / "machinechecked.toml", "lean = true", "lean = false")
    cfg = cfgmod.load(toy / "machinechecked.toml")
    export(cfg, tmp_path / "pub2")
    assert "retrieval" not in json.loads((tmp_path / "pub2/data/index.json").read_text())
    assert not (tmp_path / "pub2/data/retrieval.json").exists()
    assert not (tmp_path / "pub2/data/numbering.json").exists()


@needs_lean
@needs_tex
def test_a_bundle_leaves_out_a_content_index_over_its_limit(toy, tmp_path):
    import re
    from prooflens.bundle import bundle
    res, cfg, _ = run(toy, web_dist=WEB)
    site = cfg.out_dir / "site"
    if not (site / "index.html").exists():
        import pytest
        pytest.skip("web app not built")

    def carried(out):
        html = out.read_text()
        return json.loads(re.search(r"window.__PROOFLENS__ = (.*?);</script>", html).group(1)
                          .replace("<\\/", "</"))

    small = bundle(site, tmp_path / "a.html")
    assert not small["omitted"] and "data/retrieval.json" in carried(tmp_path / "a.html")
    big = bundle(site, tmp_path / "b.html", content_limit=10)
    data = carried(tmp_path / "b.html")
    assert "data/retrieval.json" not in data and "retrieval" not in data["data/index.json"]
    assert big["omitted"] and "content index" in big["omitted"][0]


U_TEX = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}[Uniform bound]\label{thm:bound}
There is a constant $C$, independent of $n$, such that $T_n \le C n^2$ for every $n$.
\end{theorem}
\end{document}
"""


@needs_lean
@needs_tex
def test_two_papers_check_each_reference_against_its_paper(toy, monkeypatch, capsys):
    # The toy with a second paper U, which holds the uniform bound as its Theorem 1: the
    # bound's docstring (Theorem 2.4) is checked against U, the other claims' against T, and a
    # reference that nothing attributes to one paper is left unchecked (#229).
    (toy / "paper-u").mkdir()
    (toy / "paper-u" / "u.tex").write_text(U_TEX)
    with open(toy / "machinechecked.toml", "a") as f:
        f.write('\n[[paper]]\nid = "U"\ntitle = "A second paper"\nsource = { path = "paper-u" }\n'
                'root = "u.tex"\n')
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"] = [c for c in inv["claims"] if c.get("parent") != "T:thm:bound"]
    for c in inv["claims"]:
        if c["id"] == "T:thm:bound":
            c.update(id="U:thm:bound", paper="U", location="u.tex", number="Theorem 1")
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    # A lemma that no claim of either paper names, beside the shared definitions.
    edit(toy / "lean" / "Toy" / "Defs.lean", "end Toy",
         "/-- Lemma 7.7: a doubled number is even. -/\n"
         "theorem double_even (n : Nat) : IsEven (2 * n) := ⟨n, rfl⟩\n\nend Toy")
    res, cfg, lines = run(toy)
    num = res["content"]["numbering"]
    by = {o["source"]["declaration"]: o for o in num["references"]
          if o["source"]["where"] == "docstring"}
    bound = by["Toy.PaperSpec.thm_bound"]
    assert (bound["attributed"], bound["status"]) == ("U", "absent")
    assert "of paper U" in bound["message"]
    assert (by["Toy.PaperSpec.thm_even_add"]["attributed"],
            by["Toy.PaperSpec.thm_even_add"]["status"]) == ("T", "exact")
    loose = by["Toy.double_even"]
    assert loose["status"] == "unchecked" and "attributed" not in loose
    assert "several papers" in loose["detail"]
    assert set(num["papers"]) == {"T", "U"} and num["papers"]["U"]["absent"] == 1
    assert any("not checked" in l for l in lines)

    # `check --json` gives each paper's warnings and references, and all of them together.
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check", "--json"])
    except SystemExit:
        pass
    doc = json.loads(capsys.readouterr().out)
    (w,) = [w for w in doc["warnings"] if w["id"] == bound["id"]]
    assert w["paper"] == "U"
    assert [x["id"] for x in doc["papers"]["U"]["warnings"]] == [bound["id"]]
    assert bound["id"] not in [x["id"] for x in doc["papers"]["T"]["warnings"]]
    assert {o["attributed"] for o in doc["papers"]["T"]["numbering"]["references"]} == {"T"}
    assert doc["numbering"]["pattern"]["unchecked"] >= 1

    # The reader's passport of each claim lists the references that concern it.
    data = cfg.out_dir / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    chunk = json.loads((data / "claims" / next(
        c["file"] for c in index["claims"] if c["id"] == "U:thm:bound")).read_text())
    assert bound["id"] in [r["id"] for r in chunk["references"]]
