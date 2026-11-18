"""Step 1 says whether a proof step has Lean linked, naming none (#740): `review read` in text and
`--json` (`unit.lean_linked`, `unit.route_linked`) and `review status` for each proof step left to
review. A step with no Lean is judged on the mathematics alone, and its verdict may follow the
lock directly. The site is the synthetic one of `test_read_context.py`; nothing builds Lean."""

import json

import pytest

from prooflens import cli
from test_read_context import UNITS, work  # noqa: F401  (the site, as a fixture)

WHO = ["--as", "human:Step-Reviewer"]
STEP = UNITS["step"]["id"]
LINKED = "Syn.step_bound"
ROUTE = "Syn.other_route"


def run(capsys, *args):
    cli.main(["review", *args, *WHO])
    return capsys.readouterr().out


def link_step(work, links=(), route=()):  # noqa: F811
    """Give the synthetic step these links and this formal route used instead."""
    f = work / "site" / "data" / "claims" / "eq:step.json"
    ch = json.loads(f.read_text())
    ch["step"] = {**ch["step"], "links": [{"name": n} for n in links],
                  "route": {"links": [{"name": n} for n in route], "note": ""} if route else None}
    f.write_text(json.dumps(ch))


@pytest.mark.parametrize("links, route, flags, words", [
    ((), (), (False, False), "No Lean is linked to this step: judge the printed step on the "
                             "mathematics alone. Step 2 has no Lean to show"),
    ((LINKED,), (), (True, False), "Lean is linked as establishing this step: step 2 (`review "
                                   "show`) shows it once your reading is locked."),
    ((), (ROUTE,), (False, True), "No Lean is linked as establishing this step. A different "
                                  "formal route used instead is recorded"),
])
def test_step_1_says_whether_lean_is_linked_and_names_none(work, capsys,  # noqa: F811
                                                           links, route, flags, words):
    link_step(work, links, route)
    doc = json.loads(run(capsys, "read", STEP, "--json"))
    assert (doc["unit"]["lean_linked"], doc["unit"]["route_linked"]) == flags
    text = run(capsys, "read", STEP)
    assert words in text
    for shown in (json.dumps(doc), text):
        assert LINKED not in shown and ROUTE not in shown
    status = json.loads(run(capsys, "status", "--json"))
    assert status["steps"] == [{"unit": STEP, "lean_linked": flags[0],
                                "route_linked": flags[1]}]
    line = run(capsys, "status")
    assert f"proof steps left to review: 1, {int(flags[0])} with Lean linked" in line
    assert f"    {STEP}: " + ("Lean linked" if flags[0] else
                              "no Lean linked, a different formal route recorded" if flags[1]
                              else "no Lean linked") in line
    assert LINKED not in line and ROUTE not in line


def test_other_units_say_nothing_of_it(work, capsys):  # noqa: F811
    doc = json.loads(run(capsys, "read", UNITS["def"]["id"], "--json"))
    assert "lean_linked" not in doc["unit"]
    assert "linked to this step" not in run(capsys, "read", UNITS["link"]["id"])


def test_a_step_with_no_lean_is_decided_after_the_lock(work, capsys, tmp_path):  # noqa: F811
    (tmp_path / "r.md").write_text("The step bounds the norm of every control by one.")
    (tmp_path / "c.md").write_text("No Lean is linked. The bound follows from the definition.")
    run(capsys, "read", STEP)
    run(capsys, "lock", STEP, str(tmp_path / "r.md"))
    assert "verdict recorded" in run(capsys, "decide", STEP, "holds as printed",
                                     str(tmp_path / "c.md"))
