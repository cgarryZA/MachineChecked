"""A review snapshot without the text of a paper whose source may not be redistributed (#748).

With `publish.source_text = false`, `review pack` replaces each text of the paper's source by
where it is in the source and its digest, and refuses a snapshot that still holds a line of the
source, as the public export is scanned. A reviewer's step reads each passage again from the
paper's source (downloaded from arXiv into the reviewer's directory, the project's folder, or the
copy given with --paper-source), checked against its digest, and shows exactly what a snapshot
with the text shows; a source that cannot be obtained, or that differs, is refused before
anything is shown.

The fast tests use the synthetic site of `test_compare.write_site`, given a synthetic LaTeX source
that holds its passages (one file with Windows line endings); arXiv is a test double. The last
test builds the toy example with its text private and reviews a clone of it without Lean."""

import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import promote as pr
from prooflens import review_cli as rc
from prooflens import review_snapshot as rs
from prooflens import snapshot_text as st
from prooflens.export import scan as export_scan
from prooflens.util import norm_ws
from test_compare import write_site
from test_kept_snapshot import CONFIG, git, no_build
from test_review_snapshot import UNIT, WHO, files_of, lean_free

ARXIV = "2601.00001v1"
BIG = "Syn.big_bound_" + "x" * 20


def theorem(i: int) -> str:
    return (f"\\begin{{theorem}}\\label{{thm:t{i}}}\\lean{{{BIG}}}\n"
            f"  Statement {i}: for every natural number $n$, the jet of order {i} is bounded,\n"
            f"     uniformly    in $n$, by the constant that the lemma before it provides.\n"
            "\\end{theorem}\n")


def body(i: int) -> str:
    """What the build keeps of theorem `i`: its environment's body, white space normalised."""
    t = theorem(i)
    return norm_ws(t[t.index("}", t.index("lean")) + 1:t.index("\\end")])


CONTEXT = ["\\begin{proof}",
           "Fix the order of the jet and the natural number $n$ that the statement gives.",
           "  Then the step below bounds the jet by the constant chosen at the start.",
           "\\end{proof}"]
MACRO = "\\newcommand{\\Jet}{\\mathcal{J}}"


@pytest.fixture
def paper(tmp_path):
    """The synthetic site with a LaTeX source: each claim's statement from `main.tex`, claim
    t3, read as a step, with its context in a proof from `proof.tex` (written with Windows line
    endings), claim t4's
    pin with a second passage and a notation macro; claim t2 holds no text. Returns the site data
    and the source's folder."""
    data = write_site(tmp_path)
    src = tmp_path / "work" / "sources" / "S"
    src.mkdir(parents=True)
    main = "\\documentclass{article}\n" + MACRO + "\n\\begin{document}\n"
    lines = {}
    for i in range(8):
        lines[i] = main.count("\n") + 1
        main += theorem(i) + "\n"
    main += "\\input{proof}\n\\end{document}\n"
    (src / "main.tex").write_text(main)
    (src / "proof.tex").write_bytes("\r\n".join(CONTEXT + [""]).encode())
    (src / "refs.bib").write_text("@article{a, title = {A reference title that is long enough}}\n")
    for i in range(8):
        f = data / "claims" / f"S_thm_t{i}.json"
        ch = json.loads(f.read_text())
        if i != 2:
            ch["statement_tex"] = body(i)
            ch["anchor"] = {**ch["anchor"], "kind": "exact", "file": "main.tex",
                            "line": lines[i], "statement": body(i)}
        ch["excerpt"] = {"scheme": "tex-excerpt-v1", "text": body(i), "fingerprint": "f"}
        if i == 3:
            # Read as a step of a proof, with its context in the proof.
            ch["step"] = {"unit": "proof-equation",
                          "parent": {"id": "S:thm:t2", "number": "Theorem 2"}}
            ch["context_tex"] = "\n".join(CONTEXT)
        if i == 4:
            ch["source_parts"] = [
                {"file": "main.tex", "start_line": lines[4], "end_line": lines[4] + 3,
                 "text": theorem(4).rstrip("\n")},
                {"file": "main.tex", "start_line": 2, "end_line": 2, "macro": "\\Jet",
                 "text": MACRO}]
        f.write_text(json.dumps(ch))
    index = json.loads((data / "index.json").read_text())
    index["papers"][0]["mode"] = "latex"
    (data / "index.json").write_text(json.dumps(index))
    return data, src


