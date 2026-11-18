"""`review show UNIT --definitions --fold` (#738): of the definitions a unit's Lean uses, one
line for each this workspace records as shown unchanged with another unit (`shown_definitions`,
on the draft and on the report), and in full each one changed since or never shown. The full
listing stays one call away, and folding records nothing as read, reviewed or accepted. The site
is synthetic; nothing here builds Lean."""

import hashlib
import json
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import review_cli as rc
from test_compare import seg, statement

WHO = "human:Fold-Reviewer"
A, B, C = "link:thm:a", "link:thm:b", "link:thm:c"
DEFS = {
    "Syn.Grid": ("Nat → Nat", "fun n => 2 * n", "The grid points.", []),
    "Syn.Step": ("Nat → Nat", "fun n => n + 1", "The time step.", []),
    "Syn.Incr": ("Nat → Nat", "fun n => Syn.Step n - n", "The increments.", ["Syn.Step"]),
}
# Which definitions each unit's statement uses.
USES = {A: ["Syn.Grid", "Syn.Step"], B: ["Syn.Grid", "Syn.Incr"], C: ["Syn.Step"]}


def key(n):
    return hashlib.sha256(n.encode()).hexdigest()[:24]


def write_site(tmp: Path, fingerprints: dict | None = None) -> Path:
    work = tmp / "proj" / ".machinechecked"
    data = work / "site" / "data"
    (data / "claims").mkdir(parents=True, exist_ok=True)
    (data / "decls").mkdir(exist_ok=True)
    for n, (ty, value, doc, uses) in DEFS.items():
        (data / "decls" / f"{key(n)}.json").write_text(json.dumps(
            {"name": n, "kind": "def", "module": "Syn.Defs", "signature": seg(ty),
             "value": seg(value, uses), "uses": uses, "doc": doc,
             "fingerprint": (fingerprints or {}).get(n, f"fp-{n}")}))
    claims, units = [], []
    for i, (uid, uses) in enumerate(USES.items()):
        cid, name = f"S:thm:{uid[-1]}", f"Syn.thm_{uid[-1]}"
        link = {"name": name, "kind": "theorem", "module": "Syn.Main", "source": "confirmed",
                "fingerprint": f"fp-{name}", "status": "linked: Lean proof checked",
                "status_code": "link.checked",
                "statement": statement(" ∧ ".join(f"{u} n = n" for u in uses), uses, uses)}
        ch = {"id": cid, "key": cid[2:], "paper": "S", "number": f"Theorem {i + 1}",
              "kind": "theorem", "heading": None, "location": "main.tex",
              "anchor": {"kind": "exact", "file": "main.tex", "line": 10 + i},
              "statement_tex": f"Statement {i + 1} on the grid.", "source_sha256": f"sha{i}",
              "status": "linked: Lean proof checked", "status_code": "link.checked",
              "links": [link], "suggestions": [], "clauses": [], "findings": [],
              "decls": {u: key(u) for u in uses}, "symbols": [], "reviews": []}
        (data / "claims" / f"{cid[2:]}.json").write_text(json.dumps(ch))
        claims.append({"id": cid, "paper": "S", "number": ch["number"],
                       "file": f"{cid[2:]}.json", "kind": "theorem"})
        units.append({"id": uid, "kind": "link", "name": name, "lean": [name],
                      "fingerprints": {name: f"fp-{name}"}, "papers": ["S"],
                      "claims": [{"id": cid}], "state": "pending", "reason": "Short"})
    (data / "index.json").write_text(json.dumps({
        "schema": "prooflens/manifest@1", "mode": "simple", "release": "v-fold",
        "project": {"name": "syn"}, "papers": [{"id": "S", "title": "Synthetic"}],
        "claims": claims}))
    (data / "review-queue.json").write_text(json.dumps({
        "schema": "prooflens/review-queue@1", "release": "v-fold", "mode": "simple",
        "units": units}))
    return work


@pytest.fixture
def work(tmp_path, monkeypatch):
    w = write_site(tmp_path)
    monkeypatch.setattr(cli, "_built_work", lambda a: (w, w.parent))
    for name, text in {"r.md": "Each statement holds at every point of the grid.",
                       "c.md": "The Lean states it at every grid point.",
                       "n.md": "none"}.items():
        (tmp_path / name).write_text(text)
    monkeypatch.chdir(tmp_path)
    return w


