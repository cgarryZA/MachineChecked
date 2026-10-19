"""The toy paper builds to exactly the statuses its inventory and reviews determine."""

import json

import pytest

from conftest import ROOT, build, edit, findings, needs_lean, needs_tex, status
from prooflens import manifest as mf
from prooflens.schemas import validate

EXPECTED = {
    "T:def:even": "definition: author-reviewed",
    "T:thm:even-add": "formal: accepted",
    "T:thm:triangle": "formal: proved, author-reviewed",
    "T:prop:pred": "refuted as printed; corrected statement proved",
    "T:rem:pred": "out of scope: part-of",
    "T:thm:bound": "formal: proved, review pending",
    "T:cor:even-triangle": "formal: open",
    "T:rem:history": "out of scope: literature",
}


@needs_lean
@needs_tex
def test_statuses_findings_and_schemas(toy):
    index, body, cfg = build(toy)
    assert {c["id"]: c["status"] for c in index["claims"]} == EXPECTED
    assert [f for f in findings(body) if f["tier"] == "violation"] == []
    # The only warning left is the truncated subtraction of the printed (false) claim; the one of
    # the corrected statement is dismissed with a rationale.
    warns = [f for f in findings(body, "totalised")]
    assert {(f["subject"], bool(f.get("dismissed"))) for f in warns} == {
        ("T:prop:pred#0", False), ("T:prop:pred#1", True)}
    validate(json.loads((cfg.out_dir / "evidence" / f"{index['evidence']}.json").read_text()),
             "evidence")
    validate(index, "manifest-index")
    for c in index["claims"]:
        validate(json.loads((cfg.out_dir / "site" / "data" / "claims" / c["file"]).read_text()),
                 "manifest-claim")


@needs_lean
@needs_tex
def test_statement_inspection(toy):
    index, body, _ = build(toy)
    spec = body["lean"]["specs"]["Toy.PaperSpec.thm_bound"]
    # The quantifier prefix is read in order: one constant for every n.
    assert [(b["role"], b["name"]) for b in spec["binders"]] == [("exists", "C"), ("forall", "n")]
    assert spec["conclusion"]["text"] == "Toy.triangle n ≤ C * (n * n)"
    add = body["lean"]["specs"]["Toy.PaperSpec.thm_even_add"]
    assert [b["role"] for b in add["binders"]] == ["forall", "forall", "hypothesis", "hypothesis"]
    assert [b["name"] for b in add["binders"]][2:] == ["h1", "h2"]
    assert add["closure"] == ["Toy.IsEven"]


@needs_lean
@needs_tex
def test_hashes(toy):
    _, body, _ = build(toy)
    spec = body["lean"]["specs"]["Toy.PaperSpec.thm_triangle"]
    # The first half of the legacy hash is the hash of the type `Prop`, shared by every closed
    # proposition.
    assert spec["legacy_hash"].startswith("ed839d34f480cba1")
    assert spec["fingerprint"].startswith("pl-fp-v1:") and len(spec["fingerprint"]) == 9 + 64


@needs_lean
@needs_tex
def test_build_is_reproducible(toy):
    i1, _, _ = build(toy)
    i2, _, _ = build(toy)
    assert i1["evidence"] == i2["evidence"]


@needs_lean
@needs_tex
def test_anchors_locate_every_numbered_claim(toy):
    index, body, _ = build(toy)
    anchors = body["tex"]["T"]["anchors"]
    assert [(a["env"], a["number"], a["label"]) for a in anchors] == [
        ("definition", "1.1", "def:even"), ("theorem", "2.1", "thm:even-add"),
        ("theorem", "2.2", "thm:triangle"), ("proposition", "2.3", "prop:pred"),
        ("remark", "2.4", "rem:pred"), ("theorem", "2.5", "thm:bound"),
        ("corollary", "2.6", "cor:even-triangle"), ("remark", "3.1", "rem:history")]
    for a in anchors:
        assert a["begin"][0] == 1 and a["head"][2] > a["begin"][2] - 1
    assert all(c["anchor"] for c in index["claims"])


