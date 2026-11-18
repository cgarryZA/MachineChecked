"""#567: a PDF whose statement headings are not bold, as many journals set them, is read by its
paragraphs: a statement kind and its number starting a paragraph and followed by the statement is
a heading. A reference that starts a line is not. A PDF in which no heading is recognised says
so, in a note and a warning, instead of reading as a paper with nothing to check. These tests
read synthetic lines, as `pdfclaims._lines` gives them, and need no PDF tools."""

from prooflens import cli
from prooflens.pdfclaims import paragraph_heads
from prooflens.simple import NO_HEADINGS, pdf_notes

H = 10.0          # a line's height
LEFT, RIGHT = 100.0, 500.0


def line(text, y, x0=LEFT, x1=RIGHT, page=1):
    return {"page": page, "y0": y, "y1": y + H, "x0": x0, "x1": x1, "text": text,
            "bold": False, "italic": False, "head": "", "italic_head": ""}


def heads(lines):
    return [(lines[i]["text"][:12], m.group(1), m.group(2)) for i, m in paragraph_heads(lines)]


def test_a_kind_and_number_starting_a_paragraph_is_a_heading():
    lines = [line("Some prose that fills the whole width of the column of text here.", 100),
             line("It ends here.", 112, x1=200),
             # Space above it, after a line that ended short.
             line("Theorem 2.1 Suppose (H.1) holds. Then for all sufficiently large N the", 130),
             line("bound holds.", 142, x1=180),
             line("Lemma A.3. Let a, b be even. Then a + b is even.", 160, x1=400),
             line("Corollary 4.5 (Name)", 178, x1=250)]
    assert heads(lines) == [("Theorem 2.1 ", "Theorem", "2.1"), ("Lemma A.3. L", "Lemma", "A.3"),
                            ("Corollary 4.", "Corollary", "4.5")]


def test_a_reference_is_not_a_heading():
    lines = [line("A paragraph whose second line starts with a reference to a result, as", 100),
             # Inside the paragraph: the line above is full and there is no space above.
             line("Lemma 2.2 Let us use it now, which the line above leads into, and", 112),
             line("so the paragraph goes on to its end here.", 124, x1=300),
             # Paragraph starts, but the text goes on as a sentence about the result.
             line("Theorem 2.1 gives the bound used below.", 142, x0=LEFT + 15, x1=330),
             line("Theorem 2.1, which we use below, is the main result.", 160, x0=LEFT + 15,
                  x1=380),
             line("Lemma 1.2. is used below, but this line is not a heading.", 178, x1=380)]
    assert heads(lines) == []


def test_a_head_whose_kind_and_number_are_separate_runs_is_read_whole():
    # A small-caps kind and its upright number: two runs on one line whose tops differ.
    lines = [line("The text before it ends here.", 100, x1=260),
             line("Lemma", 121, x1=150),
             line("1.2 Let a and b be even. Then a plus b is even.", 118, x0=155, x1=450)]
    assert heads(lines) == [("Lemma", "Lemma", "1.2")]


def test_no_heading_is_a_note_and_a_warning(capsys):
    warnings = []
    assert pdf_notes([], warnings) == [NO_HEADINGS]
    assert warnings == [{"kind": "pdf-no-statements", "message": NO_HEADINGS}]
    assert NO_HEADINGS.startswith("no numbered statement headings were recognised in this PDF")
    # Printed once, as a warning, by `check`, `view` and `build`.
    cli._print_simple({"notes": [NO_HEADINGS, "another note"], "paper_warnings": warnings,
                       "claims": []})
    out = capsys.readouterr().out.splitlines()
    assert out == ["note: another note", f"warning: {NO_HEADINGS}"]
    # Statements found: how they were found, and no warning.
    warnings = []
    assert "bold headings" in pdf_notes([{"found_by": "styled"}], warnings)[0]
    assert "starting a paragraph" in pdf_notes([{"found_by": "paragraph"}], warnings)[0]
    assert warnings == []
