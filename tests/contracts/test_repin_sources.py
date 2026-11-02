"""Repinning and migrating a manuscript vendored into the project, from folders, and inventories
that mix environment pins and line pins (#166), on synthetic manuscripts."""

import hashlib
import json
import subprocess

import pytest

from prooflens import repin, source_regions
from prooflens.source_regions import SCHEME, extract
from prooflens.util import norm_ws

OLD, NEW = "a" * 40, "b" * 40
HEAD = "\\documentclass{article}\n\\newtheorem{theorem}{Theorem}\n\\begin{document}\n"
TAIL = "\\end{document}\n"
THM = "\\begin{theorem}\\label{thm:t}\nEvery even number is a sum of two even numbers.\n" \
      "\\end{theorem}\n"
EQ = "\\begin{equation}\\label{eq:q}\nq = 1\n\\end{equation}\n"
# The body the compiled paper's anchor hashes: everything inside the environment.
BODY = "\\label{thm:t}\nEvery even number is a sum of two even numbers."
NOLABEL = "\\begin{theorem}\nZero is even.\n\\end{theorem}\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Synthetic",
                           "-c", "user.email=synthetic@example.org", *args],
                          check=True, capture_output=True, text=True).stdout.strip()


def write(folder, *parts):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "paper.tex").write_text(HEAD + "".join(parts) + TAIL, encoding="utf-8")
    return folder


def env_hash(body):
    return hashlib.sha256(norm_ws(body).encode("utf-8")).hexdigest()


def claims(folder, extra=()):
    text = (folder / "paper.tex").read_text(encoding="utf-8")
    line = text.split(EQ)[0].count("\n") + 1
    eq = {"id": "T:eq:q", "paper": "T", "kind": "equation", "location": f"paper.tex:{line}",
          "scope": "formal", "clauses": []}
    region = extract(folder, eq)
    eq.update(source_hash_scheme=SCHEME, source_sha256=region.sha256,
              source_line_sha256=region.line_sha256)
    thm = {"id": "T:thm:t", "paper": "T", "kind": "theorem", "label": "thm:t",
           "location": "paper.tex", "scope": "formal", "clauses": [],
           "source_sha256": env_hash(BODY)}
    note = {"id": "T:intro", "paper": "T", "scope": "expository", "clauses": []}
    return [eq, thm, note, *extra]


@pytest.fixture
def vendored(tmp_path):
    """A Lean project whose manuscript is a folder in the project's own repository."""
    proj = tmp_path / "project"
    write(proj / "manuscript", "Intro.\n", EQ, THM)
    inv = {"papers": {"T": {"commit": OLD[:7]}}, "claims": claims(proj / "manuscript")}
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    (proj / "machinechecked.toml").write_text(
        '[project]\nname = "synthetic"\nmodules = ["S"]\nscope_roots = ["S"]\n'
        'spec_prefix = "S.Spec"\naccept_prefix = "S.Accept"\ninventory = "claims.json"\n\n'
        '[[paper]]\nid = "T"\nroot = "paper.tex"\nsource = { path = "manuscript" }\n',
        encoding="utf-8")
    git(proj, "init", "-q")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "first")
    return proj


def run(main, proj, *args, capsys):
    try:
        code = main(["--config", str(proj / "machinechecked.toml"), "--paper", "T", *args])
    except SystemExit as exit:
        code = exit.code
    out = capsys.readouterr()
    return code, out.out, out.err


def by_claim(plan):
    return {e["claim"]: e for e in plan["claims"]}


def test_a_vendored_manuscript_is_repinned_from_its_committed_copy(vendored, capsys):
    proj = vendored
    config = (proj / "machinechecked.toml").read_bytes()
    write(proj / "manuscript", "Intro.\nAdded.\n\n", EQ,
          THM.replace("two even", "two even or two odd"))
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW,
                       capsys=capsys)
    assert code == 0, out + err
    plan = json.loads(out)
    got = by_claim(plan)
    assert got["T:eq:q"]["class"] == "moved"
    assert got["T:thm:t"]["class"] == "changed" and got["T:thm:t"]["pin"] == "environment"
    assert any("two odd" in line for line in got["T:thm:t"]["diff"])
    # Every claim of the paper is listed, the one without a pin as such.
    assert got["T:intro"]["class"] == "unpinned"
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW, "--write",
                       capsys=capsys)
    assert code == 0 and json.loads(out)["written"]
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    assert inv["papers"]["T"]["commit"] == NEW[:7]
    c = {x["id"]: x for x in inv["claims"]}
    assert c["T:eq:q"]["location"] == "paper.tex:7" and "commit" not in c["T:eq:q"]
    # The changed theorem keeps the digest it was reviewed at, and its revision.
    assert c["T:thm:t"]["source_sha256"] == env_hash(BODY)
    assert c["T:thm:t"]["commit"] == OLD[:7]
    # A folder has no revision in the configuration: it is left as it is.
    assert (proj / "machinechecked.toml").read_bytes() == config