def test_status_classes_are_total():
    for s in ["formal: accepted", "formal: proved, author-reviewed", "formal: open",
              "refuted as printed; other clauses open", "definition: review pending",
              "out of scope: literature", "formal: unspecified", "formal: malformed"]:
        assert mf.status_class(s) in {"accepted", "proved", "refuted", "open", "malformed",
                                      "out-of-scope", "unspecified"}


@needs_lean
@needs_tex
def test_replay_is_not_run_without_a_log_and_blockers_explain(toy):
    import json
    index, body, cfg = build(toy)
    acc = next(c for c in index["claims"] if c["id"] == "T:thm:even-add")
    chunk = json.loads((cfg.out_dir / "site" / "data" / "claims" / acc["file"]).read_text())
    rungs = {k: r["state"] for k, r in chunk["clauses"][0]["evidence"].items()}
    assert rungs["exact-statement"] == "pass" and rungs["axioms"] == "pass"
    assert rungs["replay"] == "not-run"
    # Accepted, but the release still lacks an independent replay: that is its only blocker.
    assert chunk["status"] == "formal: accepted"
    assert chunk["blockers"] == ["Independent replay: not recorded (no Comparator record for this release)"]
    bound = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:bound")
    assert "the proposition has no review" in bound["blockers"]
    assert next(c for c in body["assessment"]["claims"] if c["id"] == "T:rem:history")["blockers"] == []


@needs_lean
@needs_tex
def test_declaration_store_is_content_addressed_and_complete(toy, tmp_path):
    import json
    from prooflens import config as cfgmod
    from prooflens.export import export
    from prooflens.manifest import record_key
    index, body, cfg = build(toy)
    export(cfg, tmp_path / "public")
    for site in (cfg.out_dir / "site", tmp_path / "public"):
        data = site / "data"
        idx = json.loads((data / "index.json").read_text())
        seen = 0
        for c in idx["claims"]:
            chunk = json.loads((data / "claims" / c["file"]).read_text())
            for name, key in chunk["decls"].items():
                rec = json.loads((data / "decls" / f"{key}.json").read_text())
                assert rec["name"] == name and record_key(rec) == key
                seen += 1
            names = set()
            for cl in chunk["clauses"]:
                names |= set(((cl.get("statement") or {}).get("closure")) or [])
                names |= set(cl.get("defs") or [])
            assert names <= set(chunk["decls"])
        assert seen


@needs_lean
@needs_tex
def test_bundle_is_one_self_contained_file(toy, tmp_path):
    import json
    import re
    from prooflens.bundle import bundle
    _, _, cfg = build(toy, web_dist=ROOT / "engine" / "python" / "prooflens" / "web")
    if not (cfg.out_dir / "site" / "index.html").exists():
        import pytest
        pytest.skip("web app not built")
    res = bundle(cfg.out_dir / "site", tmp_path / "b.html")
    html = (tmp_path / "b.html").read_text()
    assert res["pdfs"] == 1 and res["files"] > 10
    assert not re.search(r'(src|href)="\./assets/', html)  # nothing left to fetch
    data = json.loads(re.search(r"window.__PROOFLENS__ = (.*?);</script>", html).group(1)
                      .replace("<\\/", "</"))
    assert "data/index.json" in data


