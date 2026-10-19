"""Moving an inventory to a new revision of its paper (#62), on synthetic manuscripts."""

from copy import deepcopy
import json
import subprocess

import pytest

from prooflens.repin import main, repin_plan
from prooflens.source_regions import SCHEME, RegionError, changed_line, collect, extract, matches
from test_source_regions import assessed

OLD, NEW = "a" * 40, "b" * 40

A = "\\begin{equation}\\label{eq:a}\na = 1\n\\end{equation}\n"
B = "\\begin{equation}\nb = 2\n\\end{equation}\n"
C = "Let $x$ be positive. Then $x+x$ is positive.\n"
E = "\\begin{align}\\label{eq:e}\ne &= 5\\\\\nf &= 6\n\\end{align}\n"
R = "\\begin{equation}\\label{eq:r}\nr = 0\n\\end{equation}\n"
D = "\\begin{equation}\\label{eq:d}\nd = 4\n\\end{equation}\n"
N = "\\begin{equation}\\label{eq:n}\nn = 1\n\\end{equation}\n"
HEAD, TAIL = "\\documentclass{article}\n\\begin{document}\nIntro.\n", "\\end{document}\n"


def write(root, *parts):
    root.mkdir(parents=True, exist_ok=True)
    (root / "paper.tex").write_text(HEAD + "".join(parts) + TAIL, encoding="utf-8")
    return root


def line_of(root, passage):
    return (root / "paper.tex").read_text(encoding="utf-8").split(passage)[0].count("\n") + 1


def pinned(root, cid, passage, **extra):
    """A claim on `tex-region-v1`, pinned at OLD to `passage` of the manuscript at `root`."""
    c = {"id": f"T:{cid}", "paper": "T", "location": f"paper.tex:{line_of(root, passage)}",
         "scope": "formal", "clauses": [{"name": "main", "spec": f"Synthetic.{cid}"}], **extra}
    region = extract(root, c)
    return {**c, "source_hash_scheme": SCHEME, "source_sha256": region.sha256,
            "source_line_sha256": region.line_sha256}


def inventory(root):
    span = {"source_region": {"end_line": line_of(root, C), "end_column": 21}}
    return {"note": "Synthetic inventory", "papers": {"T": {"commit": OLD[:7]}}, "claims": [
        pinned(root, "a", A), pinned(root, "b", B), pinned(root, "c", C, **span),
        pinned(root, "e", E), pinned(root, "r", R), pinned(root, "d", D),
        {"id": "U:other", "paper": "U", "location": "other.tex:1", "scope": "formal",
         "clauses": [{"name": "main"}]}]}


def by_claim(report):
    return {e["claim"]: e for e in report["claims"]}


@pytest.fixture
def snapshots(tmp_path):
    old = write(tmp_path / "old", A, B, C, E, R, D)
    new = write(tmp_path / "new", "Added.\n\n", A, B, "More.\n", C, E.replace("f &= 6", "f &= 7"),
                D, N, D)
    return old, new


def test_moved_changed_removed_and_ambiguous_passages_are_told_apart(snapshots):
    old, new = snapshots
    inv = inventory(old)
    before = deepcopy(inv)
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    assert inv == before
    e = by_claim(report)
    # Three passages that only moved, one of them under an opening line it shares with another.
    assert [e[f"T:{x}"]["class"] for x in "abc"] == ["moved"] * 3
    assert e["T:a"]["to"] == "paper.tex:6" and e["T:b"]["to"] == "paper.tex:9"
    assert e["T:c"]["to_region"]["end_column"] == 21
    # One whose text changed, reported with its line and a diff.
    assert e["T:e"]["class"] == "changed"
    assert e["T:e"]["where"] == f"line 3 of the passage (line {line_of(new, 'e &=') + 1} of " \
        "paper.tex) changed"
    assert "-f &= 6" in e["T:e"]["diff"] and "+f &= 7" in e["T:e"]["diff"]
    assert e["T:r"]["class"] == "removed" and "eq:r" in e["T:r"]["reason"]
    # A passage copied in the new revision is not chosen between.
    assert e["T:d"]["class"] == "ambiguous" and len(e["T:d"]["candidates"]) == 2
    assert report["blocking"] == ["T:d"]
    assert report["new_passages"] == [{"location": f"paper.tex:{line_of(new, N)}",
                                       "label": "eq:n"}]
    assert report["counts"] == {"moved": 3, "changed": 1, "removed": 1, "ambiguous": 1}
    claims = {c["id"]: c for c in result["claims"]}
    assert claims["T:d"] == next(c for c in before["claims"] if c["id"] == "T:d")
    assert claims["U:other"] == before["claims"][-1]
    assert result["papers"]["T"]["commit"] == NEW[:7]


