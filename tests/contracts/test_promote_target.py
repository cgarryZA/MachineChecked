"""Where `review promote` writes a marker (#609): after the declaration's last marker; a first
marker at the end of the file `[review.promote]` names for its kind, else of the review file
named `definitions.md` (a definition) or `<paper id>.md` (a proposition or a proof step), else of
the last review file. The plan names each marker's file and place before it asks. Every report
and project here is synthetic; nothing builds Lean."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from prooflens import cli
from prooflens import config as cfgmod
from prooflens import promote as pr
from prooflens.reviews import load_reviews
from test_structure_unit import S, body, hexes, unit
from test_structure_unit import report as structure_report

WHO = "human:Target-Referee"
SPEC = "Toy.PaperSpec.thm_new"
CONFIG = """[project]
name = "toy"
modules = ["Toy"]
scope_roots = ["Toy"]
spec_prefix = "Toy.PaperSpec"
accept_prefix = "Toy.Acceptance"
inventory = "claims.json"
reviews = {reviews}
{extra}"""


def report(kind: str, name: str, paper: str = "T") -> dict:
    uid = f"step:{name}" if kind == "step" else f"{kind}:{name}"
    return {"unit": {"id": uid, "kind": kind, "name": name, "claims": [], "papers": [paper]},
            "pins": {"source_sha256": None}, "reviewer": {"id": WHO, "kind": "human"},
            "reading": {"text": "r", "locked_at": "t0"},
            "comparison": {"text": "c", "decided_at": "t1"}, "author_review": {"shown_at": "t2"},
            "verdict": {"value": "holds as printed" if kind == "step" else "faithful"},
            "submitted_at": "2026-01-01T10:06:00Z"}


def cur(kind: str) -> dict:
    return {"source_sha256": "b" * 64} if kind == "step" else {"legacy_hash": "a" * 32}


def files(root: Path, *names: str) -> list[Path]:
    (root / "reviews").mkdir(exist_ok=True)
    out = []
    for n in names:
        (root / "reviews" / n).write_text(f"# {n}\n", encoding="utf-8")
        out.append(root / "reviews" / n)
    return out


def project(root: Path, reviews: list[str], promote: str = "") -> cfgmod.Config:
    (root / "machinechecked.toml").write_text(
        CONFIG.format(reviews=str(reviews).replace("'", '"'), extra=promote), encoding="utf-8")
    return cfgmod.load(root / "machinechecked.toml")


def written(cfg, kind: str, name: str) -> str:
    """The file, relative to the project, of the last marker of `name`."""
    reviews, _ = load_reviews(cfg.reviews, [], cfg.root)
    return [r for r in reviews if r.target == kind and r.name == name][-1].file


def test_without_configuration_a_first_marker_goes_by_the_file_names(tmp_path):
    """The issue's example: statements.md and definitions.md listed, in that order. A
    proposition's first marker goes to the last file, as no file is named after its paper; a
    third file listed last then takes it, and definitions still go to definitions.md."""
    statements, definitions = files(tmp_path, "statements.md", "definitions.md")
    cfg = SimpleNamespace(reviews=[statements, definitions], ai_reviewers=[], root=tmp_path)
    assert pr.first_marker_file(cfg, report("spec", SPEC)["unit"]) == (
        definitions, "the last review file, as none is named T.md")
    assert pr.first_marker_file(cfg, report("def", "Toy.d")["unit"]) == (
        definitions, "the review file named definitions.md")
    (third,) = files(tmp_path, "notes.md")
    cfg.reviews.append(third)
    pr.apply(cfg, [(report("spec", SPEC), cur("spec")), (report("def", "Toy.d"), cur("def"))])
    assert written(cfg, "spec", SPEC) == "reviews/notes.md"
    assert written(cfg, "def", "Toy.d") == "reviews/definitions.md"
    # A file named after the paper takes the paper's propositions and steps.
    (paper,) = files(tmp_path, "T.md")
    cfg.reviews.append(paper)
    pr.apply(cfg, [(report("step", "T:eq:one"), cur("step"))])
    assert written(cfg, "step", "T:eq:one") == "reviews/T.md"


def test_the_configuration_names_the_file_of_each_kind(tmp_path):
    files(tmp_path, "statements.md", "definitions.md")
    cfg = project(tmp_path, ["reviews/statements.md", "reviews/definitions.md", "reviews/steps"],
                  '[review.promote]\nspec = "reviews/statements.md"\n'
                  'step = "reviews/steps/proof-steps.md"\n')
    new = tmp_path / "reviews" / "steps" / "proof-steps.md"
    assert cfg.review_promote == {"spec": tmp_path / "reviews" / "statements.md", "step": new}
    steps = [(report("spec", SPEC), cur("spec")), (report("def", "Toy.d"), cur("def")),
             (report("step", "T:eq:one"), cur("step"))]
    # The plan says where each marker goes, before anything is written; proof-steps.md, in a
    # directory `reviews` lists, is new.
    plan = [p for r, c in steps for p in pr.places(cfg, r, c)]
    assert [(p["file"].name, p["how"]) for p in plan] == [
        ("statements.md", "at the end, its first marker ([review.promote] spec)"),
        ("definitions.md", "at the end, its first marker (the review file named "
                           "definitions.md)"),
        ("proof-steps.md", "at the end, its first marker ([review.promote] step); a new file")]
    assert not new.exists()
    done = pr.apply(cfg, steps)
    assert [Path(d["file"]) for d in done] == [p["file"] for p in plan]
    assert written(cfg, "spec", SPEC) == "reviews/statements.md"
    assert written(cfg, "def", "Toy.d") == "reviews/definitions.md"
    assert written(cfg, "step", "T:eq:one") == "reviews/steps/proof-steps.md"
    # The marker in the new file is a reading: the line that links its report.
    reviews, _ = load_reviews(cfg.reviews, [], cfg.root)
    (step,) = [r for r in reviews if r.target == "step"]
    assert step.text.startswith(f"Review by {WHO}: holds as printed (report `")
    # A later marker of the same declaration goes after its last one, wherever that is.
    (tmp_path / "reviews" / "definitions.md").write_text(
        "# Definitions\n\nMoved here.\n\n" + (tmp_path / "reviews" / "statements.md")
        .read_text(encoding="utf-8").split("\n", 1)[1], encoding="utf-8")
    (tmp_path / "reviews" / "statements.md").write_text("# Statements\n", encoding="utf-8")
    again = {**report("spec", SPEC), "submitted_at": "2026-01-02T10:06:00Z"}
    (p,) = pr.places(cfg, again, {"legacy_hash": "c" * 32})
    assert p["file"].name == "definitions.md" and p["how"].startswith("after its last marker")


def test_a_structure_s_members_follow_its_marker(tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "definitions.md").write_text("# Definitions\n", encoding="utf-8")
    cfg = SimpleNamespace(reviews=[tmp_path / "reviews"], ai_reviewers=[], root=tmp_path)
    r, b = structure_report(unit()), body()
    got = pr.places(cfg, r, pr.with_covers(r, b["lean"]["decls"][S], b))
    assert [p["how"] for p in got] == [
        "at the end, its first marker (the review file named definitions.md)",
        f"after the marker of {S}", f"after the marker of {S}.mk", f"after the marker of {S}.x"]
    assert {p["file"] for p in got} == {tmp_path / "reviews" / "definitions.md"}
    assert got[0]["marker"].startswith(f"<!-- def-review: {S} {hexes(S)} ")


@pytest.mark.parametrize("promote,why", [
    ('[review.promote]\nproposition = "reviews/a.md"\n', "takes spec, def, step, not proposition"),
    ('[review.promote]\nspec = 3\n', "spec must be the path of a review file"),
    ('[review]\npromote = "reviews/a.md"\n', "[review] promote is a table"),
    ('[review.promote]\nspec = "elsewhere.md"\n', "'elsewhere.md' is neither"),
    ('[review.promote]\ndef = "reviews/d/defs.txt"\n', "'reviews/d/defs.txt' is neither"),
])
def test_a_file_the_assessment_would_not_read_is_refused(tmp_path, promote, why):
    """A first marker written where `reviews` does not reach would be read by no assessment."""
    files(tmp_path, "a.md")
    with pytest.raises(cfgmod.ConfigError) as e:
        project(tmp_path, ["reviews/a.md", "reviews/d"], promote)
    assert why in str(e.value)
    cfg = project(tmp_path, ["reviews/a.md", "reviews/d"],
                  '[review.promote]\ndef = "reviews/d/defs.md"\n')
    assert cfg.review_promote == {"def": tmp_path / "reviews" / "d" / "defs.md"}


def test_the_plan_names_each_marker_s_file_before_it_asks(tmp_path, monkeypatch, capsys):
    files(tmp_path, "statements.md", "definitions.md")
    cfg = project(tmp_path, ["reviews/statements.md", "reviews/definitions.md"],
                  '[review.promote]\nspec = "reviews/statements.md"\n')
    before = {p.name: p.read_text(encoding="utf-8") for p in (tmp_path / "reviews").iterdir()}
    monkeypatch.setattr(cli, "_load_full", lambda a: cfg)
    monkeypatch.setattr(pr, "load_reports", lambda paths: [report("spec", SPEC)])
    monkeypatch.setattr(pr, "plan", lambda c, rs, *a: [(r, cur("spec"), []) for r in rs])
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "promote", "reports.json"])
    out, err = capsys.readouterr()
    assert e.value.code == 2 and "pass --yes to write the markers" in err
    assert f"<!-- spec-review: {SPEC} {'a' * 32} by={WHO} -->\n" \
        "             to reviews/statements.md, at the end, its first marker ([review.promote] " \
        "spec)\n" in out
    assert {p.name: p.read_text(encoding="utf-8")
            for p in (tmp_path / "reviews").iterdir()} == before


def test_the_guide_s_example_is_a_configuration_the_engine_accepts(tmp_path):
    import re
    import tomllib
    text = (Path(__file__).resolve().parents[2] / "docs" / "ASSURANCE.md").read_text()
    (block,) = [b for b in re.findall(r"```toml\n(.*?)```", text, re.S) if "[review.promote]" in b]
    example = tomllib.loads(block)
    cfg = project(tmp_path, example["project"]["reviews"],
                  "[review.promote]\n" + "".join(f'{k} = "{v}"\n' for k, v in
                                                example["review"]["promote"].items()))
    assert set(cfg.review_promote) == {"spec", "def", "step"}
