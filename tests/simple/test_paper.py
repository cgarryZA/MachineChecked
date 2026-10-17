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


def test_a_published_audit_gives_its_own_status_credited_to_it(tmp_path):
    """#64: a statement the project's published audit lists (same printed number) shows the
    audit's status, credited to it, with the audit's Lean names when formalization.yaml names
    none; a linked statement the audit does not list says so; a project without an audit keeps
    the page's own wording."""
    from prooflens.paper import NOT_IN_AUDIT, apply_audits
    paper = {"id": "arxiv:2601.00001", "title": TITLE, "authors": ["A. Author"], "links": {},
             "formalisations": [{"repository": A, "commit": "a" * 40,
                                 "audits": [{"url": "https://a.example/audit/"}]},
                                {"repository": B, "commit": "b" * 40}]}
    claims = paper_claims(
        [anchor("theorem", "1", 1, 100), anchor("theorem", "2", 1, 300),
         anchor("lemma", "3", 2, 100)], TITLE,
        [(paper["formalisations"][0], fy([("theorem", "1", ["A.one"]), ("lemma", "3", ["A.three"])])),
         (paper["formalisations"][1], fy([("theorem", "1", ["B.one"])]))])
    apply_audits(claims, {A: {"author": "A. Author", "url": "https://a.example/audit/",
                              "commit": "c" * 40, "claims": [
        {"id": "X:thm:one", "number": "Theorem 1", "status": "formal: accepted",
         "class": "accepted", "lean": ["A.Accept.one"], "link": "https://a.example/audit/#one"},
        {"id": "X:thm:two", "number": "Theorem 2", "status": "formal: proved, author-reviewed",
         "class": "proved", "lean": ["A.Accept.two"], "link": "https://a.example/audit/#two"}]}})
    index = write_paper_site(tmp_path / "site", paper, claims, (612, 792), None)
    by = {c["number"]: c["by_project"] for c in index["claims"]}
    assert by["Theorem 1"][A]["status"] == "formal: accepted"
    assert by["Theorem 1"][A]["audit"]["author"] == "A. Author"
    assert by["Theorem 1"][A]["audit"]["link"] == "https://a.example/audit/#one"
    assert by["Theorem 1"][B] == {"status": NOT_CHECKED, "class": "declared"}
    # The audit's names link a statement formalization.yaml leaves out.
    assert by["Theorem 2"][A]["status"] == "formal: proved, author-reviewed"
    c2 = next(c for c in index["claims"] if c["number"] == "Theorem 2")
    chunk = json.loads((tmp_path / "site/data/claims" / c2["file"]).read_text())
    assert [(l["name"], l["source"]) for l in chunk["links"]] == [("A.Accept.two", "audit")]
    # Linked, but the published audit does not list it.
    assert by["Lemma 3"][A] == {"status": NOT_IN_AUDIT, "class": "declared"}
