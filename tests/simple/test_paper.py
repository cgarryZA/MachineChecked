"""A paper page's data (`prooflens.paper`): the standard manifest, each project's links and
statuses kept apart, and no statement text."""

import json

from prooflens.paper import NOT_CHECKED, NOT_LINKED, paper_claims, write_paper_site

A, B = "alpha/project-a", "beta/project-b"
TITLE = "A synthetic paper"


def anchor(env, number, page, y0, text="the statement's words"):
    return {"env": env, "number": number, "title": None, "begin": [page, 0, y0],
            "end": [page, 0, y0 + 40], "head": None, "statement": text, "kind": "pdf"}


def fy(rows):
    return {"sources": [{"title": TITLE, "relationship": "formalizes"}],
            "alignment": {"statements": [{"source": f"{k} {n}", "lean": names}
                                         for k, n, names in rows]}}


def build(tmp_path):
    paper = {"id": "arxiv:2601.00001", "title": TITLE, "authors": ["A. Author"], "links": {},
             "formalisations": [{"repository": A, "commit": "a" * 40},
                                {"repository": B, "commit": "b" * 40}]}
    claims = paper_claims(
        [anchor("theorem", "1", 1, 100), anchor("theorem", "2", 1, 300),
         anchor("lemma", "3", 2, 100)], TITLE,
        [(paper["formalisations"][0], fy([("theorem", "1", ["A.one", "not a name!"])])),
         (paper["formalisations"][1], fy([("theorem", "1", ["B.one"]),
                                          ("theorem", "2", ["B.two"])]))])
    index = write_paper_site(tmp_path / "site", paper, claims, (612, 792),
                             "https://example.org/paper.pdf")
    return index, tmp_path / "site" / "data"


def test_each_project_has_its_own_status(tmp_path):
    index, _ = build(tmp_path)
    assert index["mode"] == "paper" and index["projects"] == [A, B]
    by = {c["number"]: c["by_project"] for c in index["claims"]}
    assert by["Theorem 1"] == {A: {"status": NOT_CHECKED, "class": "declared"},
                               B: {"status": NOT_CHECKED, "class": "declared"}}
    assert by["Theorem 2"][A]["status"] == NOT_LINKED and by["Theorem 2"][B]["status"] == NOT_CHECKED
    assert by["Lemma 3"] == {A: {"status": NOT_LINKED, "class": "unspecified"},
                             B: {"status": NOT_LINKED, "class": "unspecified"}}
    # The default status is the first project's, never one combined from both.
    assert {c["number"]: c["status"] for c in index["claims"]}["Theorem 2"] == NOT_LINKED


def test_links_name_their_project_and_bad_names_are_dropped(tmp_path):
    index, data = build(tmp_path)
    c = next(c for c in index["claims"] if c["number"] == "Theorem 1")
    chunk = json.loads((data / "claims" / c["file"]).read_text())
    assert [(l["name"], l["repository"]) for l in chunk["links"]] == [("A.one", A), ("B.one", B)]
    assert all(l["status"] == NOT_CHECKED for l in chunk["links"])


def test_the_standard_reader_files_and_no_statement_text(tmp_path):
    index, data = build(tmp_path)
    assert (data / "index.json").is_file() and (data / "search.json").is_file()
    assert index["papers"][0]["pdf_url"] == "https://example.org/paper.pdf"
    assert index["claims"][0]["anchor"]["kind"] == "approximate"
    for f in data.rglob("*.json"):
        assert "the statement's words" not in f.read_text(), f.name
