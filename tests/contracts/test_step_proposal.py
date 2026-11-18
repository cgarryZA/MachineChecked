"""A proof step's author's proposed verdict (#678): kept with the step's entry (`proposed`, the
step verdicts, a note and optionally a theorem that is the author's and not checked by Lean),
written apart from the claim records (`data/proposals/<file>`), so that no read or show payload,
and no review page before its verdict, holds it. `review author` and the informed packets show it
after the verdict; it completes no review and changes no status; a review snapshot carries it,
and a bundle, which holds every file from the start, does not. The site is the synthetic one of
`test_read_context.py`; nothing here builds Lean."""

import json
from pathlib import Path

import pytest

from prooflens import bundle as bd
from prooflens import cli
from prooflens import compare as cmp
from prooflens import review_cli as rc
from prooflens import review_snapshot as rs
from prooflens import steps
from test_read_context import UNITS, work  # noqa: F401  (the site, as a fixture)

WHO = "human:Proposal-Reviewer"
STEP = UNITS["step"]["id"]
NOTE = "AUTHOR-PROPOSAL-NOTE: the bound fails when u is not measurable."
THEOREM = "Syn.Acceptance.step_counterexample"
PROPOSED = {"verdict": "false as printed", "note": NOTE, "theorem": THEOREM, "by": "author",
            "source": "inventory"}


def test_a_proposal_is_one_of_the_step_verdicts_and_its_theorem_is_the_author_s():
    assert steps.proposal({"proposed": {k: v for k, v in PROPOSED.items() if k != "source"}},
                          "inventory") == PROPOSED
    for bad in ({"verdict": "faithful"}, {"note": "no verdict"}, "false as printed", None):
        assert steps.proposal({"proposed": bad}, "inventory") is None
    assert steps.proposal({}, "confirmed") is None
    # The inventory's schema offers the same verdicts.
    schema = json.loads((Path(steps.__file__).parent / "data/schema/inventory.schema.json")
                        .read_text())
    assert schema["$defs"]["claim"]["properties"]["proposed"]["properties"]["verdict"]["enum"] \
        == [v for vs in steps.VERDICTS.values() for v in vs]


def test_the_site_writes_a_proposal_apart_from_the_claim_record():
    ch = {"id": "S:eq:step", "step": {"unit": "proof-equation", "review": {}, "proposed": PROPOSED}}
    plain = {"id": "S:thm:main"}
    chunks, files = steps.split_proposals({"eq.json": ch, "thm.json": plain})
    assert chunks["eq.json"]["step"] == {"unit": "proof-equation", "review": {}}
    assert chunks["thm.json"] is plain and ch["step"]["proposed"] == PROPOSED  # not mutated
    assert files == {"eq.json": {"schema": steps.PROPOSAL_SCHEMA, "claim": "S:eq:step",
                                 "unit": "step:S:eq:step", "proposed": PROPOSED}}


@pytest.fixture
def proposed(work):  # noqa: F811
    data = work / "site" / "data"
    (data / "proposals").mkdir()
    (data / "proposals" / "eq:step.json").write_text(json.dumps(
        {"schema": steps.PROPOSAL_SCHEMA, "claim": "S:eq:step", "unit": STEP,
         "proposed": PROPOSED}))
    return work


def step(capsys, *args):
    cli.main(["review", *args, "--as", WHO])
    return capsys.readouterr().out


def nothing_of_it(text: str) -> None:
    for x in (NOTE, THEOREM, "false as printed", "proposed"):
        assert x not in text, f"{x!r} is shown before the verdict"


