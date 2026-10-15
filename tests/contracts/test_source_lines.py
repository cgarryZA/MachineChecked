"""Which source lines place an approximately anchored claim."""

from prooflens.tex import source_lines

TEXT = [
    "Some text before the display",          # 1
    r"\begin{equation}\label{eq:x}",          # 2
    r"\begin{aligned}",                       # 3
    "x &= 1",                                 # 4
    r"\end{aligned}",                         # 5
    r"\end{equation}",                        # 6
    r"\subsection{A section}",                # 7
    "",                                       # 8
    r"\label{sec:a}",                         # 9
    "First line of the section.",             # 10
    r"\label{orphan}",                        # 11
]


def test_display_is_placed_by_its_body():
    assert source_lines(TEXT, 2) == [[3, 4, 5, 6], [2]]


def test_labelled_heading_is_placed_by_the_heading():
    assert source_lines(TEXT, 9) == [[7], [9]]


def test_other_lines_are_placed_by_themselves():
    assert source_lines(TEXT, 10) == [[10]]
    assert source_lines(TEXT, 11) == [[11]]
