"""A theorem of the project whose type is `¬ S` or `S → False`, where S is the proposition of a
clause with no `refute`, is a warning that prints the inventory field to add (#659). It changes
no status."""

import json

from conftest import build, edit, findings, needs_lean, needs_tex
from prooflens import cli, pipeline
from prooflens.probe import merge_records, negations_request, parse_records

CODE = "unrecorded-refutation"


def test_the_request_names_the_propositions_without_a_refutation():
    inv = {"claims": [{"id": "a", "clauses": [{"spec": "S.p", "refute": "A.p"},
                                              {"spec": "S.q"}, {"defs": ["D"]}]},
                      {"id": "b", "clauses": [{"spec": "S.q", "accept": "A.q"}]}]}
    assert negations_request(inv) == {"kind": "negations", "name": "", "names": ["S.q"]}
    assert negations_request({"claims": [{"id": "a", "clauses": [
        {"spec": "S.p", "refute": "A.p"}]}]}) is None


def test_records_are_read_and_merged_across_sessions():
    def session(*recs):
        return parse_records([json.dumps(r) for r in recs] + [json.dumps({"record": "done"})])
    a = session({"record": "env", "lean": "x", "githash": "y"},
                {"record": "negation", "name": "A.q_false", "spec": "S.q", "form": "not",
                 "module": "A"},
                {"record": "negations", "searched": 3, "found": 1, "errors": []})
    b = session({"record": "env", "lean": "x", "githash": "y"},
                {"record": "negations", "name": "", "spec": None,
                 "errors": ["probe-error: out of heartbeats"]})
    assert a["negations"] == {"found": [{"name": "A.q_false", "spec": "S.q", "form": "not",
                                         "module": "A"}], "errors": [], "searched": 3}
    m = merge_records([("A", a), ("B", b)])["negations"]
    assert m["found"] == a["negations"]["found"]
    assert m["errors"] == ["probe-error: out of heartbeats"] and m["searched"] == 3


def outcome(index, body):
    """Everything the assessment decides apart from the new warning."""
    return ({c["id"]: (c["status"], c["status_code"]) for c in index["claims"]},
            body["assessment"]["gates"],
            sorted(f["id"] for f in body["assessment"]["findings"] if f["code"] != CODE))


@needs_lean
@needs_tex
def test_a_negation_the_inventory_does_not_name_is_a_warning(toy, monkeypatch, capsys):
    index, body, _ = build(toy)
    # The toy's refutation of Proposition 2.3 is named by its clause: nothing to report.
    assert not findings(body, CODE)

    # Its clause loses `refute`, and a second theorem states the negation as `S → False`.
    inv = json.loads((toy / "claims.json").read_text(encoding="utf-8"))
    for c in inv["claims"]:
        for cl in c.get("clauses", []):
            if cl.get("refute") == "Toy.Acceptance.prop_pred":
                del cl["refute"]
    (toy / "claims.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
    edit(toy / "lean/Toy/Acceptance.lean", "theorem prop_pred_pos :",
         "theorem prop_pred_false : PaperSpec.prop_pred → False := prop_pred\n\n"
         "theorem prop_pred_pos :")
    index, body, _ = build(toy)
    found = sorted(findings(body, CODE, "T:prop:pred"), key=lambda f: f["trigger"])
    assert [(f["tier"], f["subject"], f["trigger"], f["fix"]) for f in found] == [
        ("warning", "T:prop:pred#0", "Toy.Acceptance.prop_pred",
         {"refute": "Toy.Acceptance.prop_pred"}),
        ("warning", "T:prop:pred#0", "Toy.Acceptance.prop_pred_false",
         {"refute": "Toy.Acceptance.prop_pred_false"})]
    assert found[0]["message"] == (
        "declaration Toy.Acceptance.prop_pred has type ¬ Toy.PaperSpec.prop_pred; "
        "Toy.PaperSpec.prop_pred is the proposition of clause 'as printed' of T:prop:pred, "
        "which has no `refute`")
    assert "has type Toy.PaperSpec.prop_pred → False;" in found[1]["message"]
    assert len(findings(body, CODE)) == 2

    # `check` lists each with the field to add.
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check"])
    except SystemExit:
        pass
    out = capsys.readouterr().out
    assert f"  warning  {found[0]['message']}" in out
    assert 'add to the clause in the inventory: "refute": "Toy.Acceptance.prop_pred"' in out

    # The statuses, gates and other findings are those of the same build without the search.
    with_search = outcome(index, body)
    monkeypatch.setattr(pipeline, "negations_request", lambda inv: None)
    index, body, _ = build(toy)
    assert not findings(body, CODE)
    assert outcome(index, body) == with_search
