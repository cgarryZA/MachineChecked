"""A reading's coverage and basis have one set of words (#428): `data/semantic.json`'s. Every
terminal surface words each value as the vocabulary does (the reader's surfaces are checked the
same way by web/tests/coverage.test.mjs), and no source of the engine or the reader writes the
vocabulary's words itself."""

import ast
import json
import re

import pytest

from conftest import ROOT
from prooflens import cli, composition, promote, semantic, simple
from prooflens.status import fields

VOCABULARY = json.loads((ROOT / "engine/python/prooflens/data/semantic.json").read_text())
COVERAGE = ("full", "partial", "changed", "related", "unresolved")
BASIS = ("direct", "reviewed_composition", "checked_bridge")


def words(dimension, key):
    return VOCABULARY[dimension][key]["label"]


def in_text(w):
    return w[0].lower() + w[1:]


def test_the_engine_and_the_reader_name_the_same_values():
    assert simple.COVERAGE == semantic.RELATIONS == COVERAGE
    assert simple.BASIS == semantic.BASIS_KEYS[:3] == BASIS
    reader = (ROOT / "web/src/lib/coverage.js").read_text()
    assert 'export const COVERAGE = ["full", "partial", "changed", "related", "unresolved"];' \
        in reader
    assert 'export const BASIS = ["direct", "reviewed_composition", "checked_bridge"];' in reader


@pytest.mark.parametrize("coverage", COVERAGE)
@pytest.mark.parametrize("basis", BASIS)
def test_every_terminal_surface_uses_the_vocabulary(coverage, basis, capsys):
    both = f"{words('coverage', coverage)}, {in_text(words('basis', basis))}"
    assert semantic.reading_words(coverage, basis) == both
    assert semantic.reading_words(coverage) == words("coverage", coverage)

    # A links-file reading in the terminal (`check`, the review's author stage).
    bridge = {"theorem": "A.b", "target": "A.Spec.b", "state": "checked", "reasons": []}
    cor = {"coverage": coverage, "basis": basis, "note": "",
           "bridge": bridge if basis == "checked_bridge" else None}
    assert simple.reading_text(cor).split("\n")[0] == both
    for state in ("stale", "unchecked"):
        if basis == "checked_bridge":
            got = simple.reading_text({**cor, "bridge": {**bridge, "state": state}})
            assert got.split("\n")[0] == \
                f"{words('coverage', coverage)}, {in_text(words('bridge', state))}"

    # The maintainer's plan of `review promote`.
    assert promote.coverage_text({"correspondence": {"coverage": coverage, "basis": basis}}) == \
        in_text(both)

    # A composition: the auditor's argument, or a bridge Lean checks.
    if basis != "direct":
        c = {"id": "c1", "coverage": coverage, "basis": basis, "currency": {"state": "current"},
             "steps": [], "gaps": {"uncovered": []}}
        assert composition.lines(c)[0] == f"  composition c1: {in_text(both)}"

    # `check`'s line for a reading by an argument combining Lean results.
    if basis == "reviewed_composition":
        cli._print_simple({"claims": [{"id": "P:x", "number": "Theorem 1",
                                       **fields("link.checked"), "correspondence": {
                                           **cor, "next_step": "Next."}}]})
        assert f"composition Theorem 1: {in_text(both)}, which Lean has not checked." in \
            capsys.readouterr().out


def test_the_summary_uses_the_vocabulary():
    table = {k: 1 for k in COVERAGE}
    assert semantic._counts(table, VOCABULARY["coverage"]) == "; ".join(
        f"{in_text(words('coverage', k))} (1)" for k in COVERAGE)
    assert semantic._counts({k: 1 for k in BASIS}, VOCABULARY["basis"]) == "; ".join(
        f"{in_text(words('basis', k))} (1)" for k in BASIS)


def _labels():
    """The vocabulary's words for each coverage, basis and bridge state that has more than one
    word (a single word such as "Unresolved" is also a value's code)."""
    out = [words("coverage", k) for k in COVERAGE] + [words("basis", k) for k in BASIS] + \
        [words("bridge", k) for k in VOCABULARY["bridge"]]
    return [w for w in out if " " in w]


def _python_strings(path):
    """The string constants of a Python file, docstrings left out, f-strings by their pieces."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and \
                isinstance(body[0].value, ast.Constant):
            docs.add(id(body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def _reader_texts(path):
    """The text of a reader source without its comments."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"<!--.*?-->|/\*.*?\*/", "", text, flags=re.S)
    return [re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines()]


def test_no_source_writes_the_vocabularys_words_itself():
    """A string that starts with a value's words is a second definition of them: every surface
    takes them from the vocabulary (`semantic.reading_words`, `coverage.js`)."""
    labels = [w.lower() for w in _labels()]
    found = []
    for path in sorted((ROOT / "engine/python/prooflens").rglob("*.py")):
        for s in _python_strings(path):
            if any(s.strip().lower().startswith(w) for w in labels):
                found.append(f"{path.relative_to(ROOT)}: {s!r}")
    pattern = re.compile(r"""["'`>{]\s*(%s)""" % "|".join(re.escape(w) for w in labels), re.I)
    for path in sorted((ROOT / "web/src").rglob("*")):
        if path.suffix not in (".js", ".svelte"):
            continue
        for i, line in enumerate(_reader_texts(path), 1):
            if pattern.search(line):
                found.append(f"{path.relative_to(ROOT)}:{i}: {line.strip()}")
    assert found == []
