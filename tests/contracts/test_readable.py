"""A statement arranged to be read as mathematics (#70), from synthetic statement records in
the probe's form: objects grouped by where they stand, each assumption and conclusion with its
role and where it comes from, each tied to its expression's identity. Display only."""

from prooflens.readable import readable


def pp(text, at, *vs, expansions=()):
    """A printed expression `text` at identity `at` whose segments mention the variables `vs`
    (number, name), with the definitions expanded in it (`(name, at)`)."""
    segs = [{"t": text}] + [{"t": n, "var": v, "at": f"{at}/{v}"} for v, n in vs]
    out = {"text": text, "segments": segs, "terms": [], "id": at}
    if expansions:
        out["expansions"] = [{"at": a, "id": a + "=", "name": n} for n, a in expansions]
    return out


def node(op, name, var, at, ty, body, scope=None, after=(), within=(), **kw):
    supplies = "proposition" if op == "hypothesis" else kw.pop("supplies", "data")
    return {"op": op, "name": name, "var": var, "id": at, "type": ty, "supplies": supplies,
            "scope": scope or ("produced" if op == "exists" else "given"),
            "after": list(after), "within": list(within), "args": [body], **kw}


def leaf(text, at, *vs, **kw):
    return {"leaf": pp(text, at, *vs, **kw)}


def spec(tree, opening, exact="/"):
    return {"tree": tree, "binders": [{} for _ in range(opening)], "exact": {"id": exact}}


def rows(r):
    return [(x["k"], x["role"]) for x in r["rows"]]


def test_even_addition_groups_its_objects_and_lists_evenness_once():
    """`∀ a b : ℕ, IsEven a → IsEven b → IsEven (a + b)`: one row for a and b, a condition on
    each, the conclusion established, and one definition of evenness with its three
    applications, each with its expansion at its actual argument."""
    ev = "Toy.IsEven"
    t = node("forall", "a", 0, "/", pp("Nat", "/0"),
             node("forall", "b", 1, "/1", pp("Nat", "/1/0"),
                  node("hypothesis", "h1", 2, "/1/1", pp("IsEven a", "/1/1/0", (0, "a"),
                                                         expansions=[(ev, "/1/1/0")]),
                       node("hypothesis", "h2", 3, "/1/1/1",
                            pp("IsEven b", "/1/1/1/0", (1, "b"), expansions=[(ev, "/1/1/1/0")]),
                            leaf("IsEven (a + b)", "/1/1/1/1", (0, "a"), (1, "b"),
                                 expansions=[(ev, "/1/1/1/1")]), after=[0, 1]),
                       after=[0, 1]), after=[0]))
    r = readable(spec(t, 4), "S.even_add")
    assert rows(r) == [("objects", "input"), ("condition", "assumption"),
                       ("condition", "assumption"), ("claim", "output")]
    obj, h1, h2, concl = r["rows"]
    assert [o["name"] for o in obj["objects"]] == ["a", "b"] and obj["quantifier"] == "forall"
    assert obj["at"] == "/0" and [o["at"] for o in obj["objects"]] == ["/0", "/1/0"]
    assert (h1["about"], h1["joint"], h1["origin"], h1["at"]) == ([0], False, "assumed", "/1/1/0")
    assert h2["about"] == [1]
    assert (concl["about"], concl["origin"]) == ([0, 1], "established")
    assert concl["definitions"] == [{"name": ev, "at": "/1/1/1/1", "expansion": "/1/1/1/1="}]
    [d] = r["definitions"]
    assert d["name"] == ev and [(a["at"], a["role"]) for a in d["applications"]] == [
        ("/1/1/0", "assumption"), ("/1/1/1/0", "assumption"), ("/1/1/1/1", "output")]
    assert r["schema"] == "prooflens/readable@1" and r["exact"] == "/"