def test_read_and_show_never_hold_the_proposal_and_the_author_s_step_does(proposed, tmp_path,
                                                                           capsys):
    (tmp_path / "r.md").write_text("For every control the step bounds its norm by one.")
    (tmp_path / "c.md").write_text("No Lean is linked; the printed step follows.")
    (tmp_path / "n.md").write_text("none")
    before = [step(capsys, "read", STEP, "--json"), step(capsys, "read", STEP),
              step(capsys, "read", STEP, "--context", "--json")]
    step(capsys, "lock", STEP, str(tmp_path / "r.md"))
    before += [step(capsys, "show", STEP, "--json"), step(capsys, "show", STEP)]
    for text in before:
        nothing_of_it(text)
    step(capsys, "decide", STEP, "holds as printed", str(tmp_path / "c.md"))
    text = step(capsys, "author", STEP)
    assert (f"The author's proposed verdict on this step, by author: false as printed. {NOTE}\n"
            f"It names {THEOREM} (the author's; Lean does not check it here).") in text
    pk = json.loads(step(capsys, "author", STEP, "--json"))
    assert pk["interpretations"]["proposed"] == PROPOSED
    step(capsys, "submit", STEP, str(tmp_path / "n.md"))
    (r,) = rc.Session(proposed, rc.parse_reviewer(WHO)).work["reports"]
    # The reviewer's verdict is the review; the proposal is not part of it.
    assert r["verdict"]["value"] == "holds as printed" and NOTE not in json.dumps(r)
    # The informed packet of the step's claim gives it; the read stage does not.
    site = cmp.Site(proposed / "site" / "data")
    assert cmp.claim_packet(site, "S:eq:step", "informed")["interpretations"]["proposed"] == \
        PROPOSED
    nothing_of_it(json.dumps(cmp.claim_packet(site, "S:eq:step", "read")))


def test_a_snapshot_carries_it_and_a_bundle_does_not(proposed, tmp_path):
    data = proposed / "site" / "data"
    rs.pack(data, tmp_path / "snap")
    assert (tmp_path / "snap" / "data" / "proposals" / "eq:step.json").is_file()
    site = tmp_path / "site"
    (site / "assets").mkdir(parents=True)
    (site / "assets" / "app.js").write_text("console.log(1)")
    (site / "assets" / "app.css").write_text("body{}")
    (site / "index.html").write_text(
        '<html><head><link rel="stylesheet" href="./assets/app.css">'
        '<script type="module" src="./assets/app.js"></script></head><body></body></html>')
    import shutil
    shutil.copytree(data, site / "data")
    out = bd.bundle(site, tmp_path / "b.html")
    html = (tmp_path / "b.html").read_text()
    assert NOTE not in html and "data/proposals/" not in html
    assert out["omitted"] == ["the authors' proposed verdicts on proof steps, which a review "
                              "shows only after the reviewer's verdict"]
    # The index keeps its content index: only proposals were left out.
    assert '"data/index.json"' in html


from conftest import build, needs_lean, needs_tex  # noqa: E402


@needs_lean
@needs_tex
def test_the_toy_s_step_proposal_reaches_only_the_author_s_step(toy, tmp_path, monkeypatch,
                                                                capsys):
    """A full assessment: the inventory's `proposed` on a step is written apart from the step's
    record, and the review steps show it only at step 3."""
    inv = json.loads((toy / "claims.json").read_text())
    (c,) = [c for c in inv["claims"] if c["id"] == "T:eq:bound-range"]
    c["proposed"] = {"verdict": "false as printed", "note": NOTE, "theorem": THEOREM}
    (toy / "claims.json").write_text(json.dumps(inv, indent=1))
    _, _, cfg = build(toy)
    data = cfg.out_dir / "site" / "data"
    site = cmp.Site(data)
    meta = next(x for x in site.claims if x["id"] == "T:eq:bound-range")
    assert NOTE not in (data / "claims" / meta["file"]).read_text()
    assert NOTE not in (data / "review-queue.json").read_text()
    assert site.proposal("T:eq:bound-range") == {**PROPOSED, "by": None}
    monkeypatch.chdir(toy)
    for name, text in {"r.md": "For every k >= 0 the step bounds n by k n^2.",
                       "c.md": "Read as printed."}.items():
        (tmp_path / name).write_text(text)
    unit = "step:T:eq:bound-range"
    nothing_of_it(step(capsys, "read", unit, "--json") + step(capsys, "read", unit))
    step(capsys, "lock", unit, str(tmp_path / "r.md"))
    nothing_of_it(step(capsys, "show", unit, "--json") + step(capsys, "show", unit))
    step(capsys, "decide", unit, "holds as printed", str(tmp_path / "c.md"))
    assert f"proposed verdict on this step: false as printed. {NOTE}" in step(capsys, "author",
                                                                              unit)