@needs_lean
@needs_tex
def test_line_claims_are_located_approximately_and_hand_placement_wins(toy):
    import json
    from prooflens.util import norm_ws, sha256_text
    tex = (toy / "paper/toy.tex").read_text().split("\n")
    line = next(i + 1 for i, l in enumerate(tex) if "T_n = n(n+1)" in l)
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"].append({"id": "T:eq:gauss", "paper": "T", "kind": "equation", "number": "(1)",
                          "title": "", "location": f"toy.tex:{line}",
                          "source_sha256": sha256_text(norm_ws(tex[line - 1])),
                          "scope": "part-of", "scope_note": "T:thm:triangle",
                          "scope_reviewed": True, "clauses": []})
    (toy / "claims.json").write_text(json.dumps(inv))
    (toy / "anchors.json").write_text(json.dumps(
        {"T:rem:history": {"page": 1, "y0": 700, "y1": 720, "note": "test", "by": "me"}}))
    index, body, _ = build(toy)
    eq = next(c for c in index["claims"] if c["id"] == "T:eq:gauss")
    assert eq["anchor"]["kind"] == "approximate" and eq["anchor"]["page"] == 1
    thm = next(c for c in index["claims"] if c["id"] == "T:thm:triangle")
    # The equation sits inside Theorem 2.2's band.
    assert thm["anchor"]["y0"] < eq["anchor"]["y0"] < thm["anchor"]["y1"] + 20
    rem = next(c for c in index["claims"] if c["id"] == "T:rem:history")
    assert rem["anchor"]["kind"] == "manual" and rem["anchor"]["y0"] == 700
    assert not [f for f in body["assessment"]["findings"] if f["code"] == "source-changed"]


@needs_lean
@needs_tex
def test_kernel_replay_needs_a_structured_record_for_this_commit(toy):
    import json
    from prooflens.util import git_head
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=toy, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                    "--allow-empty", "-m", "t"], cwd=toy, check=True)
    commit = git_head(toy / "lean")
    with open(toy / "machinechecked.toml", "a") as f:
        f.write("")
    txt = (toy / "machinechecked.toml").read_text().replace(
        'dismissals = "reviews/dismissals.json"',
        'dismissals = "reviews/dismissals.json"\ncomparator_log = "comparator.json"')
    (toy / "machinechecked.toml").write_text(txt)

    def replay(record):
        (toy / "comparator.json").write_text(record)
        index, body, _ = build(toy)
        c = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
        return c["clauses"][0]["checks"]["replay"]["state"]

    assert replay("Lean default kernel accepts. Toy.Acceptance.thm_even_add " + commit) == \
        "unverified"
    assert replay(json.dumps({"commit": "0" * 40, "replayed": ["Toy.Acceptance.thm_even_add"]})) \
        == "unverified"
    assert replay(json.dumps({"commit": commit, "replayed": ["Toy.Acceptance.thm_even_add_x"]})) \
        == "not-run"
    assert replay(json.dumps({"commit": commit, "replayed": ["Toy.Acceptance.thm_even_add"]})) \
        == "pass"


