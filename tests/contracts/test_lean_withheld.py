"""An export of a paper whose `publish` settings say `lean = false` publishes no Lean text
(#559): no statement, type or term the build printed appears anywhere in it, findings included.
A warning keeps what it says without the Lean: a totalisation warning names its operation, the
structure on its type and the state of each condition of its rule, and quotes neither the type,
the rule's type, the sub-terms nor the premises that establish the conditions."""

import json

import jsonschema

from conftest import build, edit, findings, needs_lean, needs_tex
from prooflens import config as cfgmod
from prooflens.assess import OUTSIDE
from prooflens.export import export, public_claim
from prooflens.schemas import schema, validate

L = "lean/Toy/"

# Theorems that a clause's refutation scope and proof name, each with a type the build prints: a
# reading the refutation also covers and a class lemma for its counterexample (#653), and
# Corollary 2.5 proved assuming Theorem 2.2 (#658).
SCOPED = """
/-- At `n = 0` the printed inequality fails. -/
theorem prop_pred_at_zero : ¬ (0 - 1 < 0 / 1) := by decide

/-- The counterexample is a natural number. -/
theorem prop_pred_zero_nat : (0 : Nat) ≤ 0 + 0 := by decide

theorem cor_of_triangle : PaperSpec.thm_triangle → PaperSpec.cor_even_triangle := by
  intro h n
  have e := h (4 * n)
  have m : 4 * n * (4 * n + 1) = 4 * (n * (4 * n + 1)) := Nat.mul_assoc 4 n (4 * n + 1)
  exact ⟨n * (4 * n + 1), by omega⟩

end Toy.Acceptance"""

# Stand-ins for an order library, declared at the root as a larger project's library declares
# them: a supremum, the range of a family, a bound and a number line where a supremum needs one.
ORDER = """universe u v

/-- Predicates on `α`, standing in for sets. -/
def Set (α : Type u) : Type u := α → Prop

/-- The values of a family. -/
def Set.range {α : Type u} {ι : Sort v} (f : ι → α) : Set α := fun a => ∃ i, f i = a

/-- A supremum of each set. -/
class SupSet (α : Type u) where
  sSup : Set α → α

/-- The supremum of a family. -/
def iSup {α : Type u} {ι : Sort v} [SupSet α] (s : ι → α) : α := SupSet.sSup (Set.range s)

/-- A bounded nonempty family has a supremum. -/
class ConditionallyCompleteLattice (α : Type u) extends SupSet α

/-- A number line where only bounded families have a supremum. -/
structure Real where
  val : Int

instance : ConditionallyCompleteLattice Real where
  sSup _ := ⟨0⟩
instance : LE Real := ⟨fun _ _ => True⟩
instance : Inhabited Real := ⟨⟨0⟩⟩

/-- `s` is bounded above. -/
def BddAbove {α : Type u} [LE α] (s : Set α) : Prop := ∃ b, ∀ a, s a → a ≤ b
"""


def printed_lean(data):
    """Every expression the build printed from the Lean, in the site data at `data`: each
    printed term (`text` beside its `segments` or `math`), each type and premise a warning's
    applications quote, and each sub-term they print; bare names are left out."""
    found = set()

    def walk(x):
        if isinstance(x, dict):
            if isinstance(x.get("text"), str) and ("segments" in x or "math" in x):
                found.add(x["text"])
            for o in x.get("occurrences") or []:
                found.add(o.get("type") or "")
                found.update(c.get("statement") or "" for c in o.get("conditions") or [])
                found.update(s.get("text") or "" for s in o.get("subterms") or [])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for f in data.rglob("*.json"):
        walk(json.loads(f.read_text(encoding="utf-8")))
    return {s.strip() for s in found
            if len(s.strip()) >= 5 and any(ch in s for ch in " ()→∀∃:=<>+-*/")}


