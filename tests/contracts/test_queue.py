"""The review queue the engine writes for the reader."""

import json

from conftest import build, needs_lean, needs_tex


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
