"""#672: a reviewer sees two digests of a claim's passage: the passage's pin in this build (the
read packet's `source.sha256`) and the digest the report pins and its marker records (the unit's
`source_sha256`). The packets label each with what it covers (`paper.digests`), and `review
author` says so when they differ: the recorded one then also covers the definitions of the
notation macros the passage uses. Both are of this build's text."""

from types import SimpleNamespace

from prooflens import review_cli as rc
from prooflens.compare import DIGEST_COVERS, passage_digests

PIN, NOTATION = "a" * 64, "b" * 64
CHUNKS = [{"id": "P:rmk-x", "source_sha256": PIN}, {"id": "P:thm", "source_sha256": PIN}]
UNIT = {"id": "spec:S.x", "kind": "spec", "claims": [{"id": "P:rmk-x"}, {"id": "P:thm"}],
        "source_sha256": {"P:rmk-x": NOTATION, "P:thm": PIN}}


def test_each_digest_is_labelled_with_what_it_covers():
    assert passage_digests(UNIT, CHUNKS) == [
        {"claim": "P:rmk-x", "passage": PIN, "recorded": NOTATION, "same": False,
         "covers": DIGEST_COVERS["notation"]},
        {"claim": "P:thm", "passage": PIN, "recorded": PIN, "same": True,
         "covers": DIGEST_COVERS["passage"]}]
    # A unit with no recorded digests (a passage with no pin) lists none.
    assert passage_digests({**UNIT, "source_sha256": {}}, CHUNKS) == []


def test_review_author_says_when_they_differ():
    session = SimpleNamespace(site=SimpleNamespace(chunk=lambda cid: next(
        c for c in CHUNKS if c["id"] == cid)))
    (line,) = rc.Session._digest_lines(session, UNIT)
    assert line.startswith(f"Digests of P:rmk-x: the passage read is pinned at {PIN} in this "
                           f"build; the report records {NOTATION}, the passage with the "
                           "definitions of the notation macros it uses")
    assert line.endswith("Both are of this build's text.")
    same = {**UNIT, "source_sha256": {"P:rmk-x": PIN, "P:thm": PIN}}
    assert rc.Session._digest_lines(session, same) == []