def published_strings(out):
    """Each string of each JSON file of the export at `out`, and the text of its other files,
    by file."""
    for f in sorted(out.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix == ".json":
            def strings(x):
                if isinstance(x, str):
                    yield x
                elif isinstance(x, dict):
                    for v in x.values():
                        yield from strings(v)
                elif isinstance(x, list):
                    for v in x:
                        yield from strings(v)
            yield f, "\n".join(strings(json.loads(text)))
        else:
            yield f, text


@needs_lean
@needs_tex
def test_an_export_without_the_lean_quotes_none_of_it(toy, tmp_path):
    # Proposition 2.3 as printed gains a supremum bounded by a premise, and a division.
    (toy / L / "Order.lean").write_text(ORDER)
    edit(toy / L / "PaperSpec.lean", "import Toy.Defs", "import Toy.Defs\nimport Toy.Order")
    edit(toy / L / "PaperSpec.lean", "def prop_pred : Prop := ∀ n : Nat, n - 1 < n",
         "def prop_pred : Prop :=\n  ∀ (n : Nat) (f : Nat → Real), BddAbove (Set.range f) →\n"
         "    n - 1 < n / 1 ∧ iSup f = iSup f")
    edit(toy / L / "Acceptance.lean", "  have := h 0\n  omega",
         "  have := (h 0 (fun _ => default) ⟨default, fun _ _ => trivial⟩).1\n  omega")
    # Its refutation gains a scope, and Corollary 2.5 a proof assuming Theorem 2.2.
    edit(toy / L / "Acceptance.lean", "end Toy.Acceptance", SCOPED)
    inv = json.loads((toy / "claims.json").read_text(encoding="utf-8"))
    by_id = {c["id"]: c for c in inv["claims"]}
    by_id["T:prop:pred"]["clauses"][0].update(
        refute_scope=OUTSIDE, standing_assumptions=["natural numbers"],
        refutation_covers=[{"move": "n chosen first",
                            "theorem": "Toy.Acceptance.prop_pred_at_zero"}],
        class_lemmas=[{"assumption": "natural numbers",
                       "theorem": "Toy.Acceptance.prop_pred_zero_nat"}])
    by_id["T:cor:even-triangle"]["clauses"][0]["accept_from"] = {
        "theorem": "Toy.Acceptance.cor_of_triangle", "assumes": ["Toy.PaperSpec.thm_triangle"]}
    (toy / "claims.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False),
                                     encoding="utf-8")
    edit(toy / "machinechecked.toml", "publish = { pdf = true, source_text = true, lean = true",
         "publish = { pdf = true, source_text = false, lean = false")
    index, body, cfg = build(toy)

    # The build's warnings quote the Lean: the premise that bounds the family, the sub-terms.
    (sup,) = [f for f in findings(body, "totalised", "T:prop:pred") if f["trigger"] == "iSup"]
    [occ] = sup["occurrences"]
    bound = next(c for c in occ["conditions"] if c["condition"] == "bounded-above")
    assert (bound["state"], bound["by"], bound["statement"]) == \
        ("established", "premise", "BddAbove (Set.range f)")
    printed = printed_lean(cfg.out_dir / "site" / "data")
    assert {"BddAbove (Set.range f)", "n - 1 < n / 1"} <= printed and len(printed) > 20
    # So do the refutation's scope and the proof from Theorem 2.2: their theorems' types.
    site = cfg.out_dir / "site" / "data" / "claims"
    files = {c["id"]: c["file"] for c in index["claims"]}
    scope = json.loads((site / files["T:prop:pred"]).read_text())["clauses"][0]
    cor = json.loads((site / files["T:cor:even-triangle"]).read_text())["clauses"][0]
    assert [(e["state"], e["type"]["text"] in printed)
            for e in scope["refutation_covers"] + scope["class_lemmas"]] == [("proved", True)] * 2
    assert cor["checks"]["accept_from"]["ok"] and cor["proofs"]["accept_from"]["type"]["text"] \
        in printed

    # The export quotes none of what the build printed, anywhere.
    export(cfgmod.load(toy / "machinechecked.toml"), tmp_path / "public")
    inventory = json.dumps(json.loads((toy / "claims.json").read_text()), ensure_ascii=False)
    leaks = [(f.relative_to(tmp_path / "public").as_posix(), p)
             for f, text in published_strings(tmp_path / "public")
             for p in printed if p in text and p not in inventory]
    assert leaks == []

    # Each published claim has the form a reader of published audits checks (`published.py`).
    data = tmp_path / "public" / "data"
    idx = json.loads((data / "index.json").read_text())
    shown = {c["id"]: json.loads((data / "claims" / c["file"]).read_text())
             for c in idx["claims"]}
    for c in shown.values():
        validate(c, "manifest-claim")

    # The refutation's scope keeps its readings, its lemmas and their states.
    public_scope = shown["T:prop:pred"]["clauses"][0]
    assert [(e.get("move") or e.get("assumption"), e["state"], "type" in e)
            for e in public_scope["refutation_covers"] + public_scope["class_lemmas"]] == \
        [("n chosen first", "proved", False), ("natural numbers", "proved", False)]

    # The warnings are there, saying what they can without the Lean.
    chunk = shown["T:prop:pred"]
    (g,) = [g for g in chunk["findings"] if g["id"] == sup["id"]]
    [o] = g["occurrences"]
    assert {k: o[k] for k in ("operation", "structure", "state")} == \
        {"operation": "iSup", "structure": "conditionally-complete-lattice", "state": "applies"}
    assert "type" not in o and "subterms" not in o
    assert [(x["condition"], x["state"], x.get("by")) for x in o["conditions"]] == \
        [(x["condition"], x["state"], x.get("by")) for x in occ["conditions"]]
    assert all("statement" not in x for x in o["conditions"])
    assert g["message"] == sup["message"], "the real-number rule quotes no Lean"


def test_a_warning_recorded_before_its_withheld_form_keeps_no_lean():
    """A finding from evidence recorded before the assessment made its form without the Lean
    keeps, without the Lean, no field that can quote it."""
    from prooflens.config import Publish
    occ = {"operation": "HDiv.hDiv", "type": "Fin n → Real", "type_head": "Real",
           "structure": "group-with-zero", "state": "applies",
           "rule": "division in Fin n → Real: x / 0 = 0", "at": ["/1"],
           "subterms": [{"at": "/1", "text": "T / N"}], "condition_state": "established",
           "conditions": [{"condition": "bounded-above", "state": "established", "by": "premise",
                           "premise": "h", "statement": "BddAbove (Set.range F)"}]}
    f = {"id": "totalised:C#0:HDiv.hDiv@/1", "tier": "warning", "code": "totalised",
         "subject": "C#0", "trigger": "HDiv.hDiv",
         "message": "division in Fin n → Real: x / 0 = 0 (…)", "occurrences": [occ]}
    chunk = {"clauses": [], "findings": [f]}
    shown = public_claim(chunk, Publish(lean=True))["findings"][0]
    assert shown["occurrences"] == [occ] and shown["message"] == f["message"]
    hidden = public_claim(chunk, Publish(lean=False))["findings"][0]
    text = json.dumps(hidden, ensure_ascii=False)
    for lean in ("Fin n → Real", "T / N", "BddAbove (Set.range F)"):
        assert lean not in text, lean
    [o] = hidden["occurrences"]
    assert o["state"] == "applies" and o["conditions"][0]["state"] == "established"
    for x in (shown, hidden):
        jsonschema.validate(x, finding_schema())


def finding_schema():
    """The published form of a finding (`manifest-claim`'s `finding`)."""
    s = schema("manifest-claim")
    return {"$schema": s["$schema"], "$defs": s["$defs"], "$ref": "#/$defs/finding"}


def test_a_warning_without_the_lean_publishes_its_withheld_form():
    """Without the Lean, a totalisation warning publishes the message and applications the
    assessment stated without quoting it, in the form a reader of published audits checks
    (`published.py`): an application without its type is still a published application."""
    from prooflens.config import Publish
    occ = {"operation": "HDiv.hDiv", "type": "Fin n → Real", "type_head": "Real",
           "structure": "group-with-zero", "state": "applies",
           "rule": "division in Fin n → Real: x / 0 = 0", "at": ["/1"],
           "subterms": [{"at": "/1", "text": "T / N"}]}
    held = {"operation": "HDiv.hDiv", "type_head": "Real", "structure": "group-with-zero",
            "state": "applies", "rule": "division in a group with zero: x / 0 = 0", "at": ["/1"]}
    f = {"id": "totalised:C#0:HDiv.hDiv@/1", "tier": "warning", "code": "totalised",
         "subject": "C#0", "trigger": "HDiv.hDiv",
         "message": "division in Fin n → Real: x / 0 = 0 (…)", "occurrences": [occ],
         "withheld": {"message": "division in a group with zero: x / 0 = 0 (…)",
                      "occurrences": [held]}}
    hidden = public_claim({"clauses": [], "findings": [f]}, Publish(lean=False))["findings"][0]
    assert hidden["message"] == f["withheld"]["message"] and hidden["occurrences"] == [held]
    assert "withheld" not in hidden
    jsonschema.validate(hidden, finding_schema())