def test_a_changed_passage_keeps_its_pin_and_stays_mismatched(snapshots):
    """A repin does not accept new text: the changed passage keeps its digests and revision,
    and the source check at the new revision reports the line that changed."""
    old, new = snapshots
    inv = inventory(old)
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    claims = {c["id"]: c for c in result["claims"]}
    original = {c["id"]: c for c in inv["claims"]}
    e = claims["T:e"]
    assert e["source_sha256"] == original["T:e"]["source_sha256"]
    assert e["source_line_sha256"] == original["T:e"]["source_line_sha256"]
    assert e["commit"] == OLD[:7] and e["location"] == by_claim(report)["T:e"]["to"]
    regions = collect(result, "T", new)
    tex = {"regions": regions}
    assert all(matches(claims[f"T:{x}"], tex) for x in "abc")
    assert not matches(e, tex)
    assert changed_line(e, regions["T:e"]).startswith("line 3 of the passage")
    for x in "abc":
        assert claims[f"T:{x}"]["source_sha256"] == original[f"T:{x}"]["source_sha256"]
        assert claims[f"T:{x}"]["clauses"] == original[f"T:{x}"]["clauses"]


def test_assessment_and_reader_at_the_new_revision(snapshots):
    from prooflens.manifest import build
    old, new = snapshots
    result, _ = repin_plan(inventory(old), "T", old, new, OLD, NEW)
    claims = {c["id"]: c for c in result["claims"]}
    for cid, passes in (("T:a", True), ("T:e", False)):
        c = {**claims[cid], "clauses": [{"name": "main", "spec": "Synthetic.spec",
                                         "accept": "Synthetic.accept"}], "scope_reviewed": True}
        tex = {"mode": "latex", "envs": [], "anchors": [],
               "regions": collect({"claims": [c]}, "T", new),
               "manual_anchors": {cid: {"page": 1, "y0": 100, "y1": 150}}}
        record = assessed(new, c, tex)
        a = record["body"]["assessment"]
        assert a["gates"]["T"]["release"]["pass"] is passes
        assert any(f["code"] == "source-changed" for f in a["findings"]) is not passes
        _, chunks, _ = build(record, "synthetic")
        assert next(iter(chunks.values()))["source_matches"] is passes


def test_repeated_labels_prose_and_missing_ends_are_never_repinned(tmp_path):
    old = write(tmp_path / "old", A, C, E)
    inv = {"claims": [pinned(old, "a", A), pinned(old, "e", E),
                      pinned(old, "c", C, source_region={"end_line": line_of(old, C)})]}
    # The label of `a` twice, once on edited text; the prose twice; `e` without its end.
    new = write(tmp_path / "new", A.replace("a = 1", "a = 2"), C, A, C,
                E.replace("\\end{align}\n", ""))
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    e = by_claim(report)
    assert e["T:a"]["class"] == "ambiguous" and "label eq:a occurs 2 times" in e["T:a"]["reason"]
    assert e["T:c"]["class"] == "ambiguous" and "occurs 2 times" in e["T:c"]["reason"]
    assert e["T:e"]["class"] == "changed" and "to" not in e["T:e"]
    assert "no complete align environment" in e["T:e"]["reason"]
    claims = {c["id"]: c for c in result["claims"]}
    assert claims["T:e"]["location"] == inv["claims"][1]["location"]
    assert claims["T:e"]["source_sha256"] == inv["claims"][1]["source_sha256"]
    assert sorted(report["blocking"]) == ["T:a", "T:c"]


