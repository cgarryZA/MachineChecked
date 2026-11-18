"""`review read --context` (#666): each passage with the paper around it, from the build's copy of
the paper's source: its sections, the paragraphs before and after it, its labels' printed numbers
(from the build's `.aux`), the statements it cites (with their passages) and those that cite it or
use a term it defines (with their numbers and lines), and for a proof step the statement whose
proof it belongs to. It is context only: nothing of the Lean or of anyone's reading, and the
paper's `\\lean{...}` tags removed. The paper and its site are synthetic; nothing builds Lean."""

import json
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import review_cli as rc

WHO = "human:Context-Reviewer"
AUTHORED = "AUTHORED-NOTE: the control is read as bounded."
SOURCE = r"""\documentclass{article}
\begin{document}
\section{Preliminaries}
\subsection{Controls}

Throughout, $T > 0$ is fixed.
% a comment that is not part of the text

\begin{definition}\label{def:control}\lean{Syn.Control}
A \emph{control} is a measurable function $u : [0, T] \to \mathbb{R}$, and
\begin{equation}\label{eq:norm}
  \|u\| = \sup_t |u(t)|.
\end{equation}
\end{definition}

Controls of linear growth appear in Corollary~\ref{cor:growth}.

\section{Results}

\begin{theorem}\label{thm:main}\lean{Syn.main}
Every control satisfies \eqref{eq:norm}.
\end{theorem}

\begin{proof}
By Definition~\ref{def:control},
\begin{equation}\label{eq:step}
  \|u\| \le 1.
\end{equation}
\end{proof}

\begin{corollary}\label{cor:growth}
For every control $u$ of linear growth, the bound of Theorem~\ref{thm:main} holds.
\end{corollary}
\end{document}
"""
AUX = "".join(f"\\newlabel{{{k}}}{{{{{v}}}{{1}}}}\n" for k, v in (
    ("def:control", "1.1"), ("eq:norm", "1"), ("thm:main", "2.1"), ("eq:step", "2"),
    ("cor:growth", "2.2")))


def claim(cid, kind, number, a, b, label, **more):
    lines = SOURCE.split("\n")
    body = "\n".join(lines[a - 1:b])
    return {"id": cid, "key": cid.split(":", 1)[1], "paper": "S", "kind": kind, "number": number,
            "heading": None, "location": "main.tex",
            "anchor": {"kind": "exact", "file": "main.tex", "line": a, "label": label},
            "excerpt": {"file": "main.tex", "start_line": a, "end_line": b},
            "statement_tex": body, "source_sha256": "s" * 64, "links": [], "clauses": [],
            "status": "reviewed by an author", "correspondence": {"note": AUTHORED},
            "reviews": [{"reading": AUTHORED}], **more}


CLAIMS = [
    claim("S:def:control", "definition", "Definition 1.1", 9, 14, "def:control"),
    claim("S:thm:main", "theorem", "Theorem 2.1", 20, 22, "thm:main"),
    claim("S:eq:step", "equation", "Equation (2)", 26, 28, None, parent="S:thm:main",
          step={"parent": {"id": "S:thm:main", "number": "Theorem 2.1"}},
          context_tex="\n".join(SOURCE.split("\n")[23:28])),
    claim("S:cor:growth", "corollary", "Corollary 2.2", 31, 33, "cor:growth"),
]
UNITS = {"def": {"id": "def:Syn.Control", "kind": "def", "name": "Syn.Control",
                 "lean": ["Syn.Control"], "claims": [{"id": "S:def:control"}]},
         "link": {"id": "link:thm:main", "kind": "link", "name": "Syn.main", "lean": ["Syn.main"],
                  "claims": [{"id": "S:thm:main"}]},
         "step": {"id": "step:S:eq:step", "kind": "step", "name": "Equation (2)",
                  "claims": [{"id": "S:eq:step"}]}}


@pytest.fixture
def work(tmp_path, monkeypatch):
    work = tmp_path / "proj" / ".machinechecked"
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True)
    (data / "decls").mkdir()
    for ch in CLAIMS:
        (data / "claims" / f"{ch['key']}.json").write_text(json.dumps(ch), encoding="utf-8")
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "v-ctx",
        "project": {"name": "syn"}, "papers": [{"id": "S", "title": "Synthetic"}],
        "claims": [{"id": ch["id"], "paper": "S", "number": ch["number"], "kind": ch["kind"],
                    "file": f"{ch['key']}.json"} for ch in CLAIMS]}), encoding="utf-8")
    (data / "review-queue.json").write_text(json.dumps({
        "schema": "prooflens/review-queue@1", "release": "v-ctx", "mode": "simple",
        "units": [{**u, "papers": ["S"], "state": "pending", "reason": "Short"}
                  for u in UNITS.values()]}), encoding="utf-8")
    (work / "sources" / "S").mkdir(parents=True)
    (work / "sources" / "S" / "main.tex").write_text(SOURCE, encoding="utf-8")
    (work / "build" / "S").mkdir(parents=True)
    (work / "build" / "S" / "main.aux").write_text(AUX, encoding="utf-8")
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, work.parent))
    return work


