"""The review queue the engine writes for the reader."""

import json

from conftest import build, edit, needs_lean, needs_tex


@needs_lean
@needs_tex
def test_queue_of_a_full_assessment(toy):
    _, _, cfg = build(toy)
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    assert q["mode"] == "assurance" and q["authors"] == ["statement-author"]
    units = {u["id"]: u for u in q["units"]}
    specs = [u for u in units.values() if u["kind"] == "spec"]
    defs = [u for u in units.values() if u["kind"] == "def"]
    assert specs and defs
    for u in specs + defs:
        # Every unit names what it would be reviewed at, and why it sits where it does.
        assert len(u["legacy_hash"]) == 32 and u["fingerprint"].startswith("pl-fp-v1:")
        assert u["reason"] and u["papers"] and u["claims"]
    # A definition is one unit, however many claims use it.
    assert len({u["name"] for u in defs}) == len(defs)
    # Units already independently reviewed come last.
    states = [u["state"] == "reviewed" for u in q["units"]]
    assert states == sorted(states)


@needs_lean
@needs_tex
def test_a_unit_says_what_it_reveals_and_revealed_units_come_first(toy):
    """A statement's step 2 shows the Lean of the definitions it uses, so those come first; the
    markers closing one review section reveal each other's author review (#53)."""
    _, _, cfg = build(toy)
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    u = next(u for u in q["units"] if u["id"] == "spec:Toy.PaperSpec.thm_bound")
    h, src = u["legacy_hash"], " ".join(f"source={c}@{d}" for c, d in u["source_sha256"].items())
    edit(toy / "reviews/T.md", "<!-- spec-review: Toy.PaperSpec.thm_triangle",
         f"<!-- spec-review: Toy.PaperSpec.thm_bound {h} by=statement-author {src} -->\n"
         "<!-- spec-review: Toy.PaperSpec.thm_triangle")
    _, _, cfg = build(toy, reuse_lean=True)
    q = json.loads((cfg.out_dir / "site/data/review-queue.json").read_text())
    units = {u["id"]: u for u in q["units"]}
    tri = units["spec:Toy.PaperSpec.thm_triangle"]
    assert "def:Toy.triangle" in tri["reveals"]["lean"]
    open_order = [u["id"] for u in q["units"] if u["state"] != "reviewed"]
    for u in q["units"]:
        for v in u["reveals"]["lean"]:
            if u["id"] in open_order and v in open_order and \
                    u["id"] not in units[v]["reveals"]["lean"] + units[v]["reveals"]["author"]:
                assert open_order.index(v) < open_order.index(u["id"]), (v, u["id"])
    # The two markers closing one section share its text and reveal each other.
    bound = units["spec:Toy.PaperSpec.thm_bound"]
    assert bound["author_review"][-1]["text"] == tri["author_review"][-1]["text"] != ""
    assert "spec:Toy.PaperSpec.thm_triangle" in bound["reveals"]["author"]
