"""The probe prints every statement complete (#619), on a synthetic project: a statement nested
deeper than Lean prints by default, one whose conclusion stands under sixty hypotheses, and a
definition's body as deep, each of which Lean's default printing cuts short with `⋯`. Their
texts, which `review show` prints (`compare.statement_lines`, and the `exact` segments of
`--json`), leave nothing out, on Lean 4.24 and 4.32."""

import json
import subprocess

import pytest

from conftest import needs_lean
from prooflens import compare, probe

DEPTH = 60      # Lean's default printing leaves out what lies more than about 50 levels down
HYPOTHESES = 60


def nested_sum(n: int) -> str:
    """`b + (a + (b + … (b + a)))`, `n` additions deep, as Lean prints it."""
    t = "a"
    for i in range(n):
        t = f"{'ab'[i % 2 == 0]} + {t if i == 0 else '(' + t + ')'}"
    return t


HYPS = " ".join(f"h{i}" for i in range(HYPOTHESES))
PREMISES = " → ".join(f"h{i} ≤ c" for i in range(HYPOTHESES))
CONCLUSION = "u x + v x ≤ c * (u x + (v x + (u x + v x)))"
STATEMENTS = {
    "Deep.nested": f"∀ (a b : Nat), {nested_sum(DEPTH)} = a",
    "Deep.hypotheses": f"∀ (c : Nat) (u v : Nat → Nat) ({HYPS} : Nat), {PREMISES} → "
                       f"∀ (x : Nat), {CONCLUSION}",
}

SOURCE = f"""import Lean

namespace Deep

/-- A sum nested {DEPTH} additions deep. -/
def nested : Prop := ∀ a b : Nat, {nested_sum(DEPTH)} = a

/-- A conclusion under {HYPOTHESES} hypotheses. -/
def hypotheses : Prop := ∀ (c : Nat) (u v : Nat → Nat) ({HYPS} : Nat),
  {PREMISES} → ∀ x, {CONCLUSION}

/-- A definition whose body is nested as deep. -/
def deepValue (a b : Nat) : Nat := {nested_sum(DEPTH)}

-- Lean's default printing leaves a part of each of them out.
open Lean Meta in
#eval show MetaM Unit from do
  for n in [``nested, ``hypotheses, ``deepValue] do
    let some (.defnInfo d) := (← getEnv).find? n | throwError "{{n}} is missing"
    unless (toString (← ppExpr d.value)).contains '⋯' do
      throwError "Lean prints {{n}} complete by default"

end Deep
"""


def flat(text: str) -> str:
    """`text` with each run of white space (Lean's line breaks and indentation) one space."""
    return " ".join(text.split())


@needs_lean
@pytest.mark.parametrize("toolchain", ["leanprover/lean4:v4.32.0", "leanprover/lean4:v4.24.0"])
def test_a_deep_statement_is_printed_complete(tmp_path, toolchain):
    if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                      text=True).stdout.find(toolchain) < 0:
        pytest.skip(f"{toolchain} is not installed")
    root = tmp_path / "deep"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "deep"\ndefaultTargets = ["Deep"]\n\n'
                                        '[[lean_lib]]\nname = "Deep"\n')
    (root / "lean-toolchain").write_text(toolchain + "\n")
    (root / "Deep.lean").write_text(SOURCE)
    built = subprocess.run(["lake", "build"], cwd=root, capture_output=True, text=True,
                           timeout=900)
    assert built.returncode == 0, built.stdout + built.stderr
    query = {"scope_roots": ["Deep"], "spec_prefix": "Deep", "accept_prefix": "Deep",
             "allowed_axioms": [],
             "requests": [{"kind": "spec", "name": n} for n in STATEMENTS]
             + [{"kind": "decl", "name": "Deep.deepValue"}]}
    recs = probe.lean_session(root, ["Deep"], query, lambda ls: [json.loads(l) for l in ls])
    specs = {r["name"]: r for r in recs if r["record"] == "spec"}
    for name, expected in STATEMENTS.items():
        rec = specs[name]
        assert rec["errors"] == [], rec["errors"]
        exact = rec["exact"]
        assert flat(exact["text"]) == expected, (name, exact["text"])
        assert flat("".join(s["t"] for s in exact["segments"])) == expected, name
        printed = [rec["conclusion"]["text"]] + [b["type"]["text"] for b in rec["binders"]]
        assert not [t for t in printed if "⋯" in t], (name, printed)
        shown = "\n".join(compare.statement_lines(
            {"name": name, "statement": compare._statement(rec)}))
        assert "⋯" not in shown and flat(expected) in flat(shown), shown
    (value,) = [r for r in recs if r["record"] == "decl" and r["name"] == "Deep.deepValue"]
    assert flat(value["value"]["text"]) == f"fun (a b : Nat) => {nested_sum(DEPTH)}", \
        value["value"]["text"]
