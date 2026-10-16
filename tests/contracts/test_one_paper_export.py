"""Exporting one paper of a two-paper configuration (`export --paper`): exactly that paper's
closure, and nothing of the other paper, which the scan catches when it is planted."""

import json

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import config as cfgmod
from prooflens import manifest as mf
from prooflens import evidence as ev
from prooflens.export import ExportError, claim_names, export

U_LINE = "This sentence belongs only to the second synthetic paper of the configuration."
U_REVIEW = "A review sentence that belongs only to the second paper's bound statement."
U_TEX = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
""" + U_LINE + r"""

\begin{theorem}[Uniform bound]\label{thm:bound}
There is a constant $C$, independent of $n$, such that $T_n \le C n^2$ for every $n$.
\end{theorem}
\end{document}
"""


@pytest.fixture
def two(toy):
    """The toy with a second, unpublished paper U holding the uniform bound (Theorem 2.5)."""
    (toy / "paper-u").mkdir()
    (toy / "paper-u" / "u.tex").write_text(U_TEX)
    with open(toy / "machinechecked.toml", "a") as f:
        f.write('\n[[paper]]\nid = "U"\ntitle = "A second paper"\nsource = { path = "paper-u" }\n'
                'root = "u.tex"\n'
                'publish = { pdf = false, source_text = false, lean = false, reviews = false }\n')
    inv = json.loads((toy / "claims.json").read_text())
    for c in inv["claims"]:
        if c["id"] == "T:thm:bound":
            c.update(id="U:thm:bound", paper="U", location="u.tex")
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    with open(toy / "reviews" / "T.md", "a") as f:
        f.write(f"\n## The bound: `Toy.PaperSpec.thm_bound`\n\n{U_REVIEW}\n\nVerdict: faithful.\n\n"
                "<!-- spec-review: Toy.PaperSpec.thm_bound " + "0" * 32 + " by=a.referee -->\n")
    build(toy)
    return toy


def everything(out):
    return "\n".join(p.read_text(errors="replace") for p in out.rglob("*") if p.is_file()
                     and p.suffix in (".json", ".html", ".js"))


@needs_lean
@needs_tex
def test_one_paper_is_exactly_its_closure(two, tmp_path):
    cfg = cfgmod.load(two / "machinechecked.toml")
    rel = ev.releases(cfg.out_dir)[-1]
    rec = ev.load(cfg.out_dir, json.loads(rel.read_text())["evidence"])
    _, chunks, store = mf.build(rec, "r")
    mine = set().union(*(claim_names(c) for c in chunks.values() if c["paper"] == "T"))
    only_u = set().union(*(claim_names(c) for c in chunks.values() if c["paper"] == "U")) - mine
    assert only_u, "the fixture gives U declarations of its own"
    out = tmp_path / "T"
    export(cfg, out, paper="T")
    index = json.loads((out / "data" / "index.json").read_text())
    assert [p["id"] for p in index["papers"]] == ["T"]
    assert {c["paper"] for c in index["claims"]} == {"T"}
    names = {json.loads(p.read_text())["name"] for p in (out / "data" / "decls").iterdir()}
    assert names == mine & {d["name"] for d in store.values()}
    text = everything(out)
    assert not any(n in text for n in only_u) and "U:thm:bound" not in text
    assert U_LINE not in text and U_REVIEW not in text


@needs_lean
@needs_tex
@pytest.mark.parametrize("planted, caught", [
    (U_LINE, "a line of u.tex"),
    (U_REVIEW, "a review line of paper U"),
    ("Toy.Acceptance.thm_bound", "a declaration only paper U uses"),
    ("U:thm:bound", "a claim id of paper U"),
])
def test_the_other_papers_material_is_caught(two, tmp_path, planted, caught):
    edit(two / "claims.json", '"scope_note": ""', f'"scope_note": {json.dumps("See " + planted)}')
    build(two, reuse_lean=True)
    cfg = cfgmod.load(two / "machinechecked.toml")
    with pytest.raises(ExportError, match=caught):
        export(cfg, tmp_path / "T", paper="T")
    assert not (tmp_path / "T").exists()
