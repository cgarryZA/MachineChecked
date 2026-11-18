"""#620: a statement's passage is read without its `%` comments, removed line by line before
the lines are joined. Joined first, a comment ran on over the printed text after it, so a
printed term read as commented out. The passage's pin is unchanged: it is the digest of the
source as it is, as earlier builds recorded it."""

import json
import subprocess
import sys

from conftest import needs_tex
from prooflens.util import norm_ws, sha256_text, strip_comments


def test_a_comment_ends_with_its_line():
    assert norm_ws(strip_comments("a + b\n% \\\\\n+ c")) == "a + b + c"
    assert norm_ws(strip_comments("50\\% of $x$ % a note\nis $y$")) == "50\\% of $x$ is $y$"
    assert strip_comments("no comment") == "no comment"


BODY = r"""\label{thm:sum} For all $a, b, c$,
\begin{align*}
  s &= a + b % \\
  %& \quad
  + c,
\end{align*}
where $s$ is the sum."""
PAPER = (r"""\documentclass{article}
\usepackage{amsmath,amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}""" + BODY + r"""\end{theorem}
\end{document}
""")


@needs_tex
def test_the_read_packet_shows_the_printed_terms(tmp_path):
    root = tmp_path / "proj"
    (root / "paper").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "Proj"\n\n[[lean_lib]]\nname = "Proj"\n')
    (root / "paper" / "paper.tex").write_text(PAPER, encoding="utf-8")
    cli = [sys.executable, "-m", "prooflens.cli"]
    subprocess.run(cli + ["build"], cwd=root, capture_output=True, text=True, check=True)
    run = subprocess.run(cli + ["compare", "Theorem 1", "--stage", "read", "--json"], cwd=root,
                         capture_output=True, text=True, encoding="utf-8")
    (passage,) = json.loads(run.stdout)["paper"]["passages"]
    assert "%" not in passage["text"]
    assert "+ c, \\end{align*} where $s$ is the sum." in passage["text"]
    # The pin is the digest of the source as it is, comments and all.
    check = json.loads(subprocess.run(cli + ["check", "--json"], cwd=root, capture_output=True,
                                      text=True, encoding="utf-8").stdout)
    assert passage["source"]["sha256"] == sha256_text(norm_ws(BODY))
    assert [c["id"] for c in check["claims"]] == ["P:thm:sum"]
