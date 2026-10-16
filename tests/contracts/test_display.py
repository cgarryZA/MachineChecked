"""A display overlay changes what the site shows, never what is assessed."""

import json

from conftest import build, edit, needs_lean, needs_tex


@needs_lean
@needs_tex
def test_display_overlay(toy):
    before, body0, cfg = build(toy)
    (toy / "display.json").write_text(json.dumps({
        "claims": {"T:thm:triangle": {"title_tex": r"$T_n = n(n+1)/2$", "number": "Theorem 2.2*",
                                      "number_note": "a test correction"},
                   "T:rem:pred": {"title_tex": ""}},
        "clauses": {"corrected: positive n": {"title_tex": r"corrected: positive $n$"}}}))
    edit(toy / "machinechecked.toml", 'statement_authors = ["statement-author"]',
         'statement_authors = ["statement-author"]\ndisplay = "display.json"')
    after, body1, cfg = build(toy)
    assert body1["assessment"] == body0["assessment"]
    c = {x["id"]: x for x in after["claims"]}
    assert c["T:thm:triangle"]["number"] == "Theorem 2.2*"
    assert c["T:thm:triangle"]["title"] == r"$T_n = n(n+1)/2$"
    assert c["T:rem:pred"]["title"] == ""
    assert [x["status"] for x in after["claims"]] == [x["status"] for x in before["claims"]]
    chunk = json.loads((cfg.out_dir / "site/data/claims" / c["T:prop:pred"]["file"]).read_text())
    labels = {cl["name"]: cl["label"] for cl in chunk["clauses"]}
    assert labels["corrected: positive n"] == r"corrected: positive $n$"
    assert labels["as printed"] == "as printed"
    tri = json.loads((cfg.out_dir / "site/data/claims" / c["T:thm:triangle"]["file"]).read_text())
    assert tri["number_note"] == "a test correction"