@needs_lean
@needs_tex
def test_reuse_and_reassess_refuse_changed_inputs(toy, monkeypatch, capsys):
    import json
    import pytest
    from prooflens import cli, config as cfgmod
    from prooflens.pipeline import build as pl_build, reassess
    build(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    pl_build(cfg, reuse_lean=True, log=lambda *a: None)          # nothing changed: reuse is fine
    edit(toy / "lean/Toy/Defs.lean", "/-!", "-- a comment\n/-!")  # any Lean input
    with pytest.raises(RuntimeError, match="Lean inputs changed"):
        pl_build(cfg, reuse_lean=True, log=lambda *a: None)
    # On the command line: one line naming the remedy, no traceback, exit 2 (#104).
    monkeypatch.chdir(toy)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--reuse-lean"])
    err = capsys.readouterr().err
    assert e.value.code == 2 and "Traceback" not in err and "unexpected" not in err
    assert err.strip().splitlines() == [
        "machinechecked: Lean inputs changed since the stored Lean results (here or in a path "
        "dependency); run `machinechecked build` without `--reuse-lean`"]
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"][1]["clauses"][0]["accept"] = None
    (toy / "claims.json").write_text(json.dumps(inv))
    with pytest.raises(RuntimeError, match="inventory changed"):
        reassess(cfg, log=lambda *a: None)


@needs_lean
@needs_tex
def test_check_json_lists_each_finding(toy):
    """`check --json` (full assessment) lists each finding, with what it says and the clause it
    concerns, besides the totals it always had."""
    import subprocess
    import sys
    edit(toy / "claims.json", '"witness": "Toy.Acceptance.thm_even_add_hypotheses",\n     "regimes"',
         '"regimes"')
    r = subprocess.run([sys.executable, "-m", "prooflens.cli", "check", "--json"], cwd=toy,
                       capture_output=True, text=True)
    d = json.loads(r.stdout)
    assert isinstance(d["findings"], dict) and d["findings"].get("obligation")
    mine = [f for f in d["finding_details"] if f["subject"] == "T:thm:even-add#0"]
    assert any(f["tier"] == "obligation" and "witness" in f["message"] for f in mine), mine
    assert all({"id", "tier", "code", "subject", "message"} <= set(f) for f in d["finding_details"])


@needs_lean
@needs_tex
def test_a_paper_names_its_published_version(toy, tmp_path):
    """`published` and `note` on [[paper]] reach the reader's data and audit.json, and change no
    status; without them the evidence is as before."""
    from prooflens import config as cfgmod
    from prooflens.export import export
    before, body_before, _ = build(toy, skip_lean=True)
    assert "published" not in body_before["provenance"]["papers"]["T"]
    edit(toy / "machinechecked.toml", 'root = "toy.tex"\n',
         'root = "toy.tex"\npublished = "arXiv:2601.01234v2"\n'
         'note = "This revision corrects Proposition 2.3."\n')
    index, _, cfg = build(toy, skip_lean=True)
    paper = index["papers"][0]
    assert paper["published"] == "arXiv:2601.01234v2"
    assert paper["published_note"] == "This revision corrects Proposition 2.3."
    assert [c["status"] for c in index["claims"]] == [c["status"] for c in before["claims"]]
    export(cfgmod.load(toy / "machinechecked.toml"), tmp_path / "out")
    d = json.loads((tmp_path / "out" / "audit.json").read_text())["papers"][0]
    assert (d["id"], d["version"], d["url"]) == \
        ("arxiv:2601.01234", "v2", "https://arxiv.org/abs/2601.01234v2")
    assert d["note"] == "This revision corrects Proposition 2.3."


@needs_lean
@needs_tex
def test_a_source_problem_stops_the_build_before_lean_runs(toy, monkeypatch):
    from prooflens import pipeline
    from prooflens.sources import SourceError
    edit(toy / "machinechecked.toml", 'root = "toy.tex"\n', "")
    (toy / "paper" / "second.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n")

    def no_probe(*a, **k):
        raise AssertionError("Lean ran before the paper's sources were checked")
    monkeypatch.setattr(pipeline, "run_probe", no_probe)
    with pytest.raises(SourceError, match="several LaTeX roots"):
        build(toy)


@needs_lean
@needs_tex
def test_the_commit_is_the_lean_projects_wherever_the_configuration_is(toy):
    """The configuration is outside any repository; the Lean project is one."""
    import subprocess
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@x", "PATH": __import__("os").environ["PATH"]}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "lean"]):
        subprocess.run(["git", *args], cwd=toy / "lean", check=True, capture_output=True, env=env)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=toy / "lean", capture_output=True,
                          text=True).stdout.strip()
    _, body, _ = build(toy, skip_lean=True)
    assert body["provenance"]["project"]["commit"] == head


def test_the_latest_release_is_the_one_made_last_not_the_newest_file(tmp_path):
    import os
    from prooflens import evidence as ev
    d = tmp_path / "releases"
    d.mkdir()
    for name, created, mtime in (("r-old", "2026-01-01T00:00:00+00:00", 2_000_000_000),
                                 ("r-new", "2026-02-01T00:00:00+00:00", 1_000_000_000)):
        (d / f"{name}.json").write_text(json.dumps({"release": name, "evidence": "x",
                                                    "created": created}))
        os.utime(d / f"{name}.json", (mtime, mtime))
    assert [p.stem for p in ev.releases(tmp_path)] == ["r-old", "r-new"]