def read(capsys, uid, *args):
    cli.main(["review", "read", uid, *args, "--as", WHO])
    out = capsys.readouterr().out
    return json.loads(out) if "--json" in args else out


def around(doc) -> dict:
    (p,) = doc["paper"]["passages"]
    return p["surroundings"]


def paper_only(context) -> None:
    """The context (a passage's `surroundings`, or the text after its heading) holds nothing of
    the Lean, of the paper's `\\lean` tags or of anyone's reading."""
    text = context if isinstance(context, str) else json.dumps(context, ensure_ascii=False)
    text = text[text.find("Its context in the paper"):] if isinstance(context, str) else text
    for x in ("Syn.Control", "Syn.main", "\\lean", AUTHORED, "reviewed by an author"):
        assert x not in text, f"{x!r} is in the reading's context"


def test_a_definition_s_context(work, capsys):
    doc = read(capsys, UNITS["def"]["id"], "--context", "--json")
    s = around(doc)
    assert doc["paper"]["context"] == "requested" and s["available"]
    assert (s["file"], s["start_line"], s["end_line"]) == ("main.tex", 9, 14)
    assert [(h["level"], h["title"], h["line"]) for h in s["sections"]] == [
        ("section", "Preliminaries", 3), ("subsection", "Controls", 4)]
    # The paragraph before is found past the comment, and the comment is not part of it.
    assert s["before"] == {"start_line": 6, "end_line": 6, "text": "Throughout, $T > 0$ is fixed."}
    assert s["after"]["text"] == "Controls of linear growth appear in Corollary~\\ref{cor:growth}."
    assert s["labels"] == [{"label": "eq:norm", "number": "1", "line": 11}]
    assert s["terms"] == ["control"] and s["cites"] == []
    assert [(x["number"], x["start_line"], x["end_line"], x["why"]) for x in s["cited_by"]] == [
        ("Theorem 2.1", 20, 22, ["cites \\ref{eq:norm}", "uses the term “control”"]),
        ("Corollary 2.2", 31, 33, ["uses the term “control”"])]
    paper_only(s)
    text = read(capsys, UNITS["def"]["id"], "--context")
    assert "Its context in the paper (context, read from the build's copy" in text
    assert "in section “Preliminaries” (line 3) > subsection “Controls” (line 4)" in text
    assert "its labels: eq:norm, printed as 1" in text
    assert "Theorem 2.1 (main.tex:20-22): cites \\ref{eq:norm}; uses the term “control”" in text
    paper_only(text)


def test_a_statement_s_citations_and_a_step_s_proof(work, capsys):
    s = around(read(capsys, UNITS["link"]["id"], "--context", "--json"))
    (cited,) = s["cites"]
    assert (cited["number"], cited["label"], cited["start_line"]) == (
        "Definition 1.1", "eq:norm", 9)
    assert cited["text"].startswith("\\begin{definition}\\label{def:control}")
    assert "\\lean" not in cited["text"]
    assert [(x["number"], x["why"]) for x in s["cited_by"]] == [
        ("Corollary 2.2", ["cites \\ref{thm:main}"])]
    doc = read(capsys, UNITS["step"]["id"], "--context", "--json")
    s = around(doc)
    assert s["belongs_to"]["number"] == "Theorem 2.1" and "Every control" in \
        s["belongs_to"]["text"]
    assert s["before"]["text"] == "\\begin{proof}\nBy Definition~\\ref{def:control},"
    assert s["after"]["text"] == "\\end{proof}" and s["labels"] == []
    paper_only(s)
    assert "it belongs to the proof of Theorem 2.1 (main.tex:20-22):" in \
        read(capsys, UNITS["step"]["id"], "--context")


def test_without_the_option_the_read_step_is_as_before(work, capsys):
    doc = read(capsys, UNITS["def"]["id"], "--json")
    assert "context" not in doc["paper"]
    assert all("surroundings" not in p for p in doc["paper"]["passages"])
    assert "Its context in the paper" not in read(capsys, UNITS["def"]["id"])


def test_what_has_no_source_to_read_says_so(work, capsys):
    s = rc.Session(work, rc.parse_reviewer(WHO), evidence={"kind": "snapshot"})
    pk = s.read(UNITS["def"]["id"], as_json=True, context=True)
    assert around(pk) == {"available": False, "reason": (
        "a review snapshot holds the passages the steps show, not the rest of the paper's "
        "source: read their context in the paper")}
    (work / "sources" / "S" / "main.tex").rename(work / "sources" / "S" / "other.tex")
    assert around(read(capsys, UNITS["def"]["id"], "--context", "--json"))["reason"] == \
        "the build's copy of the paper's source has no main.tex"
    import shutil
    shutil.rmtree(work / "sources")
    assert around(read(capsys, UNITS["def"]["id"], "--context", "--json"))["reason"] == \
        "the build holds no copy of the paper's source"
    assert "Its context in the paper: not available (the build holds no copy" in \
        read(capsys, UNITS["def"]["id"], "--context")