def test_an_edited_unlabelled_line_is_not_found_not_guessed(tmp_path):
    old = write(tmp_path / "old", "First claim.\n", "Second claim.\n")
    inv = {"claims": [pinned(old, "x", "First claim.\n")]}
    new = write(tmp_path / "new", "First claim, edited.\n", "Second claim.\n")
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    assert report["claims"][0]["class"] == "not-found"
    assert result["claims"][0]["location"] == inv["claims"][0]["location"]
    assert result["claims"][0]["commit"] == OLD


def test_pins_baselines_and_other_revisions(tmp_path):
    old = write(tmp_path / "old", A, B)
    new = write(tmp_path / "new", "Added.\n", A, B)
    a = pinned(old, "a", A, commit=OLD[:7])
    b = pinned(old, "b", B, commit="c" * 7)
    result, report = repin_plan({"claims": [a, b]}, "T", old, new, OLD, NEW)
    assert result["claims"][0]["commit"] == NEW[:7]
    # A claim pinned at another revision is reported and left as it is.
    assert by_claim(report)["T:b"]["class"] == "pending-review"
    assert result["claims"][1] == b
    # The original snapshot must hold the pinned text, and the pin must be a region pin.
    wrong = {**a, "source_sha256": "f" * 64}
    with pytest.raises(RegionError, match="differs from its pin"):
        repin_plan({"claims": [wrong]}, "T", old, new, OLD, NEW)
    legacy = {**a}
    del legacy["source_hash_scheme"]
    with pytest.raises(RegionError, match="source_regions"):
        repin_plan({"claims": [legacy]}, "T", old, new, OLD, NEW)


def test_a_change_beside_an_unchanged_passage_is_reported_separately(tmp_path):
    """The audited passage is the same; the text beside it, which an excerpt may show, is not."""
    old = write(tmp_path / "old", A, "Some prose after it.\n")
    inv = {"claims": [pinned(old, "a", A)]}
    new = write(tmp_path / "new", A, "Other prose after it.\n")
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    entry = report["claims"][0]
    assert entry["class"] == "unchanged" and entry["context_changed"] is True
    assert matches(result["claims"][0], {"regions": collect(result, "T", new)})
    _, same = repin_plan(inv, "T", old, old, OLD, OLD)
    assert same["claims"][0]["context_changed"] is False


# -- the command, on a Git manuscript ---------------------------------------------------------

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Synthetic",
                           "-c", "user.email=synthetic@example.org", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def commit(repo, *parts):
    write(repo, *parts)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "revision")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "manuscript"
    repo.mkdir()
    git(repo, "init", "-q")
    first = commit(repo, A, B, E)
    inv = {"papers": {"T": {"commit": first[:7]}},
           "claims": [pinned(repo, "a", A), pinned(repo, "b", B), pinned(repo, "e", E)]}
    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    (proj / "machinechecked.toml").write_text(
        '[project]\nname = "synthetic"\nmodules = ["S"]\nscope_roots = ["S"]\n'
        'spec_prefix = "S.Spec"\naccept_prefix = "S.Accept"\ninventory = "claims.json"\n\n'
        f'[[paper]]\nid = "T"\nroot = "paper.tex"\n'
        f'source = {{ git = "../manuscript", rev = "{first}" }}\n', encoding="utf-8")
    return repo, proj, first


def run(proj, *args, capsys):
    code = None
    try:
        code = main(["--config", str(proj / "machinechecked.toml"), "--paper", "T", *args])
    except SystemExit as exit:
        code = exit.code
    out = capsys.readouterr()
    return code, out.out, out.err


def files(proj):
    return {p.name: p.read_bytes() for p in proj.iterdir()}


