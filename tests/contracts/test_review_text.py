"""The text of a review belongs to every marker that closes it (#52): one section reviewing
several declarations ends with one marker each, and each unit shows the section's text."""

from prooflens.reviews import parse_file

FILE = """# Reviews

## Theorem 1: `Foo.spec_a`, `Foo.spec_b`

Manuscript: the bound. Correspondence: both clauses. Verdict: faithful.

<!-- spec-review: Foo.spec_a 0123456789abcdef0123456789abcdef by=author -->
<!-- spec-review: Foo.spec_b fedcba9876543210fedcba9876543210 by=author -->

## A definition with a marker and no text

<!-- def-review: Foo.d 00000000000000000000000000000000 by=author -->

## Theorem 2: `Foo.spec_c`

Its own review.

<!-- spec-review: Foo.spec_c 11111111111111111111111111111111 by=author -->
"""


def test_consecutive_markers_share_their_section(tmp_path):
    f = tmp_path / "R.md"
    f.write_text(FILE)
    text = {r.name: r.text for r in parse_file(f, [], tmp_path)}
    joint = "Manuscript: the bound. Correspondence: both clauses. Verdict: faithful."
    assert text["Foo.spec_a"] == joint and text["Foo.spec_b"] == joint
    # A marker with a heading of its own but no text has none, and does not borrow another's.
    assert text["Foo.d"] == ""
    assert text["Foo.spec_c"] == "Its own review."