def test_the_two_orders_of_a_constant_and_a_for_every_read_differently():
    once = node("exists", "C", 0, "/1", pp("Nat", "/1/0"),
                node("forall", "n", 1, "/1/1", pp("Nat", "/1/1/0"),
                     leaf("n ≤ C * n", "/1/1/1", (1, "n"), (0, "C")), after=[0]))
    each = node("forall", "n", 0, "/", pp("Nat", "/0"),
                node("exists", "C", 1, "/1/1", pp("Nat", "/1/1/0"),
                     leaf("n ≤ C * n", "/1/1/1", (0, "n"), (1, "C")), after=[0]))
    a, b = readable(spec(once, 2)), readable(spec(each, 2))
    shape = lambda r: [(x["objects"][0]["name"], x["quantifier"], x["role"], x["after"])
                       for x in r["rows"] if x["k"] == "objects"]
    assert shape(a) == [("C", "exists", "output", []), ("n", "forall", "input", [0])]
    assert shape(b) == [("n", "forall", "input", []), ("C", "exists", "output", [0])]
    # A constant and a variable of the same type are never one row: one is chosen, one given.
    assert all(len(x["objects"]) == 1 for x in a["rows"] if x["k"] == "objects")


def solution(var, at, name="s"):
    """An object of a structure type carrying one proof field and one data field."""
    return {"properties": [
        {"field": "start", "kind": "proposition", "basis": "type", "structure": "S.Solution",
         "declared_in": "S.Base", "inherited": True, "via": ["S.Solution.toBase"],
         "projection": "S.Base.start", "depends": [var],
         "type": pp(f"{name}.path 0 = d", f"{at}#start:/", (var, name))},
        {"field": "path", "kind": "data", "basis": "type", "term": f"{name}.path",
         "type": pp("Nat → Nat", f"{at}#path:/")}]}


def test_properties_carried_by_a_type_keep_their_origin_by_where_the_object_stands():
    """A supplied solution's fields are included in its type; a produced one's are established
    by producing it, never supplied before the statement; one inside an assumption stays there
    with its fields."""
    given = node("forall", "s", 0, "/", pp("Solution d", "/0"), leaf("P s", "/1", (0, "s")),
                 **solution(0, "/"))
    [obj, _] = readable(spec(given, 1))["rows"]
    assert (obj["role"], [(p["field"], p["origin"], p["at"]) for p in obj["properties"]]) == \
        ("input", [("start", "type", "/#start:/")])
    assert [(d["field"], d["term"]) for d in obj["data"]] == [("path", "s.path")]
    assert obj["properties"][0]["declared_in"] == "S.Base"

    produced = node("exists", "s", 0, "/1", pp("Solution d", "/1/0"), leaf("Good s", "/1/1", (0, "s")),
                    **solution(0, "/1"))
    [obj, claim] = readable(spec(produced, 1))["rows"]
    assert (obj["role"], obj["quantifier"], [p["origin"] for p in obj["properties"]]) == \
        ("output", "exists", ["established"])
    assert claim["origin"] == "established"

    inner = node("exists", "s", 1, "/0/1", pp("Solution d", "/0/1/0"),
                 leaf("Good s", "/0/1/1", (1, "s")), scope="assumed",
                 within=["assume", "then"], **solution(1, "/0/1"))
    hyp = node("hypothesis", "h", 0, "/", pp("∃ s, Good s", "/0"), leaf("True", "/1"),
               logic=inner)
    [cond, claim] = readable(spec(hyp, 1))["rows"]
    assert (cond["k"], cond["role"], cond["name"]) == ("condition", "assumption", "h")
    [w, good] = cond["rows"]
    assert (w["k"], w["role"], w["scope"], w["objects"][0]["name"]) == \
        ("objects", "assumption", "assumed", "s")
    assert [p["origin"] for p in w["properties"]] == ["type"]
    assert (good["k"], good["role"], good["origin"]) == ("condition", "assumption", "assumed")
    assert claim["k"] == "claim"