def test_command_plans_writes_once_and_is_idempotent(project, capsys):
    repo, proj, first = project
    second = commit(repo, "Added.\n", A, B, E.replace("f &= 6", "f &= 7"))
    before = files(proj)
    code, out, _ = run(proj, "--to", second, capsys=capsys)
    assert code == 0 and files(proj) == before
    plan = json.loads(out)
    assert plan["applied"] is False and plan["counts"] == {"moved": 2, "changed": 1}
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is True
    toml = (proj / "machinechecked.toml").read_text(encoding="utf-8")
    assert f'rev = "{second}"' in toml and first not in toml
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    assert inv["papers"]["T"]["commit"] == second[:7]
    claims = {c["id"]: c for c in inv["claims"]}
    assert claims["T:a"]["location"] == "paper.tex:5" and "commit" not in claims["T:a"]
    assert claims["T:e"]["commit"] == first[:7]
    # Again: the moved claims are now unchanged, the changed one awaits review; nothing changes.
    after = files(proj)
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0 and files(proj) == after
    again = json.loads(out)
    assert again["written"] is False
    assert again["counts"] == {"unchanged": 2, "pending-review": 1}


def test_command_writes_nothing_while_a_claim_is_ambiguous(project, capsys):
    repo, proj, _ = project
    second = commit(repo, A, B, B, E)
    before = files(proj)
    code, _, err = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 2 and "ambiguous claims T:b" in err
    assert files(proj) == before


def test_command_refuses_an_inventory_changed_while_planning(project, capsys, monkeypatch):
    import prooflens.repin as repin
    repo, proj, _ = project
    second = commit(repo, "Added.\n", A, B, E)
    config = (proj / "machinechecked.toml").read_bytes()
    plan = repin.repin_plan

    def concurrently(*args):
        (proj / "claims.json").write_text("Changed concurrently.", encoding="utf-8")
        return plan(*args)
    monkeypatch.setattr(repin, "repin_plan", concurrently)
    code, _, err = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 2 and "changed while planning" in err
    assert (proj / "claims.json").read_text(encoding="utf-8") == "Changed concurrently."
    assert (proj / "machinechecked.toml").read_bytes() == config
    assert not [p for p in proj.iterdir() if p.name.startswith(".")]


def test_command_needs_the_original_snapshot(project, capsys):
    repo, proj, first = project
    second = commit(repo, "Added.\n", A, B, E)
    toml = proj / "machinechecked.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(first, "d" * 40), encoding="utf-8")
    code, _, err = run(proj, "--to", second, capsys=capsys)
    assert code == 2 and "original revision " + "d" * 40 + " cannot be read" in err
    toml.write_text(toml.read_text(encoding="utf-8").replace("d" * 40, "main"),
                    encoding="utf-8")
    code, _, err = run(proj, "--to", second, capsys=capsys)
    assert code == 2 and "full Git commit" in err


def test_a_passage_moved_to_another_file_says_so(tmp_path):
    old = write(tmp_path / "old", A, B)
    inv = {"claims": [pinned(old, "a", A)]}
    new = write(tmp_path / "new", B)
    (new / "appendix.tex").write_text("Appendix.\n" + A, encoding="utf-8")
    result, report = repin_plan(inv, "T", old, new, OLD, NEW)
    entry = report["claims"][0]
    assert entry["class"] == "moved" and entry["to"] == "appendix.tex:2"
    assert "appendix.tex" in entry["note"]
    assert matches(result["claims"][0], {"regions": collect(result, "T", new)})


@pytest.mark.parametrize("hide", [
    lambda p: "".join("% " + line + "\n" for line in p.splitlines()),
    lambda p: "\\iffalse\n" + p + "\\fi\n",
    lambda p: "\\iffalse\\ifx a b\\fi\n" + p + "\\fi\n",
    lambda p: "\\begin{comment}\n" + p + "\\end{comment}\n"])
def test_a_copy_the_paper_may_not_print_is_not_a_match(tmp_path, hide):
    """The prose was rewritten and its old text kept in a comment or a dead block: the old
    copy is not taken as the passage."""
    old = write(tmp_path / "old", "Intro line.\n", C)
    inv = {"claims": [pinned(old, "c", C, source_region={"end_line": line_of(old, C)})]}
    new = write(tmp_path / "new", hide(C), "Rewritten prose.\n")
    _, report = repin_plan(inv, "T", old, new, OLD, NEW)
    assert report["claims"][0]["class"] == "ambiguous"
    assert "may not print" in report["claims"][0]["reason"]


