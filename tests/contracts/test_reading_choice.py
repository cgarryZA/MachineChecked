"""The reading an auditor chooses for a definition the paper leaves open (#597): a `reading
choice` requirement on the definition's claim, the claims that depend on it by citing it, a
finding due for review when the choice changes (never rewritten), the choice withheld from the
read and compare steps and shown at `review author`, and an equivalence of two readings shown
with its exact statement, pending until Lean checks it and then discharged, moving no verdict.
The build and the paper are those of `test_requirements.py`; nothing here runs Lean."""

import json

import pytest

from prooflens import cli
from prooflens import reading_choice as rcm
from prooflens import workspace as wsp
from test_requirements import WHO, make_build, opened, put, snap_of

DEF = "P:def:sol"  # Definition 3.2, the synthetic paper's definition
CHOICE = {"id": "c-bounded", "kind": "requirement", "claim": "Definition 3.2",
          "local_id": "bounded", "form": "reading choice",
          "text": "what “bounded” means for a solution",
          "readings": [{"id": "uniform", "text": "bounded uniformly in time"},
                       {"id": "eventual", "text": "bounded for all large times"}],
          "chosen": "uniform", "reason": "Lemma 1.1 uses the bound at every time.",
          "equivalence": {"theorem": "Ex.uniform_iff_eventual",
                          "readings": ["uniform", "eventual"]}}
CITE = [{"claim": "Definition 3.2", "choice": "bounded"}]
DEPENDENT = [
    put({"id": "r-bd", "kind": "requirement", "claim": "Lemma 1.1", "local_id": "r1",
         "form": "assumption", "text": "u is a bounded solution", "reading_choices": CITE}),
    put({"id": "f-bd", "kind": "finding", "claim": "Lemma 1.1", "requirement": "r1",
         "coverage": "full", "note": "Lean assumes a uniform bound, as the reading chooses."}),
]


@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    make_build(w)
    return w


def update(work, p, ops):
    return wsp.update(p, ops, snap_of(work), None, WHO["id"])


def view(work, p, root=None):
    return wsp.view(wsp.read(p), snap_of(work), root=root)


def test_a_choice_belongs_to_a_definition_and_chooses_one_of_its_readings(work):
    p = opened(work)
    bad = [({**CHOICE, "claim": "Lemma 1.1"}, "a reading choice belongs to a definition's claim"),
           ({**CHOICE, "chosen": "other"}, "'other' is not one of the readings"),
           ({**CHOICE, "readings": CHOICE["readings"][:1]}, "two or more readings"),
           ({**CHOICE, "reason": ""}, "why that reading is chosen"),
           ({**CHOICE, "equivalence": {"theorem": "Ex.e", "readings": ["uniform"]}},
            "relates two different readings"),
           ({**CHOICE, "form": "condition"}, "`readings` belongs to a requirement of form")]
    for rec, why in bad:
        with pytest.raises(wsp.WorkspaceError, match=why.replace("(", r"\(").replace(")", r"\)")):
            update(work, p, [put(rec)])
    update(work, p, [put(CHOICE)])
    # Only a choice this workspace has can be cited.
    with pytest.raises(wsp.WorkspaceError, match="has no reading choice 'unbounded'"):
        update(work, p, [put({**DEPENDENT[0]["record"],
                              "reading_choices": [{"claim": "Definition 3.2",
                                                   "choice": "unbounded"}]})])


def test_a_dependent_claim_shows_the_link_and_the_choice(work, capsys):
    p = opened(work)
    update(work, p, [put(CHOICE), *DEPENDENT])
    v = view(work, p)
    (c,) = v["reading_choices"]
    assert (c["claim"], c["choice"], c["chosen"]) == (DEF, "bounded", "uniform")
    assert c["dependents"] == [{"claim": "P:lem:bound", "record": "r-bd", "kind": "requirement",
                                "requirement": "r1"}]
    lemma = v["claims"]["P:lem:bound"]
    (r,) = [x for x in lemma["reading"]["requirements"] if x["local_id"] == "r1"]
    assert r["cites"][0]["line"] == (
        "depends on the reading of P:def:sol chosen in bounded: uniform, bounded uniformly in "
        "time; pending Ex.uniform_iff_eventual")
    assert [x["choice"] for x in lemma["reading_choices"]] == ["bounded"]
    assert [x["choice"] for x in v["claims"][DEF]["reading_choices"]] == ["bounded"]
    # The finding on it rests on the choice.
    (f,) = lemma["findings"]
    assert {"dependency": "reading choice", "record": "c-bounded", "claim": DEF,
            "choice": "bounded", "sha256": rcm.digest(wsp.read(p)["records"]["c-bounded"])} \
        in f["dependencies"]["items"]
    lines = rcm.lines(c)
    assert lines[0] == ("  reading choice bounded of P:def:sol (what “bounded” means for a "
                        "solution): uniform, bounded uniformly in time. Reason: Lemma 1.1 uses "
                        "the bound at every time.")
    assert "    not chosen: eventual, bounded for all large times" in lines
    assert "    depended on by P:lem:bound, requirement r1" in lines