def test_a_baseline_that_is_not_the_pinned_text_is_refused(vendored, capsys):
    proj = vendored
    write(proj / "manuscript", "Intro.\n", EQ.replace("q = 1", "q = 2"), THM)
    # The working folder is not the revision the inventory was pinned at.
    code, _, err = run(repin.main, proj, "--from-source", str(proj / "manuscript"), "--to",
                       NEW, capsys=capsys)
    assert code == 2 and "differs from its pin" in err


def test_two_folders_with_a_git_configuration(tmp_path, capsys):
    proj = tmp_path / "project"
    old = write(tmp_path / "old", "Intro.\n", EQ, THM)
    new = write(tmp_path / "new", THM, "Intro.\n", EQ)
    proj.mkdir()
    inv = {"papers": {"T": {"commit": OLD}}, "claims": claims(old)}
    (proj / "claims.json").write_text(json.dumps(inv) + "\n", encoding="utf-8")
    (proj / "machinechecked.toml").write_text(
        '[project]\nname = "synthetic"\nmodules = ["S"]\nscope_roots = ["S"]\n'
        'spec_prefix = "S.Spec"\naccept_prefix = "S.Accept"\ninventory = "claims.json"\n\n'
        f'[[paper]]\nid = "T"\nroot = "paper.tex"\n'
        f'source = {{ git = "../manuscript", rev = "{OLD}" }}\n', encoding="utf-8")
    code, out, err = run(repin.main, proj, "--from-source", str(old), "--from-rev", OLD,
                       "--to-source", str(new), "--to", NEW, "--write", capsys=capsys)
    assert code == 0, out + err
    got = by_claim(json.loads(out))
    assert got["T:eq:q"]["class"] == "moved" and got["T:thm:t"]["class"] == "unchanged"
    assert f'rev = "{NEW}"' in (proj / "machinechecked.toml").read_text(encoding="utf-8")


def test_an_environment_found_only_by_its_number_blocks_the_write(vendored, capsys):
    proj = vendored
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    inv["claims"].append({"id": "T:thm:zero", "paper": "T", "kind": "theorem",
                          "number": "Theorem 2", "location": "paper.tex", "scope": "formal",
                          "clauses": [], "source_sha256": env_hash("Zero is even.")})
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    write(proj / "manuscript", "Intro.\n", EQ, THM, NOLABEL)
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "unlabelled theorem")
    before = (proj / "claims.json").read_bytes()
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW,
                       capsys=capsys)
    plan = json.loads(out)
    assert by_claim(plan)["T:thm:zero"]["class"] == "not-handled"
    assert plan["blocking"] == ["T:thm:zero"]
    code, _, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW, "--write",
                       capsys=capsys)
    assert code == 2 and "claims it cannot place T:thm:zero" in err
    assert (proj / "claims.json").read_bytes() == before


ZERO = {"id": "T:thm:zero", "paper": "T", "kind": "theorem", "number": "Theorem 2",
        "location": "paper.tex", "scope": "formal", "clauses": [],
        "source_sha256": env_hash("Zero is even.")}


