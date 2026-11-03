"""A dismissal covers exactly the warning it was given for (#506). A warning that a dismissal
matches is dismissed and never also marked stale because another dismissal of the same code,
subject and trigger has another fingerprint: that dismissal belongs to another warning. A
warning is marked stale only when no dismissal matches it and a dismissal of its code, subject
and trigger matches no warning the assessment reports (it lapsed)."""

from types import SimpleNamespace

from prooflens.assess import Assessor

# The docstring of `Foo.Bar` names `Baz` under two headings; `Foo.Baz` is a module.
MODDOCS = [
    {"record": "moddoc", "module": "Foo.Bar", "line": 5, "name": "Baz",
     "heading": "Main results", "item_lead": True, "kind": "module", "full": "Foo.Baz"},
    {"record": "moddoc", "module": "Foo.Bar", "line": 9, "name": "Baz",
     "heading": "Notation", "item_lead": False, "kind": "module", "full": "Foo.Baz"},
]
MAIN, NOTATION = 5, 9


def module_doc(dismissals, moddocs=MODDOCS):
    """The module-doc-name warnings of `moddocs` under `dismissals`, by line."""
    a = Assessor(SimpleNamespace(statement_authors=[], lean_root=None), {},
                 {"moddocs": moddocs}, {}, [], dismissals)
    a.module_doc_checks()
    return {f["line"]: f for f in a.findings if f["code"] == "module-doc-name"}


def dismissal(f, **kw):
    return {"code": "module-doc-name", "subject": f["subject"], "trigger": f["trigger"],
            "fingerprint": f["fingerprint"], "rationale": f"kept at line {f['line']}",
            "by": "auditor", **kw}


def test_a_name_under_two_headings_has_two_dismissals_neither_stale():
    open_ = module_doc([])
    assert set(open_) == {MAIN, NOTATION}
    main, notation = open_[MAIN], open_[NOTATION]
    assert main["trigger"] == notation["trigger"] == "Baz"
    assert main["fingerprint"] != notation["fingerprint"]
    assert not any(f.get("dismissed") or f.get("dismissal_stale") for f in open_.values())

    # Each warning is dismissed by its own dismissal, and neither reads as lapsed because of
    # the other's.
    both = module_doc([dismissal(main), dismissal(notation)])
    assert both[MAIN]["dismissed"] == {"rationale": f"kept at line {MAIN}", "by": "auditor"}
    assert both[NOTATION]["dismissed"] == {"rationale": f"kept at line {NOTATION}",
                                           "by": "auditor"}
    assert not any(f.get("dismissal_stale") for f in both.values())


def test_a_dismissal_of_one_heading_leaves_the_other_open_not_stale():
    main = module_doc([])[MAIN]
    one = module_doc([dismissal(main)])
    assert one[MAIN].get("dismissed") and not one[MAIN].get("dismissal_stale")
    # The other warning was never dismissed: it is open, and no dismissal of it lapsed.
    assert not one[NOTATION].get("dismissed") and not one[NOTATION].get("dismissal_stale")


def test_a_dismissal_lapses_when_its_name_moves_to_another_heading():
    open_ = module_doc([])
    main, notation = open_[MAIN], open_[NOTATION]
    # The name is now under "Notation" only: the dismissal given under "Main results" matches no
    # warning, so the warning that remains reads as having a dismissal that no longer applies.
    moved = module_doc([dismissal(main)], moddocs=MODDOCS[1:])
    assert not moved[NOTATION].get("dismissed") and moved[NOTATION]["dismissal_stale"]
    # A lapsed dismissal beside a current one: the current one dismisses its warning, and the
    # warning it matches is not stale.
    lapsed = {**dismissal(main), "fingerprint": "pl-moddoc-v1:" + "0" * 64}
    mixed = module_doc([lapsed, dismissal(notation)], moddocs=MODDOCS[1:])
    assert mixed[NOTATION].get("dismissed") and not mixed[NOTATION].get("dismissal_stale")


def test_a_dismissal_of_one_warning_per_subject_still_lapses():
    # A code with one warning per code, subject and trigger: a dismissal of an earlier
    # fingerprint lapses, and a current one beside it dismisses without a stale mark.
    def warn(dismissals):
        a = Assessor(SimpleNamespace(statement_authors=[]), {}, {}, {}, [], dismissals)
        a.add_warning("witness-instances", "T:x#0", "P.s", {"fingerprint": "fp-2"},
                      "message", "witness-instances")
        return a.findings[-1]

    d = {"code": "witness-instances", "subject": "P.s", "trigger": "witness-instances",
         "rationale": "canonical instances", "by": "auditor"}
    old = warn([{**d, "fingerprint": "fp-1"}])
    assert not old.get("dismissed") and old["dismissal_stale"]
    both = warn([{**d, "fingerprint": "fp-1"}, {**d, "fingerprint": "fp-2"}])
    assert both["dismissed"] and not both.get("dismissal_stale")


# A statement with two suprema in the reals, as the probe records it: each application with
# its positions and the term a dismissal of it is tied to.
def supremum(at, term):
    return {"const": "iSup", "carrier": "Real", "carrier_head": "Real",
            "lattice": "conditional", "at": [at], "term": term, "vars": []}


def totalised(occurrences, dismissals):
    rec = {"name": "P.s", "consts": ["iSup"], "fingerprint": "fp-1",
           "order_ops": {"complete": True, "occurrences": occurrences}}
    a = Assessor(SimpleNamespace(statement_authors=[]), {}, {"decls": {}}, {}, [], dismissals)
    a.totalised_warnings("T:x#0", "P.s", rec)
    return {f["at"]: f for f in a.findings}


def test_an_application_dismissal_that_followed_its_application_is_not_stale():
    first = totalised([supremum("/0", "a"), supremum("/1", "b")], [])
    fp = {at: f["fingerprint"] for at, f in first.items()}

    def d(at, fingerprint):
        return {"code": "totalised", "subject": "P.s", "trigger": "iSup", "at": at,
                "fingerprint": fingerprint, "rationale": f"bounded at {at}", "by": "auditor"}

    # The application `b` moves to `/0`, where `a` was, and `a` is gone. The dismissal given
    # for `b` follows it; the one given for `a` lapses. In either order of the dismissals the
    # warning at `/0` is dismissed by `b`'s, and not marked stale by `a`'s.
    for ds in ([d("/0", fp["/0"]), d("/1", fp["/1"])], [d("/1", fp["/1"]), d("/0", fp["/0"])]):
        (f,) = totalised([supremum("/0", "b")], ds).values()
        assert f["dismissed"] == {"rationale": "bounded at /1", "by": "auditor"}
        assert not f.get("dismissal_stale")

    # A new application `c` takes the position `b` left. It was never dismissed: `b`'s dismissal
    # went with `b`, so `c`'s warning is open and not marked stale.
    fs = totalised([supremum("/0", "b"), supremum("/1", "c")], [d("/1", fp["/1"])])
    assert fs["/0"]["dismissed"] and not fs["/0"].get("dismissal_stale")
    assert not fs["/1"].get("dismissed") and not fs["/1"].get("dismissal_stale")

    # A dismissal that follows no application lapses at its position.
    fs = totalised([supremum("/0", "a2"), supremum("/1", "b")], [d("/0", fp["/0"])])
    assert not fs["/0"].get("dismissed") and fs["/0"]["dismissal_stale"]
    assert not fs["/1"].get("dismissed") and not fs["/1"].get("dismissal_stale")
