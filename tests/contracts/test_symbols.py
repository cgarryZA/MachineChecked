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
         "by": WHO, "stale": False, "stale_because": []},
        {"symbol": {"tex": "b", "occurrence": "all"},
         "lean": {"decl": SPEC, "binder": 1, "path": "type"}, "by": WHO, "stale": False,
         "stale_because": []}]
    # Both are made on the passage the reader typesets, and pinned to its context.
    data = json.loads((toy / "symbols.json").read_text())
    assert [ln["pins"]["excerpt"] for ln in data["links"]] == [ch["excerpt"]["fingerprint"]] * 2
    # A link pinned to another statement is stale.
    data["links"][0]["pins"]["statement"] = "pl-fp-v1:" + "0" * 64
    (toy / "symbols.json").write_text(json.dumps(data))
    _, _, cfg = build(toy, reuse_lean=True)
    assert [(s["stale"], s["stale_because"]) for s in chunk(cfg, "T:thm:even-add")[1]["symbols"]] \
        == [(True, ["statement"]), (False, [])]


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


@needs_lean
@needs_tex
def test_a_link_can_name_a_sub_term(toy):
    """#59: a link's Lean end may be a sub-term, named by its place and number."""
    _, _, cfg = build(toy)
    st = next(c for c in chunk(cfg, "T:thm:even-add")[1]["clauses"] if c["spec"] == SPEC)["statement"]
    concl = st["conclusion"]
    k = next(i for i, t in enumerate(concl["terms"])
             if "".join(s["t"] for s in concl["segments"][t["from"]:t["to"]]) == "(a + b)")
    add(cfg, "T:thm:even-add", "a", SPEC, WHO, term=f"c#{k}")
    _, _, cfg = build(toy, reuse_lean=True)
    (link,) = chunk(cfg, "T:thm:even-add")[1]["symbols"]
    # It is recorded by the sub-term's identity in the proposition, not its printed position
    # (#73), and the same identity can be given directly.
    assert link["lean"] == {"decl": SPEC, "at": concl["terms"][k]["id"]} and not link["stale"]
    add(cfg, "T:thm:even-add", "a", SPEC, WHO, at=concl["terms"][k]["id"])
    with pytest.raises(SymbolError, match="no sub-term with the identity"):
        add(cfg, "T:thm:even-add", "a", SPEC, WHO, at="/9/9/9")
    with pytest.raises(SymbolError, match="no sub-term"):
        add(cfg, "T:thm:even-add", "a", SPEC, WHO, term="c#999")
    # A sub-term is found by numbers that depend on how the statement is printed: a link whose
    # number now names other text, or an older one made without its text, is stale (#67).
    data = json.loads((toy / "symbols.json").read_text())
    data["links"][0]["pins"]["target"] = "(b + a)"
    (toy / "symbols.json").write_text(json.dumps(data))
    _, _, cfg = build(toy, reuse_lean=True)
    assert chunk(cfg, "T:thm:even-add")[1]["symbols"][0]["stale"]
    del data["links"][0]["pins"]["target"]
    (toy / "symbols.json").write_text(json.dumps(data))
    _, _, cfg = build(toy, reuse_lean=True)
    assert chunk(cfg, "T:thm:even-add")[1]["symbols"][0]["stale"]