def test_a_witness_inside_a_negation_or_one_alternative_keeps_its_enclosing_claim():
    neg = {"op": "not", "id": "/", "args": [
        node("exists", "x", 0, "/1/1", pp("Nat", "/1/1/0"), leaf("x < 0", "/1/1/1", (0, "x")),
             scope="denied", within=["not"])]}
    [n] = readable(spec(neg, 0))["rows"]
    assert (n["k"], n["role"]) == ("not", "output")
    [[w, c]] = n["parts"]
    assert (w["quantifier"], w["scope"], w["role"]) == ("exists", "denied", "output")
    assert c["k"] == "claim"
    alt = {"op": "or", "id": "/", "args": [
        node("exists", "x", 0, "/1/1", pp("ℝ", "/1/1/0"), leaf("n < x", "/1/1/1", (0, "x")),
             scope="alternative", within=["or"]),
        node("exists", "x", 1, "/2/1", pp("Nat", "/2/1/0"), leaf("2 * x = n", "/2/1/1", (1, "x")),
             scope="alternative", within=["or"])]}
    [o] = readable(spec(alt, 0))["rows"]
    left, right = o["parts"]
    assert left[0]["objects"][0]["var"] != right[0]["objects"][0]["var"]
    assert [p[0]["scope"] for p in o["parts"]] == ["alternative", "alternative"]
    # An implication's premise is assumed, its conclusion established under it.
    imp = {"op": "implies", "id": "/", "args": [leaf("P", "/0"), leaf("Q", "/1")]}
    [i] = readable(spec(imp, 0))["rows"]
    assert [[(x["k"], x["role"], x["origin"]) for x in p] for p in i["parts"]] == [
        [("condition", "assumption", "assumed")], [("claim", "output", "established")]]


def test_supplied_structure_and_an_additional_assumption_on_it():
    """`[MeasurableSpace Ω]` supplies structure on Ω; `[SigmaFinite μ]` is an assumption in
    addition, which states what its field says; μ's type carries properties of its own."""
    sf = {"properties": [{"field": "out'", "kind": "proposition", "basis": "premise",
                          "structure": "M.SigmaFinite", "declared_in": "M.SigmaFinite",
                          "type": pp("∃ s, …", "/1/1/1#out':/", (2, "μ"))}]}
    mu = {"properties": [{"field": "empty", "kind": "proposition", "basis": "type",
                          "structure": "M.Measure", "declared_in": "M.Measure",
                          "type": pp("μ ∅ = 0", "/1/1#empty:/", (2, "μ"))}]}
    t = node("forall", "Ω", 0, "/", pp("Type", "/0"),
             node("instance", "inst", 1, "/1", pp("MeasurableSpace Ω", "/1/0", (0, "Ω")),
                  node("forall", "μ", 2, "/1/1", pp("Measure Ω", "/1/1/0", (0, "Ω")),
                       node("instance", "inst", 3, "/1/1/1",
                            pp("SigmaFinite μ", "/1/1/1/0", (2, "μ")), leaf("True", "/1/1/1/1"),
                            supplies="proposition", binder="instance", **sf),
                       **mu),
                  binder="instance"))
    r = readable(spec(t, 4))["rows"]
    assert [(x["k"], x["role"], x.get("origin")) for x in r] == [
        ("objects", "input", None), ("structure", "input", "supplied"),
        ("objects", "input", None), ("condition", "assumption", "assumed"), ("claim", "output",
                                                                            "established")]
    assert r[1]["on"] == [0]
    assert [(p["field"], p["origin"]) for p in r[2]["properties"]] == [("empty", "type")]
    assert [(s["field"], s["origin"]) for s in r[3]["states"]] == [("out'", "assumed")]


def test_a_cited_result_is_proved_for_its_own_object_only():
    t = node("forall", "s", 0, "/", pp("Solution d", "/0"),
             node("forall", "s", 1, "/1", pp("Solution e", "/1/0"), leaf("P s s", "/1/1")),
             **solution(0, "/"))
    cited = [{"object": {"decl": "S.two", "var": 1, "id": "/1"}, "ref": {"decl": "S.lemma"},
              "statement": "s.path 1 = d", "evidence": "e1"},
             {"object": {"decl": "S.two", "var": 1, "id": "/other"}, "ref": {"decl": "S.stale"}}]
    first, second, _ = readable(spec(t, 2), "S.two", cited)["rows"]
    assert all(p["origin"] != "proved" for p in first["properties"])
    [p] = [p for p in second["properties"] if p["origin"] == "proved"]
    assert (p["object"], p["ref"], p["statement"], p["evidence"]) == \
        (1, {"decl": "S.lemma"}, "s.path 1 = d", "e1")


def test_a_record_without_a_statement_has_no_reading():
    assert readable(None) is None and readable({}) is None
    # A record written before the tree is read from its binders and conclusion.
    old = {"binders": [{"role": "forall", "name": "n", "id": "/", "type": pp("Nat", "/0")}],
           "conclusion": pp("0 ≤ n", "/1", (0, "n"))}
    r = readable(old)
    assert [(x["k"], x["role"]) for x in r["rows"]] == [("objects", "input"), ("claim", "output")]
