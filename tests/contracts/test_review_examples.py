"""The examples for cases where a review verdict is easy to get wrong (#667, #674) are one short
reference, `data/review_examples.json`: the review page shows it at step 2 (web/tests checks the
reader reads this file), `review decide --help` names each example, docs/AGENTS.md quotes it, and
each has its worked version under "Difficult cases" in docs/REVIEWING.md. Nothing builds Lean."""

import json
import re

import pytest

from conftest import ROOT
from prooflens import cli

CASES = json.loads((ROOT / "engine/python/prooflens/data/review_examples.json")
                   .read_text(encoding="utf-8"))


def norm(s: str) -> str:
    return " ".join(s.split())


def section(text: str, heading: str) -> str:
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end >= 0 else len(text)]


def test_each_example_is_worked_in_the_review_guide():
    guide = (ROOT / "docs/REVIEWING.md").read_text(encoding="utf-8")
    path, anchor = CASES["guide"].split("#")
    assert path == "docs/REVIEWING.md" and anchor == "difficult-cases"
    assert CASES["url"].endswith("/" + CASES["guide"])
    worked = section(guide, "Difficult cases")
    headings = re.findall(r"^### (.+)$", worked, re.M)
    assert headings == [ex["section"] for ex in CASES["examples"]]
    assert len({ex["id"] for ex in CASES["examples"]}) == len(CASES["examples"])
    # The guide's verdict section points to them.
    assert "[Difficult cases](#difficult-cases)" in section(guide, "What a verdict means")


def test_the_agent_guide_quotes_the_same_reference():
    agents = norm((ROOT / "docs/AGENTS.md").read_text(encoding="utf-8"))
    assert "[Difficult cases](REVIEWING.md#difficult-cases)" in agents
    for ex in CASES["examples"]:
        assert norm(f"**{ex['title']}.** {ex['text']}") in agents, ex["id"]


def test_decide_s_help_names_each_example(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["review", "decide", "--help"])
    assert e.value.code == 0
    text = norm(capsys.readouterr().out)
    assert f"Difficult cases, worked in {CASES['guide']}" in text
    for ex in CASES["examples"]:
        assert f"- {ex['title']}" in text, ex["id"]


def test_the_reader_reads_the_same_file():
    src = (ROOT / "web/src/lib/review.js").read_text(encoding="utf-8")
    assert 'from "../../../engine/python/prooflens/data/review_examples.json"' in src