@needs_lean
@needs_tex
def test_a_replay_record_counts_only_for_its_commit_environment_and_a_passing_run(toy, tmp_path):
    """`machinechecked replay` runs Comparator (a stand-in script here) on a clean commit and
    writes its record; the assessment counts it for the proofs it names, and refuses a record of a
    failed run, of a dirty tree, or of another Lean version or set of dependencies."""
    import os
    import subprocess
    from prooflens.replay import ReplayError, replay
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "toy"]):
        subprocess.run(["git", *args], cwd=toy, check=True, capture_output=True, env=env)
    edit(toy / "machinechecked.toml", 'dismissals = "reviews/dismissals.json"',
         'dismissals = "reviews/dismissals.json"\ncomparator_log = "replay.json"')
    fake = tmp_path / "comparator"
    fake.write_text("#!/bin/sh\necho checked\n")
    fake.chmod(0o755)
    conf = toy / "comparator.json"
    conf.write_text(json.dumps({"challenge_module": "Toy.PaperSpec",
                                "solution_module": "Toy.Acceptance",
                                "theorem_names": ["Toy.Acceptance.thm_even_add"],
                                "permitted_axioms": ["propext", "Quot.sound", "Classical.choice"]}))
    rec = replay(toy / "lean", conf, toy / "replay.json", comparator=str(fake))
    assert rec["passed"] and rec["replayed"] == ["Toy.Acceptance.thm_even_add"] and not rec["dirty"]

    def state():
        _, body, _ = build(toy)
        c = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
        return c["clauses"][0]["checks"]["replay"]

    assert state()["state"] == "pass"
    for change, why in (({"passed": False}, "did not pass"), ({"dirty": True}, "uncommitted"),
                        ({"toolchain": "leanprover/lean4:v0.0.0"}, "other Lean version"),
                        ({"lake_manifest_sha256": "0" * 64}, "other Lake dependencies")):
        (toy / "replay.json").write_text(json.dumps({**rec, **change}))
        got = state()
        assert got["state"] == "unverified" and why in got["detail"], (change, got)
    # A tree whose Lean inputs differ from the commit is refused before Comparator runs.
    edit(toy / "lean/Toy/Defs.lean", "/-!", "-- changed\n/-!")
    with pytest.raises(ReplayError, match="uncommitted changes"):
        replay(toy / "lean", conf, toy / "replay.json", comparator=str(fake))


@needs_lean
@needs_tex
def test_a_checked_refutation_needs_no_witness(toy):
    """#56: a refutation of S exhibits an instance meeting S's hypotheses, so a refuted clause
    raises no witness obligation; the same statement with only a proof still would."""
    edit(toy / "lean/Toy/PaperSpec.lean", "end Toy.PaperSpec",
         "/-- A printed claim with a hypothesis, false at n = 2. -/\n"
         "def prop_one : Prop := ∀ n : Nat, 0 < n → n = 1\n\nend Toy.PaperSpec")
    edit(toy / "lean/Toy/Acceptance.lean", "end Toy.Acceptance",
         "theorem prop_one : ¬ PaperSpec.prop_one := fun h => absurd (h 2 (by decide)) "
         "(by decide)\n\nend Toy.Acceptance")
    edit(toy / "claims.json", '"spec": "Toy.PaperSpec.prop_pred",\n     "refute": "Toy.Acceptance.prop_pred"',
         '"spec": "Toy.PaperSpec.prop_one",\n     "refute": "Toy.Acceptance.prop_one"')
    index, body, _ = build(toy)
    clause = next(c for c in body["assessment"]["claims"] if c["id"] == "T:prop:pred")["clauses"][0]
    assert clause["state"] == "refuted"
    assert not findings(body, "witness", "T:prop:pred"), findings(body, subject="T:prop:pred")


