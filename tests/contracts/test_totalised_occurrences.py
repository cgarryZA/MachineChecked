"""A totalisation warning carries the applications it is about (#232): each with its operation,
its type, the structure on the type that decides the rule, the state of the rule there and the
positions of the application in the statement. The evidence, `check --json`, the site data and
an export carry the same records; the warning changes no status."""

import json

from conftest import build, edit, findings, needs_lean, needs_tex
from prooflens import cli
from prooflens.export import export

L = "lean/Toy/"


@needs_lean
@needs_tex
def test_occurrences_round_trip(toy, tmp_path, monkeypatch, capsys):
    # The printed (false) Proposition 2.3 gains a division of natural numbers.
    edit(toy / L / "PaperSpec.lean", "def prop_pred : Prop := ∀ n : Nat, n - 1 < n",
         "def prop_pred : Prop := ∀ n : Nat, n - 1 < n / 1")
    index, body, cfg = build(toy)
    (f,) = [f for f in findings(body, "totalised", "T:prop:pred") if f["trigger"] == "HDiv.hDiv"]
    assert f["message"].startswith("division in ℕ rounds down and n / 0 = 0")
    (occ,) = f["occurrences"]
    assert {k: occ[k] for k in ("operation", "type_head", "structure", "state")} == {
        "operation": "HDiv.hDiv", "type_head": "Nat", "structure": "unknown", "state": "applies"}
    assert occ["rule"] == "division in ℕ rounds down and n / 0 = 0" and occ["at"]
    assert "occurrences_complete" not in f

    # The position is a sub-term of the printed statement: the division itself.
    spec = body["lean"]["specs"]["Toy.PaperSpec.prop_pred"]
    concl = spec["conclusion"]
    marked = [t for t in concl["terms"] for a in occ["at"]
              if t["id"] == a or (t["id"].startswith(a + "/")
                                  and set(t["id"][len(a):].split("/")) <= {"", "0"})]
    assert ["".join(s["t"] for s in concl["segments"][t["from"]:t["to"]]) for t in marked] \
        == ["n / 1"]

    # A totalised operation the probe does not read by type carries no occurrences.
    sub = [f for f in findings(body, "totalised", "T:prop:pred") if f["trigger"] == "instSubNat"]
    assert sub and all("occurrences" not in g for g in sub)

    def same(g):
        return {k: g.get(k) for k in ("id", "message", "occurrences")}

    # The site data.
    c = next(c for c in index["claims"] if c["id"] == "T:prop:pred")
    chunk = json.loads((cfg.out_dir / "site" / "data" / "claims" / c["file"]).read_text())
    (g,) = [g for g in chunk["findings"] if g["id"] == f["id"]]
    assert same(g) == same(f)

    # `check --json`.
    monkeypatch.chdir(toy)
    capsys.readouterr()
    try:
        cli.main(["check", "--json"])
    except SystemExit:
        pass
    doc = json.loads(capsys.readouterr().out)
    (g,) = [g for g in doc["finding_details"] if g["id"] == f["id"]]
    assert same(g) == same(f)

    # The export.
    export(cfg, tmp_path / "public")
    data = tmp_path / "public" / "data"
    idx = json.loads((data / "index.json").read_text())
    c = next(c for c in idx["claims"] if c["id"] == "T:prop:pred")
    chunk = json.loads((data / "claims" / c["file"]).read_text())
    (g,) = [g for g in chunk["findings"] if g["id"] == f["id"]]
    assert same(g) == same(f)