def test_text_after_a_closed_block_is_printed(tmp_path):
    from prooflens.repin import dead_ranges
    text = "\\iffalse\nhidden\n\\else\nshown\n\\fi\n" + C
    assert all(not a <= text.index(C) < b for a, b in dead_ranges(text))
    assert all(not a <= text.index("shown") < b for a, b in dead_ranges(text))
    assert any(a <= text.index("hidden") < b for a, b in dead_ranges(text))


def test_display_excerpts_move_or_are_invalidated_separately(project, capsys):
    """An excerpt selected by its place moves with its text, or selects nothing at the new
    revision; one selected by a label is read again at the next build. The inventory's audited
    pins are handled as before, whatever happens to the excerpts (#62, #69)."""
    from prooflens.excerpt import excerpt_for
    repo, proj, first = project
    commit(repo, A, B, E, C)
    first = git(repo, "rev-parse", "HEAD")
    inv = {"papers": {"T": {"commit": first[:7]}},
           "claims": [pinned(repo, "a", A), pinned(repo, "b", B), pinned(repo, "e", E)]}
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    toml = (proj / "machinechecked.toml").read_text(encoding="utf-8")
    toml = toml.replace('inventory = "claims.json"', 'inventory = "claims.json"\n'
                        'display = "display.json"').replace(git(repo, "rev-parse", "HEAD~1"), first)
    (proj / "machinechecked.toml").write_text(toml, encoding="utf-8")
    at_c = line_of(repo, C)
    display = {"claims": {
        "T:a": {"excerpt": {"label": "eq:a"}},
        "T:b": {"excerpt": {"location": f"paper.tex:{line_of(repo, B)}", "end_line": at_c,
                            "end_column": 21}},
        "T:e": {"excerpt": {"location": f"paper.tex:{at_c}", "end_line": at_c,
                            "end_column": 21}, "title_tex": "kept"}}}
    (proj / "display.json").write_text(json.dumps(display), encoding="utf-8")
    # Lines are added before every passage; the prose after B's display changes, C does not.
    second = commit(repo, "Added.\n\n", A, B, E, "Inserted.\n", C)
    before = files(proj)
    code, out, _ = run(proj, "--to", second, capsys=capsys)
    assert code == 0 and files(proj) == before, "a plan writes nothing"
    plan = json.loads(out)
    assert plan["counts"] == {"moved": 3}
    ex = {e["claim"]: e for e in plan["excerpts"]}
    assert ex["T:a"]["class"] == "follows-label"
    assert ex["T:b"]["class"] == "invalidated" and "select the passage again" in ex["T:b"]["reason"]
    assert ex["T:e"]["class"] == "moved" and ex["T:e"]["to"] == {
        "location": f"paper.tex:{line_of(repo, C)}", "end_line": line_of(repo, C),
        "end_column": 21}
    assert ex["T:e"]["context_changed"] is True
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is True
    shown = json.loads((proj / "display.json").read_text(encoding="utf-8"))["claims"]
    assert shown["T:a"] == display["claims"]["T:a"]
    assert shown["T:e"] == {"excerpt": ex["T:e"]["to"], "title_tex": "kept"}
    assert shown["T:b"]["excerpt"] == {**display["claims"]["T:b"]["excerpt"], "revision": first}
    # The invalidated selector selects nothing at the new revision; the moved one is the same
    # passage there.
    aux = {"labels": {}, "cites": {}}
    stale = excerpt_for(repo, "paper.tex", aux, second, set(), None, None,
                        shown["T:b"]["excerpt"])
    assert stale["ready"] is False and "selected at revision" in stale["reasons"][0]
    moved = excerpt_for(repo, "paper.tex", aux, second, set(), None, None,
                        shown["T:e"]["excerpt"])
    assert moved["ready"], moved["reasons"]
    assert moved["text"] == C[:20]
    # Again: nothing more is written.
    after = files(proj)
    code, out, _ = run(proj, "--to", second, "--write", capsys=capsys)
    assert code == 0 and files(proj) == after
    again = {e["claim"]: e["class"] for e in json.loads(out)["excerpts"]}
    assert again == {"T:a": "follows-label", "T:b": "stale", "T:e": "unchanged"}
