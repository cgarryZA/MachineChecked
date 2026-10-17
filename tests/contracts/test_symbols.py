"""Symbol links (docs/SYMBOL_LINKS.md): a symbol of a claim's printed statement linked, under a
named person, to a variable of its Lean statement. Display only: a link changes no status, it is
shown as stale when its statement or the printed text changes, and a wrong one is refused."""

import json

import pytest

from conftest import build, needs_lean, needs_tex
from prooflens import cli
from prooflens import config as cfgmod
from prooflens.symbols import SymbolError, add

WHO = "human:A-Referee"
SPEC = "Toy.PaperSpec.thm_even_add"


def chunk(cfg, cid):
    index = json.loads((cfg.out_dir / "site/data/index.json").read_text())
    meta = next(c for c in index["claims"] if c["id"] == cid)
    return index, json.loads((cfg.out_dir / "site/data/claims" / meta["file"]).read_text())


@needs_lean
@needs_tex
def test_a_link_is_shown_as_its_authors_and_changes_no_status(toy, monkeypatch, capsys):
    before, _, cfg = build(toy)
    monkeypatch.chdir(toy)
    cli.main(["symbol", "add", "T:thm:even-add", "a", SPEC, "--var", "a", "--as", WHO])
    cli.main(["symbol", "add", "T:thm:even-add", "b", SPEC, "--type-of", "b", "--as", WHO])
    after, _, cfg = build(toy, reuse_lean=True)
    assert {c["id"]: c["status"] for c in after["claims"]} == \
        {c["id"]: c["status"] for c in before["claims"]}
    _, ch = chunk(cfg, "T:thm:even-add")
    assert ch["symbols"] == [
        {"symbol": {"tex": "a", "occurrence": "all"}, "lean": {"decl": SPEC, "var": 0},
         "by": WHO, "stale": False},
        {"symbol": {"tex": "b", "occurrence": "all"},
         "lean": {"decl": SPEC, "binder": 1, "path": "type"}, "by": WHO, "stale": False}]
    # A link pinned to another statement is stale.
    data = json.loads((toy / "symbols.json").read_text())
    data["links"][0]["pins"]["statement"] = "pl-fp-v1:" + "0" * 64
    (toy / "symbols.json").write_text(json.dumps(data))
    _, _, cfg = build(toy, reuse_lean=True)
    assert [s["stale"] for s in chunk(cfg, "T:thm:even-add")[1]["symbols"]] == [True, False]


@needs_lean
@needs_tex
def test_a_wrong_link_is_refused(toy):
    build(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")
    for args, why in [
        (("T:thm:even-add", "c", SPEC), "does not occur"),          # not in the mathematics
        (("T:thm:even-add", "are", SPEC), "does not occur"),        # prose, not mathematics
        (("T:thm:triangle", "n", SPEC), "not a statement of"),      # another claim's statement
        (("T:thm:even-add", "a", SPEC, "nobody"), "has no binder"),
    ]:
        claim, sym, decl, *var = args
        with pytest.raises(SymbolError, match=why):
            add(cfg, claim, sym, decl, WHO, var=var[0] if var else "a")
    with pytest.raises(SymbolError, match="human:NAME"):
        add(cfg, "T:thm:even-add", "a", SPEC, "someone", var="a")
    assert not (toy / "symbols.json").exists()


@needs_lean
@needs_tex
def test_a_link_made_in_the_local_reader_is_checked_and_shown(toy):
    """#60: the local reader's request goes through the checks of `symbol add`, and the site is
    rewritten with it; removing it takes it off."""
    from prooflens.symbols import from_reader
    _, _, cfg = build(toy)
    req = {"action": "add", "claim": "T:thm:even-add", "tex": "a", "decl": SPEC, "var": "a",
           "by": WHO}
    from_reader(cfg, req)
    assert [s["symbol"]["tex"] for s in chunk(cfg, "T:thm:even-add")[1]["symbols"]] == ["a"]
    with pytest.raises(SymbolError, match="does not occur"):
        from_reader(cfg, {**req, "tex": "z"})
    with pytest.raises(SymbolError, match="unknown action"):
        from_reader(cfg, {**req, "action": "rewrite"})
    from_reader(cfg, {"action": "remove", "claim": "T:thm:even-add", "tex": "a"})
    assert chunk(cfg, "T:thm:even-add")[1]["symbols"] == []