def private(src: Path, source: dict | None = None) -> dict:
    return {"S": {"dir": src, "source": source or {"kind": "arxiv", "arxiv": ARXIV}}}


def eprint(src: Path) -> bytes:
    """The paper's source as arXiv serves it: a gzipped tar."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        for p in sorted(src.rglob("*")):
            t.add(p, arcname=p.relative_to(src).as_posix())
    return buf.getvalue()


def source_lines(src: Path) -> list[Path]:
    return sorted(p for p in src.rglob("*") if p.suffix in st.TEXT_SUFFIXES)


def test_a_snapshot_without_the_text_holds_no_line_of_the_source(paper, tmp_path):
    data, src = paper
    m = rs.pack(data, tmp_path / "snap", without=private(src))
    snap = tmp_path / "snap"
    # The export's scan finds no line of the source in it.
    assert export_scan(snap, source_lines(src), set()) == []
    assert m["schema"] == rs.SCHEMA_WITHOUT_TEXT
    files = {"main.tex": hashlib.sha256((src / "main.tex").read_bytes()).hexdigest(),
             "proof.tex": hashlib.sha256((src / "proof.tex").read_bytes()).hexdigest()}
    assert m["paper_text"] == {"S": {"included": False,
                                     "source": {"kind": "arxiv", "arxiv": ARXIV},
                                     "files": files}}
    ch = json.loads((snap / "data" / "claims" / "S_thm_t4.json").read_text())
    assert ch["statement_tex"] is None and ch["anchor"]["statement"] is None
    assert [p["text"] for p in ch["source_parts"]] == [None, None] and ch["excerpt"] is None
    assert ch["source_parts"][1]["macro"] == "\\Jet"
    text = "\n".join((snap / f).read_text() for f in files_of(snap))
    for x in ["Statement 4", "Fix the order", MACRO.replace("\\", "\\\\")]:
        assert x not in text, x
    # Each passage is a byte range of a file of the source, with the digest of its text.
    refs = json.loads((snap / st.REFS).read_text())
    assert refs["schema"] == st.REFS_SCHEMA
    by = {(r["at"][0] if r["at"][0] != "source_parts" else f"part{r['at'][1]}"): r
          for r in refs["claims"]["claims/S_thm_t4.json"]}
    raw = (src / "main.tex").read_bytes()
    a, b = by["statement_tex"]["bytes"]
    assert by["statement_tex"]["form"] == "whitespace" and norm_ws(raw[a:b].decode()) == body(4)
    a, b = by["part0"]["bytes"]
    assert by["part0"]["form"] == "text" and raw[a:b].decode() == theorem(4).rstrip("\n")
    (ctx,) = [r for r in refs["claims"]["claims/S_thm_t3.json"] if r["at"] == ["context_tex"]]
    a, b = ctx["bytes"]
    assert ctx["file"] == "proof.tex" and (src / "proof.tex").read_bytes()[a:b] == \
        "\r\n".join(CONTEXT).encode()
    for r in [x for rs_ in refs["claims"].values() for x in rs_]:
        f = (src / r["file"]).read_bytes()[r["bytes"][0]:r["bytes"][1]]
        assert hashlib.sha256(st.formed(f, r["form"]).encode()).hexdigest() == r["sha256"]
    said = rs.summary_text(m)
    assert f"paper S: its text left out; a reviewer reads each passage from arXiv {ARXIV}" in said
    assert "It holds no text of the paper's source" in said
    assert "left out: the typeset excerpts of 8 claim(s), which only the reader shows" in said
    # The same material packed again is current.
    assert rs.pack(data, snap, without=private(src))["unchanged"]


def test_pack_refuses_a_snapshot_that_would_still_hold_the_source(paper, tmp_path):
    data, src = paper
    # A declaration's docstring that quotes a line of the source.
    (decl,) = [p for p in (data / "decls").iterdir()
               if json.loads(p.read_text())["name"] == "Syn.Jet"]
    rec = json.loads(decl.read_text())
    rec["doc"] = "As the paper says: uniformly    in $n$, by the constant that the lemma before " \
                 "it provides."
    decl.write_text(json.dumps(rec))
    with pytest.raises(rs.SnapshotError) as e:
        rs.pack(data, tmp_path / "snap", without=private(src))
    assert f"data/decls/{decl.name}: contains a line of main.tex (in $.doc)" in str(e.value)
    assert "Nothing was written" in str(e.value) and not (tmp_path / "snap").exists()
    # With the text kept, as asked, the same snapshot is written.
    m = rs.pack(data, tmp_path / "snap", kept_text={"S": "asked"})
    assert m["schema"] == rs.SCHEMA and m["paper_text"] == {"S": {"included": True,
                                                                   "because": "asked"}}
    assert "paper S: its text kept, as asked (--with-paper-text)" in rs.summary_text(m)
    # A text that is no passage of the source cannot be read again from it.
    f = data / "claims" / "S_thm_t5.json"
    ch = json.loads(f.read_text())
    ch["statement_tex"] = "A statement this source does not hold."
    f.write_text(json.dumps(ch))
    with pytest.raises(rs.SnapshotError, match="statement_tex of S:thm:t5 is no passage"):
        rs.pack(data, tmp_path / "other", without=private(src))
    with pytest.raises(rs.SnapshotError, match="copy of paper S's source .* is missing"):
        rs.pack(data, tmp_path / "other", without=private(tmp_path / "nowhere"))


def review(capsys, work: Path, snap: Path, *args, code=0, given=()):
    """A review step against `snap` in the working directory `work`: its standard output and
    error."""
    argv = ["review", *args, *WHO, "--snapshot", str(snap), "--review-dir", str(work),
            *[x for g in given for x in ("--paper-source", g)]]
    if code:
        with pytest.raises(SystemExit) as e:
            cli.main(argv)
        assert e.value.code == code
    else:
        cli.main(argv)
    got = capsys.readouterr()
    return got.out, got.err


def steps(capsys, tmp_path, work: Path, snap: Path, given=()) -> list[str]:
    """Every step of a review of UNIT, with what each shows."""
    texts = tmp_path / "texts"
    texts.mkdir(exist_ok=True)
    for name, text in {"r.md": "Every statement bounds the jet uniformly in n.",
                       "c.md": "The same bound, for every n.", "n.md": "none"}.items():
        (texts / name).write_text(text)
    shown = [review(capsys, work, snap, "read", UNIT, "--json", given=given)[0],
             review(capsys, work, snap, "read", UNIT)[0]]
    review(capsys, work, snap, "lock", UNIT, str(texts / "r.md"))
    shown += [review(capsys, work, snap, "show", UNIT, "--json")[0],
              review(capsys, work, snap, "show", UNIT)[0]]
    review(capsys, work, snap, "decide", UNIT, "faithful", str(texts / "c.md"))
    shown += [review(capsys, work, snap, "author", UNIT, "--json")[0]]
    review(capsys, work, snap, "submit", UNIT, str(texts / "n.md"))
    return shown


def test_review_reads_from_the_source_what_a_snapshot_with_the_text_shows(paper, tmp_path,
                                                                         monkeypatch, capsys):
    data, src = paper
    # Step 3 shows when the reviewer took the earlier steps: one time for both reviews.
    monkeypatch.setattr(rc, "now", lambda: "2026-01-01T00:00:00Z")
    rs.pack(data, tmp_path / "with-text")
    rs.pack(data, tmp_path / "without.zip", without=private(src))
    (tmp_path / "eprint.tar.gz").write_bytes(eprint(src))
    expected = steps(capsys, tmp_path, tmp_path / "wa", tmp_path / "with-text")
    got = steps(capsys, tmp_path, tmp_path / "wb", tmp_path / "without.zip",
                given=[f"S={tmp_path / 'eprint.tar.gz'}"])
    assert got == expected
    assert "Statement 4: for every natural number" in got[1] and "Fix the order" in got[1]
    # The source given is kept for the later steps, and each step says where the text is from.
    out, err = review(capsys, tmp_path / "wb", tmp_path / "without.zip", "status")
    assert err == (f"note: the passages of paper S are read from arXiv {ARXIV}, each checked "
                   "against its digest\n")
    assert (tmp_path / "wb" / "sources" / "S" / "main.tex").is_file()
    # A snapshot that holds the text does not use a source given.
    _, err = review(capsys, tmp_path / "wa", tmp_path / "with-text", "status",
                    given=[str(tmp_path / "eprint.tar.gz")])
    assert err == "note: the snapshot holds the paper's text: --paper-source is not used\n"


def refused(capsys, work, snap, given=()) -> dict:
    out, _ = review(capsys, work, snap, "read", UNIT, "--json", code=2, given=given)
    err = json.loads(out)["error"]
    assert err["kind"] == "paper-source", err
    return err


def test_the_source_is_obtained_once_and_refused_when_it_differs_or_is_missing(
        paper, tmp_path, monkeypatch, capsys):
    data, src = paper
    snap = tmp_path / "snap"
    rs.pack(data, snap, without=private(src))
    served = {"body": eprint(src), "calls": 0}

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        served["calls"] += 1
        assert req.full_url == f"https://arxiv.org/e-print/{ARXIV}"
        if served["body"] is None:
            raise urllib.error.URLError("no network here")
        return Reply(served["body"])

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    out, _ = review(capsys, tmp_path / "w", snap, "read", UNIT)
    assert "Statement 4: for every natural number" in out and served["calls"] == 1
    review(capsys, tmp_path / "w", snap, "read", UNIT)
    assert served["calls"] == 1  # the download is kept in the reviewer's directory
    # A copy changed in the reviewer's directory is unpacked again from the download.
    (tmp_path / "w" / "sources" / "S" / "main.tex").write_text("changed")
    assert "Statement 4" in review(capsys, tmp_path / "w", snap, "read", UNIT)[0]
    assert served["calls"] == 1

    # Another source on arXiv, or none, refuses the step before anything is shown.
    changed = tmp_path / "changed"
    shutil.copytree(src, changed)
    (changed / "main.tex").write_text((src / "main.tex").read_text().replace("uniformly",
                                                                             "evenly"))
    served["body"] = eprint(changed)
    err = refused(capsys, tmp_path / "w2", snap)
    assert err["message"].startswith(f"the source arXiv serves for {ARXIV} is not the one the "
                                     "snapshot was made from: main.tex differs")
    served["body"] = None
    err = refused(capsys, tmp_path / "w3", snap)
    assert "could not be obtained" in err["message"] and "no network here" in err["message"]
    assert "give it with --paper-source S=FILE" in err["message"]
    assert not (tmp_path / "w3" / "resolved").exists()
    err = refused(capsys, tmp_path / "w4", snap, given=[str(changed)])
    assert err["message"] == (f"the source given for paper S ({changed}) is not the one the "
                              f"snapshot was made from (arXiv {ARXIV}): main.tex differs. No "
                              "step was taken")
    err = refused(capsys, tmp_path / "w4", snap, given=[str(tmp_path / "nothing")])
    assert "no such file or folder" in err["message"]
    # A source the snapshot does not name is given by the reviewer.
    rs.pack(data, tmp_path / "git-snap", without=private(src, {"kind": "git",
                                                               "revision": "a" * 40}))
    err = refused(capsys, tmp_path / "w5", tmp_path / "git-snap")
    assert f"its Git repository at commit {'a' * 40}" in err["message"]
    assert "--paper-source S=FILE" in err["message"]
    out, _ = review(capsys, tmp_path / "w5", tmp_path / "git-snap", "read", UNIT,
                    given=[str(src)])
    assert "Statement 4" in out
    # A passage whose digest the source does not give is refused, whatever the files' digests.
    def tamper(edit):
        refs = json.loads((snap / st.REFS).read_text())
        edit(refs["claims"]["claims/S_thm_t6.json"][0])
        (snap / st.REFS).write_bytes(rs._json_bytes(refs))
        manifest = json.loads((snap / rs.MANIFEST).read_text())
        manifest["files"][st.REFS] = hashlib.sha256((snap / st.REFS).read_bytes()).hexdigest()
        (snap / rs.MANIFEST).write_text(json.dumps(manifest))

    tamper(lambda r: r["bytes"].__setitem__(0, r["bytes"][0] + 1))
    err = refused(capsys, tmp_path / "w6", snap, given=[str(src)])
    assert "does not give the passage statement_tex of S:thm:t6 (main.tex" in err["message"]
    # Nor is a passage read from a file whose digest the manifest does not give.
    tamper(lambda r: r.update(file="refs.bib", bytes=[0, 10]))
    err = refused(capsys, tmp_path / "w6", snap, given=[str(src)])
    assert "does not give a passage of S:thm:t6 (refs.bib)" in err["message"]


PAPER = """
[[paper]]
id = "S"
title = "Synthetic"
source = { arxiv = "2601.00001v1" }
publish = { source_text = SETTING }
"""


@pytest.fixture
def project(paper, tmp_path):
    """A full assessment of the synthetic paper whose last build is the synthetic site, with
    the build's copy of the paper's source."""
    data, src = paper
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "syn"\n')
    shutil.move(tmp_path / "work", root / ".machinechecked")
    (root / "machinechecked.toml").write_text(CONFIG + PAPER.replace("SETTING", "false")
                                              + '\n[review]\nsnapshot = "review-snapshot"\n')
    return root


def test_the_configuration_decides_what_pack_and_build_keep(project, tmp_path, monkeypatch,
                                                            capsys):
    monkeypatch.chdir(project)
    cli.main(["review", "pack", "--out", str(tmp_path / "public")])
    out = capsys.readouterr().out
    assert f"paper S: its text left out; a reviewer reads each passage from arXiv {ARXIV}" in out
    assert rs.SCHEMA_WITHOUT_TEXT == json.loads(
        (tmp_path / "public" / rs.MANIFEST).read_text())["schema"]
    cli.main(["review", "pack", "--out", str(tmp_path / "private.zip"), "--with-paper-text"])
    assert "paper S: its text kept, as asked (--with-paper-text)" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "pack", "--with-paper-text"])
    assert e.value.code == 2 and not (project / "review-snapshot").exists()
    assert "follows each paper's publish.source_text: give --out FILE" in capsys.readouterr().err
    # The snapshot the project keeps, written by build, follows the configuration.
    no_build(monkeypatch, full=True)
    cli.main(["build"])
    assert capsys.readouterr().out == (
        "wrote the review snapshot review-snapshot/ (release v-synthetic; the text of paper S "
        "is left out, for the reviewer to read from its source): commit it with the project "
        "for reviewers who clone the repository\n")
    assert export_scan(project / "review-snapshot",
                       source_lines(project / ".machinechecked" / "sources" / "S"), set()) == []
    # A paper whose text is published, or read from its PDF, keeps it.
    (project / "machinechecked.toml").write_text(
        CONFIG + PAPER.replace("SETTING", "true") + '\n[review]\nsnapshot = "review-snapshot"\n')
    cli.main(["build"])
    m = json.loads((project / "review-snapshot" / rs.MANIFEST).read_text())
    assert m["schema"] == rs.SCHEMA and m["paper_text"] == {"S": {"included": True,
                                                                   "because": "published"}}
    capsys.readouterr()
    (project / "machinechecked.toml").write_text(CONFIG + PAPER.replace("SETTING", "false"))
    idx = project / ".machinechecked" / "site" / "data" / "index.json"
    index = json.loads(idx.read_text())
    index["papers"][0]["mode"] = "pdf"
    idx.write_text(json.dumps(index))
    cli.main(["review", "pack", "--out", str(tmp_path / "pdf")])
    assert "paper S: its text kept, it is read from its PDF, whose text has no source to read " \
           "it again from" in capsys.readouterr().out


@needs_lean
@needs_tex
def test_a_clone_of_the_toy_with_its_text_private_is_reviewed_from_the_paper_s_folder(
        toy, tmp_path, monkeypatch, capsys):
    cfg_file = toy / "machinechecked.toml"
    cfg_file.write_text(cfg_file.read_text().replace(
        "publish = { pdf = true, source_text = true,",
        "publish = { pdf = true, source_text = false,") + '\n[review]\nsnapshot = "review-snapshot"\n')
    (toy / ".gitignore").write_text(".machinechecked/\n.lake/\n")
    git(toy, "init", "-q")
    git(toy, "add", "-A")
    git(toy, "commit", "-q", "-m", "The toy paper")
    monkeypatch.chdir(toy)
    cli.main(["build"])
    assert "the text of paper T is left out" in capsys.readouterr().out
    snap = toy / "review-snapshot"
    assert export_scan(snap, source_lines(toy / ".machinechecked" / "sources" / "T"), set()) == []
    git(toy, "add", "-A")
    git(toy, "commit", "-q", "-m", "Its review snapshot, without the paper's text")
    unit = "def:Toy.triangle"
    cli.main(["review", "read", unit, "--json", "--as", "human:Toy-Author"])
    author_read = capsys.readouterr().out

    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(toy), str(clone))
    env = lean_free(tmp_path)

    def run(*args, cwd=clone, code=0):
        r = subprocess.run([sys.executable, "-m", "prooflens", "review", *args], cwd=cwd,
                           env=env, capture_output=True, text=True, encoding="utf-8",
                           timeout=300)
        assert r.returncode == code, r.stdout + r.stderr
        return r

    # In the clone, the paper's folder is the source: the reviewer reads what the author sees.
    r = run("read", unit, "--json")
    assert r.stdout == author_read
    assert "the passages of paper T are read from the folder paper of the project" in r.stderr
    (tmp_path / "reading.md").write_text("T_n is the sum 0 + 1 + ... + n.")
    (tmp_path / "comparison.md").write_text("The recursion is the sum.")
    (tmp_path / "none.md").write_text("none")
    run("lock", unit, str(tmp_path / "reading.md"))
    run("show", unit)
    run("decide", unit, "faithful", str(tmp_path / "comparison.md"))
    run("author", unit)
    run("submit", unit, str(tmp_path / "none.md"))
    run("export", "--out", str(tmp_path / "reports.json"))
    assert git(clone, "status", "--porcelain") == ""
    (rep,) = pr.load_reports([tmp_path / "reports.json"])
    (_, _, why), = pr.plan(cfgmod_load(cfg_file), [rep])
    assert not why, why

    # Elsewhere, with the snapshot alone, the source is given.
    away = tmp_path / "away"
    away.mkdir()
    r = run("read", unit, "--json", "--snapshot", str(clone / "review-snapshot"), cwd=away,
            code=2)
    assert json.loads(r.stdout)["error"]["kind"] == "paper-source"
    r = run("read", unit, "--json", "--snapshot", str(clone / "review-snapshot"),
            "--paper-source", str(clone / "paper"), cwd=away)
    assert r.stdout == author_read


def cfgmod_load(path):
    from prooflens import config
    return config.load(path)