def test_a_changed_choice_makes_a_dependent_finding_due_and_rewrites_nothing(work):
    p = opened(work)
    update(work, p, [put(CHOICE), *DEPENDENT])
    rev = wsp.read(p)["records"]["f-bd"]["rev"]
    update(work, p, [{"op": "submit", "id": "f-bd", "base_rev": rev}])
    before = json.dumps(wsp.read(p)["records"]["f-bd"], sort_keys=True)
    assert view(work, p)["claims"]["P:lem:bound"]["findings"][0]["currency"]["state"] == \
        "current"
    # Its reason alone changing leaves the interpretation as it was.
    choice = wsp.read(p)["records"]["c-bounded"]
    update(work, p, [put({**CHOICE, "reason": "A clearer reason."}, choice["rev"])])
    assert view(work, p)["claims"]["P:lem:bound"]["findings"][0]["currency"]["state"] == \
        "current"
    choice = wsp.read(p)["records"]["c-bounded"]
    update(work, p, [put({**CHOICE, "chosen": "eventual"}, choice["rev"])])
    f = view(work, p)["claims"]["P:lem:bound"]["findings"][0]
    assert f["currency"]["state"] == "stale"
    assert any("the reading choice c-bounded" in (ch.get("reason") or "")
               for ch in f["currency"]["changes"])
    assert json.dumps(wsp.read(p)["records"]["f-bd"], sort_keys=True) == before


def test_a_finding_may_cite_the_choice_itself(work):
    p = opened(work)
    update(work, p, [put(CHOICE), put({"id": "f-own", "kind": "finding", "claim": "Lemma 1.1",
                                       "coverage": "partial", "reading_choices": CITE,
                                       "note": "Only under the uniform reading."})])
    (f,) = view(work, p)["claims"]["P:lem:bound"]["findings"]
    assert f["cites"][0]["line"].startswith("depends on the reading of P:def:sol chosen in "
                                            "bounded")
    assert view(work, p)["reading_choices"][0]["dependents"] == [
        {"claim": "P:lem:bound", "record": "f-own", "kind": "finding"}]


@pytest.mark.parametrize("record, state, reason", [
    ({"kind": "theorem", "sorry": False, "errors": [],
      "statement": {"exact": {"text": "∀ u, Uniform u ↔ Eventual u"}}}, "discharged", None),
    ({"kind": "theorem", "sorry": True, "errors": []}, "pending",
     "the proof of Ex.uniform_iff_eventual uses sorry"),
    ({"kind": "theorem", "sorry": False, "errors": ["axioms=sorryAx"]}, "pending",
     "Ex.uniform_iff_eventual fails a check: axioms=sorryAx"),
    ({"kind": "def", "sorry": False, "errors": []}, "pending",
     "Ex.uniform_iff_eventual is not a theorem"),
    (None, "pending", "Ex.uniform_iff_eventual is not in the Lean project"),
])
def test_an_equivalence_is_pending_until_lean_checks_it(monkeypatch, tmp_path, record, state,
                                                         reason):
    monkeypatch.setattr(rcm, "check", lambda root, theorem, cached_only=True: {
        "status": "checked" if record else "not found", "record": record,
        **({} if record else {"reason": f"{theorem} is not in the Lean project"})})
    eq = rcm.equivalence(CHOICE["equivalence"], tmp_path)
    assert (eq["state"], eq.get("reason")) == (state, reason)
    line = rcm.equivalence_line(eq)
    if state == "discharged":
        assert line == ("equivalence of readings uniform and eventual: discharged by "
                        "Ex.uniform_iff_eventual; it states: ∀ u, Uniform u ↔ Eventual u. No "
                        "verdict moves between the readings: what it justifies is what it states.")
    else:
        assert line.startswith("equivalence of readings uniform and eventual: pending "
                               "Ex.uniform_iff_eventual")
    # Without a Lean project it is pending, never discharged.
    assert rcm.equivalence(CHOICE["equivalence"], None)["state"] == "pending"


def test_workspace_show_prints_the_choice_and_the_dependence(work, monkeypatch, capsys):
    p = opened(work)
    update(work, p, [put(CHOICE), *DEPENDENT])
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, None))
    cli.main(["workspace", "show", "--as", WHO["id"]])
    out = capsys.readouterr().out
    assert "      depends on the reading of P:def:sol chosen in bounded: uniform" in out
    assert "  reading choices:" in out
    assert "    reading choice bounded of P:def:sol" in out
    assert ("      equivalence of readings uniform and eventual: pending "
            "Ex.uniform_iff_eventual") in out


def test_check_lists_each_choice_with_its_dependents_and_equivalence(work):
    p = opened(work)
    update(work, p, [put(CHOICE), *DEPENDENT])
    (c,) = cli._reading_choices(work, None)
    assert c["workspace"] == wsp.read(p)["id"]
    assert c["equivalence"]["state"] == "pending"
    lines = cli._reading_choice_lines([c])
    assert lines[0] == f"note: workspace {c['workspace']} records a reading choice:"
    assert lines[1].startswith("  reading choice bounded of P:def:sol")
    assert "    depended on by P:lem:bound, requirement r1" in lines
    assert any(x.startswith("    equivalence of readings uniform and eventual: pending "
                            "Ex.uniform_iff_eventual") for x in lines)