def test_a_claim_found_by_its_number_is_carried_over_with_keep(vendored, capsys):
    """#445: a revision that leaves an unlabelled environment's text alone moves the rest of the
    inventory, the kept claim with it."""
    proj = vendored
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    inv["claims"].append(ZERO)
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    write(proj / "manuscript", "Intro.\n", EQ, THM, NOLABEL)
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "unlabelled theorem")
    write(proj / "manuscript", "Intro.\nAdded.\n\n", EQ,
          THM.replace("two even", "two even or two odd"), NOLABEL)
    args = ("--from-source", "git:HEAD", "--to", NEW)
    before = (proj / "claims.json").read_bytes()
    code, _, err = run(repin.main, proj, *args, "--write", capsys=capsys)
    assert code == 2 and "--keep CLAIM" in err
    assert (proj / "claims.json").read_bytes() == before
    code, out, err = run(repin.main, proj, *args, "--keep", "T:thm:zero", capsys=capsys)
    assert code == 0, err
    plan = json.loads(out)
    zero = by_claim(plan)["T:thm:zero"]
    assert zero["class"] == "unchanged" and zero["kept"] is True
    assert "printed number" in zero["note"] and plan["blocking"] == []
    assert (proj / "claims.json").read_bytes() == before, "a plan writes nothing"
    code, out, err = run(repin.main, proj, *args, "--keep", "T:thm:zero", "--write",
                         capsys=capsys)
    assert code == 0 and json.loads(out)["written"] is True, err
    after = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    c = {x["id"]: x for x in after["claims"]}
    assert after["papers"]["T"]["commit"] == NEW[:7]
    # The kept claim is carried over as it was, now read at the new revision.
    assert c["T:thm:zero"] == ZERO
    # The rest of the plan is written: the moved display takes its place, and the changed
    # theorem keeps its digest and revision.
    assert c["T:eq:q"]["location"] == "paper.tex:7" and "commit" not in c["T:eq:q"]
    assert c["T:thm:t"]["source_sha256"] == env_hash(BODY)
    assert c["T:thm:t"]["commit"] == OLD[:7]


def test_a_kept_claim_whose_number_changed_is_reported_by_the_next_build():
    """A kept claim's printed number is not computed by the repin: when a theorem is inserted
    before it, the build finds another theorem under its number, and reports both."""
    from types import SimpleNamespace
    from prooflens.assess import Assessor

    def anchor(n, body, line):
        return {"id": f"a{n}", "env": "theorem", "number": str(n), "label": None,
                "file": "paper.tex", "line": line, "source_sha256": env_hash(body)}
    inv = {"claims": [{**ZERO, "scope_reviewed": True}]}
    tex = {"T": {"mode": "latex", "envs": ["theorem"], "regions": {},
                 "anchors": [anchor(2, "Two is even.", 8), anchor(3, "Zero is even.", 11)]}}
    cfg = SimpleNamespace(statement_authors=[], papers=[], lean_root=None)
    lean = {"specs": {}, "proofs": {}, "decls": {}, "defs": {}, "layering": []}
    findings = Assessor(cfg, inv, lean, tex, [], []).run()["findings"]
    codes = {(f["code"], f["subject"]) for f in findings if f["tier"] == "violation"}
    assert ("source-changed", "T:thm:zero") in codes
    assert any(code == "inventory-gap" for code, _ in codes)


def test_keep_needs_the_same_text_at_both_revisions(tmp_path):
    old = write(tmp_path / "old", "Intro.\n", EQ, THM, NOLABEL)
    inv = {"papers": {"T": {"commit": OLD[:7]}}, "claims": claims(old, [ZERO])}

    def plan(*parts, keep=("T:thm:zero",), files=None):
        new = write(tmp_path / f"new{len(list(tmp_path.iterdir()))}", *parts)
        for name, text in (files or {}).items():
            (new / name).write_text(text, encoding="utf-8")
        return repin.repin_plan(inv, "T", old, new, OLD, NEW, keep=keep)

    result, report = plan("Intro.\n", EQ, "\\input{results}\n",
                          files={"results.tex": THM + NOLABEL})
    zero = by_claim(report)["T:thm:zero"]
    assert zero["class"] == "moved" and zero["to"] == "results.tex"
    assert next(c for c in result["claims"] if c["id"] == "T:thm:zero")["location"] == \
        "results.tex"
    changed = NOLABEL.replace("Zero is even.", "Zero is even, and so is two.")
    with pytest.raises(source_regions.RegionError, match="no environment theorem of the new "
                       "revision has its text: it changed or was removed"):
        plan("Intro.\n", EQ, THM, changed)
    with pytest.raises(source_regions.RegionError, match="2 environments of the new revision"):
        plan("Intro.\n", EQ, THM, NOLABEL, NOLABEL)
    with pytest.raises(source_regions.RegionError, match="may not print"):
        plan("Intro.\n", EQ, THM, "\\iffalse\n" + NOLABEL + "\\fi\n")
    with pytest.raises(source_regions.RegionError, match="it is unchanged"):
        plan("Intro.\n", EQ, THM, NOLABEL, keep=("T:thm:zero", "T:thm:t"))
    with pytest.raises(source_regions.RegionError, match="T:intro: --keep carries over"):
        plan("Intro.\n", EQ, THM, NOLABEL, keep=("T:thm:zero", "T:intro"))
    twice = write(tmp_path / "twice", "Intro.\n", EQ, THM, NOLABEL, NOLABEL)
    with pytest.raises(source_regions.RegionError, match="2 environments at the original"):
        repin.repin_plan({"claims": claims(twice, [ZERO])}, "T", twice, twice, OLD, NEW,
                         keep=["T:thm:zero"])


