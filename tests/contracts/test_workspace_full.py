"""Workspace records that Lean checks, in the toy paper's full assessment (#248): an
application inside a proof (`app`), a fact inside a proof (`fact`) and a composition's bridge
are recorded by `workspace update`, by the reader's local server and in an export, against the
toy's Lean project (`lean_root`, the `lean/` folder beside `machinechecked.toml`). No status
changes on the way."""

import json

from conftest import build, needs_lean, needs_tex

from prooflens import cli
from prooflens import server
from prooflens.export import export

CLAIM = "T:thm:bound"
WHO = "human:A-Auditor"
BRIDGE = {"theorem": "Toy.Acceptance.thm_bound", "target": "Toy.PaperSpec.thm_bound"}


def put(rec):
    return {"op": "put", "record": rec}


def run_json(capsys, *argv):
    capsys.readouterr()
    cli.main(list(argv))
    return json.loads(capsys.readouterr().out)


@needs_lean
@needs_tex
def test_lean_checked_records_in_a_full_assessment(toy, tmp_path, monkeypatch, capsys):
    index, _, cfg = build(toy)
    before = {c["id"]: c["status"] for c in index["claims"]}
    assert cfg.lean_root != cfg.root
    monkeypatch.chdir(toy)

    # Theorem 2.5's proof applies Theorem 2.2 and states n ≤ n * n on the way.
    uses = run_json(capsys, "compare", "--query", "uses", "Toy.Acceptance.thm_triangle", "--json")
    app = next(a for a in uses["results"][0]["applications"]
               if a["caller"] == "Toy.Acceptance.thm_bound")
    facts = run_json(capsys, "compare", "--query", "proof-facts", "Toy.Acceptance.thm_bound",
                     "--json")
    hn = next(f for f in facts["results"] if f.get("name") == "hn")

    run_json(capsys, "workspace", "open", "--mode", "informed", "--as", WHO, "--json")
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps({"op_id": "lean-checked", "ops": [
        put({"id": "e-app", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"app": {"callee": "Toy.Acceptance.thm_triangle", "id": app["id"]}}}),
        put({"id": "e-fact", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"fact": hn["ref"]}}),
        put({"id": "c1", "kind": "composition", "claim": CLAIM,
             "steps": [{"id": "s1", "establishes": "2 T_n = n (n + 1)", "uses": ["e-app"]},
                       {"id": "s2", "establishes": "n ≤ n²", "uses": ["e-fact"]},
                       {"id": "s3", "establishes": "T_n ≤ 1 · n²", "after": ["s1", "s2"]}],
             "bridge": BRIDGE}),
        put({"id": "f1", "kind": "finding", "claim": CLAIM, "coverage": "partial",
             "basis": "checked_bridge", "composition": "c1", "note": "C = 1"}),
        {"op": "submit", "id": "f1", "base_rev": 1}]}), encoding="utf-8")
    ack = run_json(capsys, "workspace", "update", str(ops), "--as", WHO)
    assert ack["ok"], ack
    assert set(ack["changed"]) == {"e-app", "e-fact", "c1", "f1"}

    shown = run_json(capsys, "workspace", "show", "--as", WHO, "--json")
    rd = shown["claims"][CLAIM]
    ev = {e["id"]: e for e in rd["evidence"]}
    assert ev["e-app"]["ref"]["app"]["caller"] == "Toy.Acceptance.thm_bound"
    assert ev["e-fact"]["ref"]["fact"]["type"] == "n ≤ n * n"
    assert {e["currency"]["state"] for e in ev.values()} == {"current"}
    c, = rd["compositions"]
    assert c["bridge"]["type"] == BRIDGE["target"]
    assert (c["basis"], c["bridge_check"]["state"]) == ("checked_bridge", "checked")

    # The reader's local server records the same kinds against the same Lean project.
    routes = {}
    monkeypatch.setattr(server, "serve", lambda *a, **kw: routes.update(api=kw["api"]))
    cli.main(["view", "--no-browser"])
    gets, posts = routes["api"]
    got = gets["/api/proof-facts"]({"name": ["Toy.Acceptance.thm_bound"]})
    assert any(f.get("name") == "hn" for f in got["results"])
    ack = posts["/api/workspace"]({"action": "update", "id": shown["id"], "op_id": "reader",
                                   "ops": [put({"id": "e-fact-2", "kind": "evidence",
                                                "claim": CLAIM, "role": "candidate",
                                                "ref": {"fact": hn["ref"]}})]})
    assert ack["ok"] and ack["changed"] == ["e-fact-2"]

    # An export counts the bridge, which it checks against the Lean project.
    export(cfg, tmp_path / "out")
    row = next(r for r in json.loads((tmp_path / "out" / "data" / "index.json").read_text())
               ["claims"] if r["id"] == CLAIM)
    pub, = json.loads((tmp_path / "out" / "data" / "work" / row["file"]).read_text())["readings"]
    assert pub["compositions"][0]["basis"] == "checked_bridge"
    assert pub["compositions"][0]["bridge_check"] == {"state": "checked", "reasons": []}
    assert pub["findings"][0]["basis"] == "checked_bridge"

    index2, _, _ = build(toy)
    assert {c["id"]: c["status"] for c in index2["claims"]} == before
