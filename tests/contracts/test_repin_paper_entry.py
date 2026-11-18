"""#565: `inventory repin` moves `papers.<id>.commit` to the new revision, and with it every other
field of the paper's entry whose form names the old revision: a link to its tree, a file or
arXiv page of it, or the revision itself. The plan shows each beside the commit. A field that
names the old revision in other text is listed for the author to inspect and left as it is, and
a word that only resembles the revision is neither changed nor listed. A synthetic manuscript."""

import json

import pytest

from prooflens.repin import retarget_entry
from test_repin import A, B, E, commit, files, git, pinned, run

UNRELATED = "Draft aaaa1119, see xaaaa111 and paper/main.tex"


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "manuscript"
    repo.mkdir()
    git(repo, "init", "-q")
    first = commit(repo, A, B, E)
    inv = {"papers": {"T": {
        "commit": first[:7], "source": f"https://example.org/paper/tree/{first[:7]}",
        "path": "paper/main.tex", "title": UNRELATED,
        "note": f"Read at {first[:7]} against the journal proofs."}},
        "claims": [pinned(repo, "a", A), pinned(repo, "b", B)]}
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    (proj / "machinechecked.toml").write_text(
        '[project]\nname = "synthetic"\nmodules = ["S"]\nscope_roots = ["S"]\n'
        'spec_prefix = "S.Spec"\naccept_prefix = "S.Accept"\ninventory = "claims.json"\n\n'
        f'[[paper]]\nid = "T"\nroot = "paper.tex"\n'
        f'source = {{ git = "../manuscript", rev = "{first}" }}\n', encoding="utf-8")
    return repo, proj, first


def test_the_source_link_moves_with_the_commit(project, capsys):
    repo, proj, first = project
    second = commit(repo, "Added.\n", A, B)
    code, out, _ = run(proj, "--to", second, capsys=capsys)
    assert code == 0
    entry = json.loads(out)["paper_entry"]
    assert entry["commit"] == {"from": first[:7], "to": second[:7]}
    assert entry["fields"] == [{"field": "source",
                                "from": f"https://example.org/paper/tree/{first[:7]}",
                                "to": f"https://example.org/paper/tree/{second[:7]}"}]
    assert [i["field"] for i in entry["inspect"]] == ["note"]

    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is True
    paper = json.loads((proj / "claims.json").read_text(encoding="utf-8"))["papers"]["T"]
    assert paper == {"commit": second[:7],
                     "source": f"https://example.org/paper/tree/{second[:7]}",
                     "path": "paper/main.tex", "title": UNRELATED,
                     "note": f"Read at {first[:7]} against the journal proofs."}

    # Again, against the updated inventory: nothing to move, nothing to inspect, nothing written.
    after = files(proj)
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    plan = json.loads(out)
    assert code == 0 and plan["written"] is False and files(proj) == after
    assert plan["paper_entry"] == {"commit": {"from": second[:7], "to": second[:7]},
                                   "fields": [], "inspect": []}


def test_the_forms_of_a_revision_that_are_read():
    old, new = "c" * 7 + "0" * 33, "d" * 7 + "0" * 33
    entry = {"rev": old[:7], "raw": f"https://example.org/o/r/raw/{old[:12]}/main.tex?ref={old}",
             "nested": {"tree": [f"https://example.org/o/r/tree/{old[:7]}/paper"]},
             "word": f"x{old[:7]}y", "longer": old[:7] + "9", "count": 3}
    changes, inspect = retarget_entry(entry, old, new)
    assert {c["field"]: c["to"] for c in changes} == {
        "rev": new[:7], "raw": f"https://example.org/o/r/raw/{new[:12]}/main.tex?ref={new}",
        "nested.tree[0]": f"https://example.org/o/r/tree/{new[:7]}/paper"}
    assert inspect == [] and entry["word"] == f"x{old[:7]}y" and entry["count"] == 3
    # A versioned arXiv identifier: its abstract page, its PDF and the identifier itself.
    entry = {"abs": "https://arxiv.org/abs/2601.01234v1",
             "pdf": "https://arxiv.org/pdf/2601.01234v1.pdf", "id": "arxiv:2601.01234v1",
             "other": "https://arxiv.org/abs/2601.01234v10"}
    changes, _ = retarget_entry(entry, "2601.01234v1", "2601.01234v2")
    assert {c["field"]: c["to"] for c in changes} == {
        "abs": "https://arxiv.org/abs/2601.01234v2",
        "pdf": "https://arxiv.org/pdf/2601.01234v2.pdf", "id": "arxiv:2601.01234v2"}