def test_an_environment_moved_to_another_file_and_a_repeated_label(vendored, capsys):
    proj = vendored
    (proj / "manuscript" / "results.tex").write_text(THM, encoding="utf-8")
    write(proj / "manuscript", "Intro.\n", EQ, "\\input{results}\n")
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW,
                       capsys=capsys)
    got = by_claim(json.loads(out))["T:thm:t"]
    assert got["class"] == "moved" and got["to"] == "results.tex"
    write(proj / "manuscript", "Intro.\n", EQ, THM, THM)
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW,
                       capsys=capsys)
    assert by_claim(json.loads(out))["T:thm:t"]["class"] == "ambiguous"


def test_the_migration_reads_a_vendored_manuscript_at_its_recorded_revision(vendored,
                                                                           capsys):
    proj = vendored
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    eq = inv["claims"][0]
    text = (proj / "manuscript" / "paper.tex").read_text(encoding="utf-8")
    first = text.split("\n")[int(eq["location"].rsplit(":", 1)[1]) - 1]
    eq["source_sha256"] = hashlib.sha256(" ".join(first.split()).encode()).hexdigest()
    for k in ("source_hash_scheme", "source_line_sha256"):
        del eq[k]
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    code, out, err = run(source_regions.main, proj, "--write", capsys=capsys)
    assert code == 0, out + err
    assert json.loads(out)["changes"][0]["claim"] == "T:eq:q"
    migrated = json.loads((proj / "claims.json").read_text(encoding="utf-8"))["claims"][0]
    assert migrated["source_hash_scheme"] == SCHEME
    # Without a recorded revision the command says how to name it.
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    del inv["papers"]
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    code, _, err = run(source_regions.main, proj, capsys=capsys)
    assert code == 2 and "--rev" in err


def test_environment_pins_are_read_as_the_compiled_paper_reads_them():
    """The toy paper's inventory mixes environment pins (made from the compiled paper's
    anchors) and line pins: every one is verified at its revision, and a repin onto the same
    text leaves each unchanged."""
    from pathlib import Path
    toy = Path(__file__).resolve().parents[2] / "examples" / "toy-paper"
    inv = json.loads((toy / "claims.json").read_text(encoding="utf-8"))
    _, plan = repin.repin_plan(inv, "T", toy / "paper", toy / "paper", OLD, NEW)
    classes = {e["claim"]: e["class"] for e in plan["claims"]}
    assert set(classes) == {c["id"] for c in inv["claims"]}
    assert set(classes.values()) == {"unchanged"}, classes


def test_a_folder_whose_configuration_records_its_revision(vendored, capsys):
    """`source = { path = ..., rev = ... }`: the folder holds that revision, and a repin
    moves the configuration's record with the inventory's."""
    proj = vendored
    toml = proj / "machinechecked.toml"
    toml.write_text(toml.read_text(encoding="utf-8").replace(
        'source = { path = "manuscript" }', f'source = {{ path = "manuscript", rev = "{OLD}" }}'),
        encoding="utf-8")
    inv = json.loads((proj / "claims.json").read_text(encoding="utf-8"))
    del inv["papers"]
    (proj / "claims.json").write_text(json.dumps(inv, indent=1) + "\n", encoding="utf-8")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "revision in the configuration")
    write(proj / "manuscript", "Intro.\nAdded.\n", EQ, THM)
    code, out, err = run(repin.main, proj, "--from-source", "git:HEAD", "--to", NEW,
                         "--write", capsys=capsys)
    assert code == 0, out + err
    assert {e["class"] for e in json.loads(out)["claims"]} == {"moved", "unchanged",
                                                                "unpinned"}
    assert f'rev = "{NEW}"' in toml.read_text(encoding="utf-8")
    assert json.loads((proj / "claims.json").read_text(encoding="utf-8"))["papers"]["T"][
        "commit"] == NEW