def run(capsys, *args):
    cli.main(["review", *args, "--as", WHO])
    return capsys.readouterr().out


def to_step_2(capsys, uid):
    run(capsys, "read", uid)
    run(capsys, "lock", uid, "r.md")
    return run(capsys, "show", uid, "--definitions")


def full(name, used_by=None):
    ty, value, doc, _ = DEFS[name]
    head = f"{name}  (def; unit def:{name})" + (f", used by {used_by}" if used_by else "")
    return f"{head}\n  doc: {doc}\n  type: {ty}\n  value: {value}"


def test_a_definition_shown_unchanged_with_another_unit_is_one_line(work, capsys):
    first = to_step_2(capsys, A)
    assert full("Syn.Grid") in first and full("Syn.Step") in first
    # The draft records the definitions shown, at their fingerprints.
    d = rc.Session(work, rc.parse_reviewer(WHO)).work["drafts"][A]
    assert d["shown_definitions"] == {"Syn.Grid": "fp-Syn.Grid", "Syn.Step": "fp-Syn.Step"}
    to_step_2(capsys, B)
    folded = run(capsys, "show", B, "--definitions", "--fold")
    assert ("Syn.Grid  (def; unit def:Syn.Grid): shown to you with link:thm:a, unchanged since"
            in folded)
    # The time step, which the increments use, was shown with the first unit too.
    assert ("Syn.Step  (def; unit def:Syn.Step), used by Syn.Incr: shown to you with "
            "link:thm:a, unchanged since") in folded
    assert "fun n => 2 * n" not in folded and "fun n => n + 1" not in folded
    # Unseen before: in full.
    assert full("Syn.Incr") in folded
    assert ("2 definition(s) folded: each was shown to you unchanged with another unit. `review "
            "show link:thm:b --definitions` lists them in full. Folding is a display only") \
        in folded
    # The complete listing is one call away, and the same as before.
    plain = run(capsys, "show", B, "--definitions")
    assert full("Syn.Grid") in plain and "folded" not in plain


def test_a_report_keeps_what_was_shown_and_a_unit_never_folds_its_own(work, capsys):
    to_step_2(capsys, A)
    run(capsys, "decide", A, "faithful", "c.md")
    run(capsys, "author", A)
    run(capsys, "submit", A, "n.md")
    (r,) = rc.Session(work, rc.parse_reviewer(WHO)).work["reports"]
    assert r["shown_definitions"] == {"Syn.Grid": "fp-Syn.Grid", "Syn.Step": "fp-Syn.Step"}
    to_step_2(capsys, C)
    assert "Syn.Step  (def; unit def:Syn.Step): shown to you with link:thm:a" in run(
        capsys, "show", C, "--definitions", "--fold")
    # Undo keeps the record.
    s = rc.Session(work, rc.parse_reviewer(WHO))
    assert s.undo()["shown_definitions"] == r["shown_definitions"]


def test_a_definition_changed_since_is_printed_in_full(work, capsys, tmp_path):
    to_step_2(capsys, A)
    write_site(tmp_path, {"Syn.Grid": "fp-changed"})
    to_step_2(capsys, B)
    text = run(capsys, "show", B, "--definitions", "--fold")
    assert ("Syn.Grid  (def; unit def:Syn.Grid); changed since it was shown to you with "
            "link:thm:a") in text
    assert full("Syn.Grid").split("\n", 1)[1] in text
    assert "1 definition(s) folded" in text  # the time step, unchanged


def test_a_unit_s_own_earlier_showing_folds_nothing(work, capsys):
    to_step_2(capsys, C)
    text = run(capsys, "show", C, "--definitions", "--fold")
    assert full("Syn.Step") in text and "folded" not in text


def test_folding_records_nothing_and_needs_the_definitions_listing(work, capsys):
    to_step_2(capsys, A)
    to_step_2(capsys, B)
    before = json.dumps(rc.Session(work, rc.parse_reviewer(WHO)).work, sort_keys=True)
    run(capsys, "show", B, "--definitions", "--fold")
    after = json.dumps(rc.Session(work, rc.parse_reviewer(WHO)).work, sort_keys=True)
    assert before == after
    for args in (["show", B, "--fold"], ["show", B, "--definitions", "--fold", "--json"]):
        with pytest.raises(SystemExit):
            cli.main(["review", *args, "--as", WHO])
        assert "--fold folds the listing" in capsys.readouterr().err