@needs_lean
@needs_tex
def test_a_committed_replay_record_counts_until_a_lean_input_changes(toy, tmp_path):
    """#58: committing the record makes a new commit, which changes nothing the replay checked;
    the record counts there, and stops counting once a Lean input changes."""
    import os
    import subprocess
    from prooflens.replay import replay
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

    def git(*args):
        subprocess.run(["git", *args], cwd=toy, check=True, capture_output=True, env=env)
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "toy")
    edit(toy / "machinechecked.toml", 'dismissals = "reviews/dismissals.json"',
         'dismissals = "reviews/dismissals.json"\ncomparator_log = "replay.json"')
    fake = tmp_path / "comparator"
    fake.write_text("#!/bin/sh\necho checked\n")
    fake.chmod(0o755)
    conf = toy / "comparator.json"
    conf.write_text(json.dumps({"theorem_names": ["Toy.Acceptance.thm_even_add"]}))
    rec = replay(toy / "lean", conf, toy / "replay.json", comparator=str(fake))
    git("add", "-A")
    git("commit", "-q", "-m", "the replay record")

    def state():
        _, body, _ = build(toy)
        c = next(c for c in body["assessment"]["claims"] if c["id"] == "T:thm:even-add")
        return c["clauses"][0]["checks"]["replay"]

    got = state()
    assert got["state"] == "pass" and f"replayed at commit {rec['commit'][:12]}" in got["detail"]
    edit(toy / "lean/Toy/Defs.lean", "/-!", "-- changed\n/-!")
    git("commit", "-q", "-am", "a Lean change")
    got = state()
    assert got["state"] == "unverified" and "Lean inputs changed" in got["detail"], got


@needs_lean
@needs_tex
def test_a_pinned_pdf_is_source_evidence_for_the_release_gate(toy):
    """#63: a paper published only as a PDF meets the gate's source condition when the PDF is
    pinned by hash and matches, and every claim in scope is found in it; the gate says the
    source is a PDF, and claims are placed as approximate."""
    import shutil
    from prooflens.util import sha256_file
    _, _, cfg = build(toy)
    (toy / "paper-pdf").mkdir()
    shutil.copy(cfg.out_dir / "site/data/papers/T.pdf", toy / "paper-pdf/toy.pdf")
    edit(toy / "machinechecked.toml", 'source = { path = "paper" }\nroot = "toy.tex"',
         'source = { path = "paper-pdf" }\npdf = "toy.pdf"')

    def gate():
        index, body, cfg = build(toy, reuse_lean=True)
        g = body["assessment"]["gates"]["T"]
        return g, [r for r in g["release"]["reasons"] if r.startswith("sources:")], cfg

    g, src, _ = gate()
    assert g["source"] == "pdf" and "approximate" in g["source_note"]
    assert src == ["sources: the paper is a PDF and its hash is not pinned (pdf_sha256 in "
                   "machinechecked.toml), so it is not checked"], src
    edit(toy / "machinechecked.toml", 'pdf = "toy.pdf"',
         f'pdf = "toy.pdf"\npdf_sha256 = "{sha256_file(toy / "paper-pdf/toy.pdf")}"')
    g, src, cfg = gate()
    assert src == [], src            # pinned, matching, every claim in scope found by heading
    chunk = next(json.loads(p.read_text()) for p in (cfg.out_dir / "site/data/claims").iterdir()
                 if p.name.startswith("T_thm_even-add"))
    assert chunk["anchor"]["kind"] == "approximate" and chunk["source_matches"] is None
    edit(toy / "machinechecked.toml", 'pdf_sha256 = "', 'pdf_sha256 = "0')
    _, src, _ = gate()
    assert len(src) == 1 and "differs from the one pinned" in src[0], src
