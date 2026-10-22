"""`workspace show` names each kind of evidence it stores (#250), on the toy paper's Lean project
with its paper in zero configuration: a declaration, an application inside a proof, a fact
inside a proof, a Lean certificate, a source location, a paper passage, and a composition's
bridge. The stored records are as `update` wrote them; only the text names them."""

import json
import shutil
import subprocess

from conftest import TOY, needs_lean, needs_tex

from prooflens import cli

WHO = "human:A-Auditor"
CLAIM = "Theorem 2.5"
REFUTES = {"theorem": "ToyAudit.bound_range_at_one_false",
           "target": "ToyAudit.bound_range_at_one", "certifies": "refutes"}
BRIDGE = {"theorem": "Toy.Acceptance.thm_bound", "target": "Toy.PaperSpec.thm_bound"}


def put(rec):
    return {"op": "put", "record": rec}


def run(capsys, *argv):
    capsys.readouterr()
    cli.main(list(argv))
    return capsys.readouterr().out


@needs_lean
@needs_tex
def test_workspace_show_names_each_kind_of_evidence(tmp_path, monkeypatch, capsys):
    root = tmp_path / "toy"
    shutil.copytree(TOY / "lean", root, ignore=shutil.ignore_patterns(".lake", ".machinechecked"))
    shutil.copytree(TOY / "paper", root / "paper")
    for target in ("Toy", "ToyAudit"):
        subprocess.run(["lake", "build", target], cwd=root, check=True, capture_output=True,
                       timeout=900)
    monkeypatch.chdir(root)
    cli.main(["build"])

    uses = json.loads(run(capsys, "compare", "--query", "uses", "Toy.Acceptance.thm_triangle",
                          "--json"))
    app = next(a for a in uses["results"][0]["applications"]
               if a["caller"] == "Toy.Acceptance.thm_bound")
    facts = json.loads(run(capsys, "compare", "--query", "proof-facts",
                           "Toy.Acceptance.thm_bound", "--json"))
    hn = next(f for f in facts["results"] if f.get("name") == "hn")

    run(capsys, "workspace", "open", "--mode", "informed", "--as", WHO)
    ops = tmp_path / "ops.json"
    ops.write_text(json.dumps({"ops": [
        put({"id": "e-decl", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"decl": "Toy.Acceptance.thm_triangle"}}),
        put({"id": "e-app", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"app": {"callee": "Toy.Acceptance.thm_triangle", "id": app["id"]}}}),
        put({"id": "e-fact", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"fact": hn["ref"]}}),
        put({"id": "e-cert", "kind": "evidence", "claim": CLAIM, "role": "supports",
             "ref": {"certificate": REFUTES}}),
        put({"id": "e-source", "kind": "evidence", "claim": CLAIM, "role": "candidate",
             "ref": {"source": {"file": "Toy/Acceptance.lean", "line": 41}}}),
        put({"id": "e-paper", "kind": "evidence", "claim": CLAIM, "role": "candidate",
             "ref": {"paper": {"claim": CLAIM, "quote": "a constant"}}}),
        put({"id": "c1", "kind": "composition", "claim": CLAIM,
             "steps": [{"id": "s1", "establishes": "2 T_n = n (n + 1)", "uses": ["e-app"]},
                       {"id": "s2", "establishes": "n ≤ n²", "uses": ["e-fact"]}],
             "bridge": BRIDGE})]}), encoding="utf-8")
    ack = json.loads(run(capsys, "workspace", "update", str(ops), "--as", WHO))
    assert ack["ok"], ack

    # The stored references are of the kind each record cites.
    shown = json.loads(run(capsys, "workspace", "show", "--as", WHO, "--json"))
    (cid, c), = shown["claims"].items()
    kinds = {e["id"]: [k for k in ("decl", "app", "fact", "certificate", "source", "paper")
                       if k in e["ref"]] for e in c["evidence"]}
    assert kinds == {"e-decl": ["decl"], "e-app": ["app"], "e-fact": ["fact"],
                     "e-cert": ["certificate"], "e-source": ["source"], "e-paper": ["paper"]}

    text = run(capsys, "workspace", "show", "--as", WHO)
    line = {ln.split()[1]: ln for ln in text.splitlines()
            if ln.startswith("  evidence ")}
    assert "Toy.Acceptance.thm_triangle  [current]" in line["e-decl"]
    assert "Toy.Acceptance.thm_triangle applied in Toy.Acceptance.thm_bound  [current]" in \
        line["e-app"]
    assert "hn : n ≤ n * n, inside the proof of Toy.Acceptance.thm_bound  [current]" in \
        line["e-fact"]
    assert ("ToyAudit.bound_range_at_one_false, certificate for ToyAudit.bound_range_at_one  "
            "[current]") in line["e-cert"]
    assert "Toy/Acceptance.lean:41  [unchecked]" in line["e-source"]
    assert "paper passage  [unchecked]" in line["e-paper"]
    assert [e for e, ln in line.items() if "paper passage" in ln] == ["e-paper"]
    # What the certificate establishes, and the fact's basis, under their lines.
    assert ("Lean checks that the type of ToyAudit.bound_range_at_one_false is the negation of "
            "ToyAudit.bound_range_at_one (∀ (k : Nat), 1 ≤ k * 1 ^ 2). It certifies that "
            "proposition only, not the reading it is attached to.") in text
    assert "established inside this proof under this context" in text
    assert ("bridge Toy.Acceptance.thm_bound for Toy.PaperSpec.thm_bound: Lean checks it"
            in text)
