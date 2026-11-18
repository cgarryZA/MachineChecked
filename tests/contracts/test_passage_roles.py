"""The passages of a definition unit say which define the notion and which only use it (#626):
each passage of `review read --json` has a role, `defines` or `uses`, the defining first; the
plain text prints the defining passages in full, then the uses abbreviated (in full with
`--full`). The site is the synthetic one of `test_read_context.py`; nothing builds Lean."""

import json

from prooflens import cli
from prooflens import compare as cmp
from test_read_context import UNITS, work  # noqa: F401  (the site, as a fixture)

WHO = ["--as", "human:Role-Reviewer"]
DEF = UNITS["def"]["id"]
LONG = "Every control of linear growth satisfies the bound. " * 20


def as_definition_unit(work, mapped=True):  # noqa: F811
    """The definition's claim mapped to `Syn.Control` in the inventory (`defs`), and the unit's
    passages those of every claim that names it, the definition's last."""
    data = work / "site" / "data"
    f = data / "claims" / "def:control.json"
    ch = json.loads(f.read_text())
    ch.update(scope="definition", clauses=[{"name": "main", "defs": ["Syn.Control"]}]
              if mapped else [])
    f.write_text(json.dumps(ch))
    g = data / "claims" / "cor:growth.json"
    cor = json.loads(g.read_text())
    cor["statement_tex"] = LONG
    g.write_text(json.dumps(cor))
    q = data / "review-queue.json"
    queue = json.loads(q.read_text())
    unit = next(u for u in queue["units"] if u["id"] == DEF)
    unit["claims"] = [{"id": "S:thm:main"}, {"id": "S:cor:growth"}, {"id": "S:def:control"}]
    q.write_text(json.dumps(queue))


def read(capsys, *args):
    cli.main(["review", "read", DEF, *args, *WHO])
    return capsys.readouterr().out


def test_each_passage_has_its_role_and_the_defining_one_comes_first(work, capsys):  # noqa: F811
    as_definition_unit(work)
    doc = json.loads(read(capsys, "--json"))
    assert [(p["claim"], p["role"]) for p in doc["paper"]["passages"]] == [
        ("S:def:control", "defines"), ("S:thm:main", "uses"), ("S:cor:growth", "uses")]
    text = read(capsys)
    assert text.startswith("a definition used by 3 claim(s); every one of their passages is "
                           "included\n\nPassages that define it (1):\n\nDefinition 1.1")
    assert ("Passages that use it (2), each abbreviated: `review read UNIT --full` prints them in "
            "full, and `--json` gives each whole:") in text
    assert text.index("Definition 1.1") < text.index("Theorem 2.1") < text.index("Corollary 2.2")
    # A long use is cut, and says so; a short one is whole.
    assert LONG not in text and LONG[:cmp.USE_CHARS].rstrip() + " …" in text
    assert f"(abbreviated: {len(LONG)} characters)" in text
    assert "Every control satisfies" in text
    # In full on request.
    full = read(capsys, "--full")
    assert LONG in full and "abbreviated" not in full


def test_with_no_mapped_definition_every_passage_only_uses_it(work, capsys):  # noqa: F811
    as_definition_unit(work, mapped=False)
    doc = json.loads(read(capsys, "--json"))
    assert {p["role"] for p in doc["paper"]["passages"]} == {"uses"}
    assert "\n\nNo passage is recorded as defining it" in read(capsys)


def test_other_units_have_no_roles(work, capsys):  # noqa: F811
    cli.main(["review", "read", UNITS["link"]["id"], "--json", *WHO])
    doc = json.loads(capsys.readouterr().out)
    assert all("role" not in p for p in doc["paper"]["passages"])