def test_a_link_on_a_typeset_passage_goes_stale_with_its_context():
    """The same printed text typeset under other macros or references is another passage for a
    link made on it (#62, #69); a link made on the source text alone keeps its old rule."""
    from prooflens.manifest import symbol_links
    from prooflens.util import sha256_text
    text = "For $a$ and $b$."
    lean = {"specs": {SPEC: {"fingerprint": "fp", "binders": [{"name": "a"}]}}}
    excerpt = {"ready": True, "text": text, "fingerprint": "tex-excerpt-v1:one"}

    def link(**pins):
        return {"symbols": [{"claim": "P:x", "symbol": {"tex": "a"}, "lean": {"decl": SPEC, "var": 0},
                             "by": WHO, "pins": {"statement": "fp", "source": sha256_text(text),
                                                 **pins}}]}

    def stale(display, ex, tex=text):
        return [s["stale"] for s in symbol_links(display, "P:x", tex, lean, ex)]
    on_excerpt = link(excerpt="tex-excerpt-v1:one")
    assert stale(on_excerpt, excerpt) == [False]
    assert stale(on_excerpt, {**excerpt, "fingerprint": "tex-excerpt-v1:two"}) == [True]
    assert stale(on_excerpt, {**excerpt, "ready": False}) == [True], "shown from the PDF"
    assert stale(on_excerpt, None) == [True]
    assert stale(link(), {**excerpt, "fingerprint": "tex-excerpt-v1:two"}) == [False]
    assert stale(link(), excerpt, tex="Changed $a$.") == [True]


def test_a_link_names_one_object_by_its_identity_and_says_why_it_is_stale():
    """#73: a property of an object's type (prefixed by the object's identity and the field), one
    occurrence of a variable and an equation of a definition each have an identity a link or an
    alignment can name; a variable is named by its number and pinned to its binder's identity;
    a link that no longer holds says why, and one made by place and number is never drawn."""
    from prooflens.manifest import symbol_links
    from prooflens.symbols import IDS, target_text, term_by_id
    from prooflens.util import sha256_text
    text = "For solutions $s$ and $t$."

    def start(obj, who, var):
        return {"field": "start", "kind": "proposition", "type": {
            "id": f"{obj}#start:/", "text": f"{who}.path 0 = d",
            "segments": [{"t": who, "var": var, "at": f"{obj}#start:/0/1/1"}, {"t": ".path 0 = d"}],
            "terms": [{"id": f"{obj}#start:/", "from": 0, "to": 2}]}}
    spec = {"fingerprint": "fp", "binders": [
        {"name": "d", "role": "forall", "id": "/", "type": {"text": "Nat"}},
        {"name": "s", "role": "forall", "id": "/1", "type": {"text": "Solution d"},
         "properties": [start("/1", "s", 1)]},
        {"name": "t", "role": "forall", "id": "/1/1", "type": {"text": "Solution d"},
         "properties": [start("/1/1", "t", 2)]}],
        "conclusion": {"id": "/1/1/1", "text": "s = t",
                       "segments": [{"t": "s", "var": 1, "at": "/1/1/1/0/1"}, {"t": " = "},
                                    {"t": "t", "var": 2, "at": "/1/1/1/1"}],
                       "terms": [{"id": "/1/1/1", "from": 0, "to": 3}]}}
    # The same field of two objects: each identity names its own object's statement.
    assert term_by_id(spec, "/1#start:/") == "s.path 0 = d"
    assert term_by_id(spec, "/1/1#start:/") == "t.path 0 = d"
    # One occurrence of a variable, apart from the variable.
    assert term_by_id(spec, "/1/1/1/1") == "t" and term_by_id(spec, "/1/1/1/9") is None
    # An equation of a linked definition, named by its theorem.
    eqn = {"text": "F 0 = 0", "segments": [{"t": "F 0"}, {"t": " = 0"}],
           "terms": [{"id": "Ex.F.eq_1:/", "from": 0, "to": 2}]}
    assert term_by_id({"definition": {"equations": [{"statement": eqn}]}}, "Ex.F.eq_1:/") == "F 0 = 0"

    lean = {"specs": {SPEC: spec}}

    def why(lean_end, **pins):
        pins = {"statement": "fp", "source": sha256_text(text), **pins}
        display = {"symbols": [{"claim": "P:x", "symbol": {"tex": "s"}, "lean": {"decl": SPEC, **lean_end},
                                "by": WHO, "pins": pins}]}
        [ln] = symbol_links(display, "P:x", text, lean)
        assert ln["stale"] == bool(ln["stale_because"])
        return ln["stale_because"]
    assert why({"at": "/1#start:/"}, target="s.path 0 = d", ids=IDS) == []
    assert why({"at": "/1#start:/"}, target="t.path 0 = d") == ["target"]
    assert why({"at": "/1/1/1/1"}) == ["unpinned"]
    assert why({"at": "/7"}, target="s") == ["missing"]
    assert why({"term": 0, "in": "c"}, target=target_text(spec, {"at": "/1/1/1"})) == ["positional"]
    assert why({"var": 2}, target="t", binder_id="/1/1") == []
    assert why({"var": 2}, target="t", binder_id="/1") == ["target"], "another variable named t"
    assert why({"var": 1}, target="s", ids="older@0") == ["ids"]
    assert why({"var": 1}, target="s", statement="fp-other") == ["statement"]


@needs_lean
@needs_tex
def test_a_definitions_symbol_is_linked_apart_for_each_object_it_stands_for(toy, monkeypatch):
    """#99: Definition 1.1 only defines, so its symbols link into its definitions. Its `n` is
    printed five times: twice for the number defined even, three times in the triangular
    numbers. Each object's occurrences are linked apart and named; they never share one."""
    from prooflens.symbols import remove

    before, body, cfg = build(toy)
    decls = body["lean"]["decls"]

    def terms(name):
        for pp in (decls[name].get("body"), *(q.get("statement") for q in
                                              decls[name].get("equations") or [])):
            for t in (pp or {}).get("terms") or []:
                yield t["id"], "".join(s["t"] for s in pp["segments"][t["from"]:t["to"]])
    even = next(i for i, text in terms("Toy.IsEven") if text == "n = 2 * k")
    # The smallest sub-term of an equation of the triangular numbers that mentions n.
    tri = min((x for x in terms("Toy.triangle") if "n" in x[1]), key=lambda x: len(x[1]))[0]
    add(cfg, "T:def:even", "n", "Toy.IsEven", WHO, at=even, occurrence=[2, 1],
        paper_object="n, the number defined")
    monkeypatch.chdir(toy)
    cli.main(["symbol", "add", "T:def:even", "n", "Toy.triangle", "--at", tri, "--occurrence",
              "3", "--occurrence", "4", "--occurrence", "5", "--object", "n, the index of T",
              "--as", WHO])
    for kw, why in [
        ({"var": "n", "occurrence": [5, 1], "paper_object": "another n"}, "linked already at"),
        ({"var": "n"}, "linked already at"),                              # every occurrence
        ({"var": "n", "occurrence": [6], "paper_object": "x"}, "occurs 5 time"),
        ({"var": "n", "occurrence": [1]}, "name it"),
    ]:
        with pytest.raises(SymbolError, match=why):
            add(cfg, "T:def:even", "n", "Toy.IsEven", WHO, **kw)
    with pytest.raises(SymbolError, match="not a statement or a definition of"):
        add(cfg, "T:def:even", "n", SPEC, WHO, var="a")
    # The same object's link is replaced, not doubled.
    add(cfg, "T:def:even", "n", "Toy.IsEven", WHO, at=even, occurrence=[1, 2],
        paper_object="n, the number defined")
    after, _, cfg = build(toy, reuse_lean=True)
    assert {c["id"]: c["status"] for c in after["claims"]} == \
        {c["id"]: c["status"] for c in before["claims"]}
    links = chunk(cfg, "T:def:even")[1]["symbols"]
    assert [(ln["symbol"], ln["lean"], ln["stale"]) for ln in links] == [
        ({"tex": "n", "occurrence": [3, 4, 5], "of": 5, "object": "n, the index of T"},
         {"decl": "Toy.triangle", "at": tri}, False),
        ({"tex": "n", "occurrence": [1, 2], "of": 5, "object": "n, the number defined"},
         {"decl": "Toy.IsEven", "at": even}, False)]
    assert remove(cfg, "T:def:even", "n", "n, the index of T") == 1
    assert [ln["symbol"]["object"] for ln in json.loads((toy / "symbols.json").read_text())["links"]] \
        == ["n, the number defined"]
