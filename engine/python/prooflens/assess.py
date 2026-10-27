"""From evidence to statuses, findings and gates.

Every status shown by any ProofLens view is computed here, from the probe records, the TeX
anchors, the review markers and the inventory; the views only display it.

Findings come in three tiers:

* `violation`: a mechanical fact that contradicts acceptance (a disallowed axiom, a proof whose
  type is not the proposition, a stale source hash, a claim of the paper missing from the
  inventory). A violation fails the consistency check; it does not change a status, which
  records what is proved: a proof that fails its check is not a proof, so its clause is open.
* `warning`: a pattern that may change the meaning of a statement (a totalised operation, for
  instance), or a name a module docstring lists that nothing declares. It asks for
  investigation, may be wrong, and can be dismissed with a recorded rationale tied to the
  subject's fingerprint.
* `obligation`: a judgement only a reviewer can make (a review of a proposition or definition, a
  witness that the hypotheses can be met, a regime the paper intends to cover).

Two gates per paper: the consistency check (no violation) and the release gate (sources checked, consistency clean, every scope decision reviewed, every formal
claim accepted and every definition claim reviewed, no printed clause refuted, every witness
valid, and a Comparator replay of every proof).
"""

from __future__ import annotations

import re

from .status import fields

from . import review_sources
from .reviews import Review, history
from .source_regions import SCHEMES as SOURCE_SCHEMES, changed_line, matches as source_matches

OUT_OF_SCOPE = {"expository", "literature", "empirical", "proof-step", "part-of", "duplicate"}

# Constants whose value outside the intended domain is a junk value; a statement that uses one
# may be weaker or different from the printed claim unless the domain is constrained.
TOTALISED = {
    "instSubNat": "truncated subtraction on ℕ: a - b = 0 when a < b",
    "Nat.sub": "truncated subtraction on ℕ: a - b = 0 when a < b",
    "Nat.instDiv": "division on ℕ rounds down and n / 0 = 0",
    "Int.instDivInt": "integer division rounds and n / 0 = 0",
    "HDiv.hDiv": "division: x / 0 = 0 in Lean's fields and ℕ",
    "Inv.inv": "inverse: 0⁻¹ = 0",
    "MeasureTheory.integral": "the Bochner integral is 0 for a non-integrable function",
    "tsum": "an unconditional sum is 0 when the family is not summable",
    "iSup": "a supremum in ℝ is 0 when the set is unbounded or empty",
    "sSup": "a supremum in ℝ is 0 when the set is unbounded or empty",
    "iInf": "an infimum in ℝ is 0 when the set is unbounded below or empty",
    "sInf": "an infimum in ℝ is 0 when the set is unbounded below or empty",
    "Real.log": "log x = log |x| and log 0 = 0",
    "Real.sqrt": "√x = 0 for x < 0",
    "Real.rpow": "x ^ y for x < 0 is defined through the complex logarithm",
    "deriv": "the derivative is 0 where the function is not differentiable",
    "fderiv": "the derivative is 0 where the function is not differentiable",
    "MeasureTheory.condExp": "the conditional expectation is 0 for a non-integrable function",
    "ENNReal.toReal": "∞.toReal = 0",
    "ENNReal.toNNReal": "∞.toNNReal = 0",
    "SupSet.sSup": "a supremum in ℝ is 0 when the set is unbounded or empty",
    "InfSet.sInf": "an infimum in ℝ is 0 when the set is unbounded below or empty",
}

# Suprema and infima: a family with none gets a default value only in a type where it need not
# exist. The probe records each application's type (`order_ops`), and the warning names it.
ORDER_OPS = {"iSup": "supremum", "sSup": "supremum", "SupSet.sSup": "supremum",
             "iInf": "infimum", "sInf": "infimum", "InfSet.sInf": "infimum"}


def _order_warning(c: str, spec: str, ops) -> str | None:
    """The warning for the order operation `c` in `spec`, from the types of its applications
    there: none when each is taken in a complete lattice (every family has one), the real-number
    rule for the reals, a default value in another conditionally complete type, and an
    unresolved type otherwise. A record without `order_ops` (an older probe) leaves the type
    unresolved."""
    what = ORDER_OPS[c]
    side = "above" if what == "supremum" else "below"
    occ = [o for o in (ops or {}).get("occurrences") or [] if o.get("const") == c]
    if not isinstance(ops, dict):
        return (f"the type of this {what} is not recorded (the evidence predates the record), so "
                f"whether it can take a default value is unresolved ({c} occurs in {spec})")
    real = [o for o in occ if o.get("carrier_head") == "Real"]
    other = sorted({o.get("carrier") or o.get("carrier_head") or "?" for o in occ
                    if o.get("lattice") == "conditional" and o.get("carrier_head") != "Real"})
    unknown = sorted({o.get("carrier") or "?" for o in occ
                      if o.get("carrier_head") != "Real"
                      and o.get("lattice") not in ("complete", "conditional")})
    walked = ops.get("complete", True)
    if not occ and walked:
        unknown = ["not read: it is used without its type"]
    parts = []
    if not walked:
        # The walk stopped early: an application it did not reach may be in any type.
        parts.append(f"the statement is too large to read the type of every {what}, so whether "
                     "one can take a default value is unresolved")
    if real:
        parts.append(TOTALISED[c])
    if other:
        parts.append(f"a {what} in {', '.join(other)} is a default value when the family is "
                     f"empty or not bounded {side}")
    if unknown:
        parts.append(f"Lean finds no lattice structure on the type of a {what} "
                     f"({', '.join(unknown)}), so whether it can take a default value is "
                     "unresolved")
    if not parts:
        return None
    return "; ".join(parts) + f" ({c} occurs in {spec})"


# Division and inverse: what `x / 0` and `0⁻¹` give depends on the type. In a group there is no
# exceptional case; in a group with zero (a field) both are 0; ℕ and ℤ round; ℝ≥0∞ gives ∞.
DIVISION_OPS = {"HDiv.hDiv": ("division", "what x / 0 gives"),
                "Inv.inv": ("inverse", "what 0⁻¹ gives")}
DIVISION_BY_HEAD = {
    ("HDiv.hDiv", "Nat"): "division in ℕ rounds down and n / 0 = 0",
    ("HDiv.hDiv", "Int"): "division in ℤ rounds and n / 0 = 0",
    ("HDiv.hDiv", "ENNReal"): "division in ℝ≥0∞: x / 0 = ∞ when x ≠ 0, 0 / 0 = 0 and ∞ / ∞ = 0",
    ("Inv.inv", "ENNReal"): "inverse in ℝ≥0∞: 0⁻¹ = ∞ and ∞⁻¹ = 0",
}

# Operations with no exceptional case in some types: the Bochner integral of a function into a
# type with one element (every such function is integrable), and a sum in ℝ≥0∞ (every family
# is summable there). In any other type, or one not read, the operation keeps its warning.
EXEMPT = {"MeasureTheory.integral": lambda o: o.get("subsingleton") is True,
          "tsum": lambda o: o.get("carrier_head") == "ENNReal"}


def _occurrences(c: str, ops) -> list[dict]:
    return [o for o in (ops or {}).get("occurrences") or [] if o.get("const") == c] \
        if isinstance(ops, dict) else []


def _division_rule(c: str, o: dict) -> tuple[str, str | None]:
    """The state of the rule for one division or inverse (`applies`, `none` or `unresolved`),
    with the rule when it applies."""
    what = DIVISION_OPS[c][0]
    rule = DIVISION_BY_HEAD.get((c, o.get("carrier_head")))
    if rule:
        return "applies", rule
    if o.get("algebra") == "group":
        return "none", None
    if o.get("algebra") == "group-with-zero":
        zero = "x / 0 = 0" if what == "division" else "0⁻¹ = 0"
        return "applies", f"{what} in {o.get('carrier') or o.get('carrier_head')}: {zero}"
    return "unresolved", None


def _division_warning(c: str, spec: str, ops) -> str | None:
    """The warning for a division or an inverse `c` in `spec`, from the types of its
    applications there: none in a group, `0` in a group with zero, the rule of ℕ, ℤ or ℝ≥0∞ in
    those types, and an unresolved type otherwise (also for a record without `order_ops`)."""
    what, outcome = DIVISION_OPS[c]
    if not isinstance(ops, dict):
        return (f"the type of this {what} is not recorded (the evidence predates the record), so "
                f"{outcome} is unresolved ({c} occurs in {spec})")
    occ = _occurrences(c, ops)
    walked = ops.get("complete", True)
    parts, unknown = [], []
    if not walked:
        parts.append(f"the statement is too large to read the type of every {what}, so "
                     f"{outcome} is unresolved")
    elif not occ:
        unknown.append("not read: it is used without its type")
    for o in occ:
        state, rule = _division_rule(c, o)
        if state == "none":
            continue
        if rule is None:
            ty = o.get("carrier") or "?"
            if ty not in unknown:
                unknown.append(ty)
        elif rule not in parts:
            parts.append(rule)
    if unknown:
        article = "an" if what == "inverse" else "a"
        parts.append(f"Lean finds neither a group nor a field structure on the type of {article} "
                     f"{what} ({', '.join(unknown)}), so {outcome} is unresolved")
    if not parts:
        return None
    return "; ".join(parts) + f" ({c} occurs in {spec})"


def _exempt(c: str, ops) -> bool:
    """Whether every application of `c` was read and each is in a type where it has no
    exceptional case (`EXEMPT`)."""
    occ = _occurrences(c, ops)
    return bool(occ) and ops.get("complete", True) and all(EXEMPT[c](o) for o in occ)


# The operations the probe reads with their types (its `totalOps`).
READ_BY_TYPE = {*ORDER_OPS, *DIVISION_OPS, "MeasureTheory.integral", "tsum",
                "MeasureTheory.condExp", "deriv", "Real.sqrt", "Real.log", "ENNReal.toReal"}

# The conditions the probe looks for at an application (its `conditionsOf`), in words.
CONDITIONS = {"bounded-above": "bounded above", "bounded-below": "bounded below",
              "nonempty-index": "a nonempty index type", "nonempty-set": "a nonempty set",
              "integrable": "the function integrable for this measure",
              "finite": "a finite value"}


def condition_state(conds: list[dict]) -> str:
    """The state of an application's conditions together: `refuted` when a premise refutes one,
    `established` when every one is established, `unresolved` otherwise."""
    states = {c.get("state") for c in conds}
    if "refuted" in states:
        return "refuted"
    return "established" if states == {"established"} else "unresolved"

STRUCTURES = {("lattice", "complete"): "complete-lattice",
              ("lattice", "conditional"): "conditionally-complete-lattice",
              ("lattice", "unknown"): "unknown", ("algebra", "group"): "group",
              ("algebra", "group-with-zero"): "group-with-zero", ("algebra", "unknown"): "unknown",
              ("subsingleton", True): "one-element"}


def _rule(c: str, o: dict) -> tuple[str, str | None]:
    """The state of the rule of `c` at one recorded application `o` (`applies`, `none`: the type
    gives it no exceptional case, or `unresolved`), with the rule when it applies."""
    if c in ORDER_OPS:
        what = ORDER_OPS[c]
        if o.get("carrier_head") == "Real":
            return "applies", TOTALISED[c]
        if o.get("lattice") == "complete":
            return "none", None
        if o.get("lattice") == "conditional":
            side = "above" if what == "supremum" else "below"
            return "applies", (f"a {what} in {o.get('carrier') or o.get('carrier_head')} is a "
                               f"default value when the family is empty or not bounded {side}")
        return "unresolved", None
    if c in DIVISION_OPS:
        return _division_rule(c, o)
    if c in EXEMPT and EXEMPT[c](o):
        return "none", None
    return "applies", TOTALISED[c]


def occurrences(srec: dict, c: str) -> list[dict] | None:
    """The applications of the totalised operation `c` that the probe read in a statement, each
    with its type (`type`, its head constant `type_head`), the structure on it that decides the
    rule (`structure`), the state of the rule there and the rule itself, and the positions of
    the application in the proposition (`at`). None for an operation the probe does not read
    by type, and for a record from before it read them."""
    ops = srec.get("order_ops")
    if not isinstance(ops, dict) or c not in READ_BY_TYPE:
        return None
    out = []
    for o in _occurrences(c, ops):
        state, rule = _rule(c, o)
        structure = next((v for (k, val), v in STRUCTURES.items() if o.get(k) == val
                          and k in o), None)
        rec = {"operation": c, "type": o.get("carrier") or None,
               "type_head": o.get("carrier_head") or None, "structure": structure,
               "state": state, "rule": rule, "at": list(o.get("at") or [])}
        if state == "applies" and o.get("conditions"):
            conds = [{k: d[k] for k in ("condition", "state", "by", "premise", "statement")
                      if k in d} for d in o["conditions"]]
            rec.update(conditions=conds, condition_state=condition_state(conds))
        out.append(rec)
    return out


OCCURRENCE_VERSION = "pl-occ-v1"


def occurrence_fingerprint(o: dict, decls: dict) -> str | None:
    """What a dismissal of one application records: the application in its scope (the
    variables it depends on and the hypotheses about them, `term`, and the variables' names),
    its type and the structure on it, and the fingerprints of the project's declarations it
    uses. None for a record from before the probe read the application's scope."""
    import json
    from .util import sha256_text
    if not o.get("term"):
        return None
    uses = sorted((n, (decls.get(n) or {}).get("fingerprint")) for n in o.get("uses") or [])
    key = {"term": o["term"], "vars": o.get("vars") or [], "uses": uses,
           **{k: o.get(k) for k in ("carrier", "carrier_head", "lattice", "algebra",
                                     "subsingleton")}}
    return f"{OCCURRENCE_VERSION}:" + sha256_text(json.dumps(key, sort_keys=True,
                                                             ensure_ascii=False))


def _unresolved(c: str, o: dict) -> str:
    """Why the rule of `c` at one application is unresolved: Lean finds no structure on its
    type that decides it."""
    ty = o.get("carrier") or "?"
    if c in ORDER_OPS:
        return (f"Lean finds no lattice structure on the type of this {ORDER_OPS[c]} ({ty}), so "
                "whether it can take a default value is unresolved")
    what, outcome = DIVISION_OPS[c]
    return (f"Lean finds neither a group nor a field structure on the type of this {what} "
            f"({ty}), so {outcome} is unresolved")


def totalised_findings(srec: dict, spec: str, decls: dict | None = None) -> list[dict]:
    """The totalisation warnings of `spec`, one per application of an operation the probe read
    by type whose rule applies or is unresolved there (`occurrence`: the record, with its
    `fingerprint`), and one per operation for what is not read application by application: an
    operation not read by type, evidence from before the record, an operation used without
    being read, and the applications a walk that stopped early did not reach."""
    ops = srec.get("order_ops")
    out = []
    for c, msg in totalised(srec, spec):
        if c not in READ_BY_TYPE or not isinstance(ops, dict):
            out.append({"trigger": c, "message": msg, "occurrence": None})
            continue
        occ = occurrences(srec, c)
        raw = _occurrences(c, ops)
        for o, r in zip(occ, raw):
            if o["state"] == "none":
                continue
            why = o["rule"] if o["state"] == "applies" else _unresolved(c, r)
            out.append({"trigger": c, "message": f"{why} ({c} occurs in {spec})",
                        "occurrence": {**o, "fingerprint": occurrence_fingerprint(r, decls or {})}})
        if not ops.get("complete", True):
            what = ORDER_OPS.get(c) or (DIVISION_OPS.get(c) or (None,))[0] or "application"
            out.append({"trigger": c, "occurrence": None, "incomplete": True,
                        "message": f"the statement is too large to read every {what} of {c}, so "
                                   f"the rule at the ones not read is unresolved ({c} occurs in "
                                   f"{spec})"})
        elif not occ:
            out.append({"trigger": c, "message": msg, "occurrence": None})
    return out


def totalised(srec: dict, spec: str) -> list[tuple[str, str]]:
    """The totalised operations `spec` uses, each with its warning (`TOTALISED`): the operation
    is the trigger. Suprema, infima, divisions, inverses, integrals and sums are judged by the
    types they are taken in."""
    out = []
    ops = srec.get("order_ops")
    for c in srec.get("consts", []):
        if c not in TOTALISED:
            continue
        if c in ORDER_OPS:
            msg = _order_warning(c, spec, ops)
        elif c in DIVISION_OPS:
            msg = _division_warning(c, spec, ops)
        elif c in EXEMPT and _exempt(c, ops):
            msg = None
        else:
            msg = f"{TOTALISED[c]} ({c} occurs in {spec})"
        if msg:
            out.append((c, msg))
    return out


# Totalised operations so common in analysis that a warning about them is rarely informative,
# and propositions whose only hypotheses are instances of inhabited classes.
LOW_SIGNAL = {"HDiv.hDiv", "Inv.inv", "witness-instances"}

# Type classes whose instances exist at a canonical type (ℝ, Unit, `Fin 1`, a Dirac measure)
# whenever their arguments are free variables of the proposition. A proposition whose only
# hypotheses are such instances gets a low-signal warning instead of a witness obligation. A
# project sets its own list with `inhabited_classes` in `machinechecked.toml` (`[]` restores
# the obligation everywhere). `Fact`, `Subsingleton`, `Nontrivial` and the project's own
# classes are deliberately absent: their instances need not exist, or not together.
INHABITED_CLASSES = [
    "Inhabited", "Nonempty", "DecidableEq", "Fintype", "Finite", "Countable", "Encodable",
    "NeZero",
    "Preorder", "PartialOrder", "LinearOrder", "Lattice",
    "AddMonoid", "AddCommMonoid", "AddGroup", "AddCommGroup", "Monoid", "CommMonoid", "Group",
    "CommGroup", "Semiring", "CommSemiring", "Ring", "CommRing", "Field", "Module", "Algebra",
    "TopologicalSpace", "UniformSpace", "PseudoMetricSpace", "MetricSpace",
    "PseudoEMetricSpace", "EMetricSpace", "T2Space", "CompleteSpace", "CompactSpace",
    "LocallyCompactSpace", "ProperSpace", "TopologicalSpace.SecondCountableTopology",
    "TopologicalSpace.SeparableSpace",
    "SeminormedAddCommGroup", "NormedAddCommGroup", "NormedSpace", "InnerProductSpace",
    "NormedField", "NontriviallyNormedField", "RCLike", "FiniteDimensional", "Module.Finite",
    "MeasurableSpace", "MeasureTheory.MeasureSpace", "BorelSpace", "OpensMeasurableSpace",
    "MeasurableSingletonClass", "StandardBorelSpace", "MeasurableSpace.CountablyGenerated",
    "MeasureTheory.IsProbabilityMeasure", "MeasureTheory.IsFiniteMeasure",
    "MeasureTheory.IsZeroOrProbabilityMeasure", "MeasureTheory.SigmaFinite",
]

# Constants an instance's argument may be, besides a variable of the proposition: the number
# systems, at which the classes above have their canonical instances.
_STANDARD_TYPES = {"ℕ", "ℤ", "ℚ", "ℝ", "ℂ", "ℝ≥0", "ℝ≥0∞", "Nat", "Int", "Rat", "Real",
                   "Complex", "NNReal", "ENNReal"}


def instance_class(binder: dict, earlier: set[str], allowed: set[str]) -> str | None:
    """The class of an instance binder when it is in `allowed` and applied only to variables
    bound before it (or to a number system): `[NormedAddCommGroup F]`, `[NeZero N]`,
    `[InnerProductSpace ℝ F]`. None for any other instance (`[Fact (1 < p)]`, `[NeZero 0]`,
    a class outside the list), which needs a witness like a hypothesis."""
    text = ((binder.get("type") or {}).get("text") or "").strip()
    if not text or any(ch in text for ch in "()[]{}⟨⟩:,"):
        return None
    head, *args = text.split()
    head = head.lstrip("@")
    if head not in allowed:
        return None
    if not all(a in earlier or a in _STANDARD_TYPES for a in args):
        return None
    return head


def _finding(tier, code, subject, message, **extra):
    f = {"tier": tier, "code": code, "subject": subject, "message": message}
    f.update(extra)
    f["id"] = f"{code}:{subject}" + (f":{extra['trigger']}" if "trigger" in extra else "")
    return f


def parse_comparator(text: str | None) -> dict | None:
    """The structured Comparator record, or an error saying why the text is not one."""
    import json
    if not text:
        return None
    try:
        rec = json.loads(text)
    except ValueError:
        return {"error": "the Comparator log is not a structured record (JSON with commit and "
                         "replayed theorems)"}
    if not isinstance(rec, dict) or not isinstance(rec.get("replayed"), list) or \
            not isinstance(rec.get("commit"), str):
        return {"error": "the Comparator record lacks `commit` or `replayed`"}
    return rec


def _hashes(rec):
    return {h for h in (rec.get("legacy_hash"), rec.get("fingerprint")) if h}


def unread(rec: dict | None) -> bool:
    """Whether a probe record holds no declaration: none was found under the name, or the probe
    failed on the request. Such a record has only `name` and `errors`."""
    if rec is None:
        return True
    errs = rec.get("errors") or []
    return "missing" in errs or any(str(e).startswith("probe-error") for e in errs)


class Assessor:
    def __init__(self, cfg, inventory, lean, tex, reviews: list[Review], dismissals,
                 comparator_log: str | None = None, project_commit: str | None = None):
        self.cfg, self.inv, self.lean, self.tex = cfg, inventory, lean, tex
        self.reviews, self.dismissals = reviews, dismissals
        self.comparator = parse_comparator(comparator_log)
        self.project_commit = project_commit
        self.findings: list[dict] = []
        self.authors = set(cfg.statement_authors)
        self._history = None
        self._unlisted: list[str] | None = None
        # Each name the probe did not find that unlisted project modules declare: those modules.
        self.unlisted_declarers: dict[str, list[str]] = {}
        self._pins: dict[str, str | None] | None = None
        self._witness_only: dict[str, list[str]] | None = None
        self._unpinned: dict[str, str] | None = None

    # -- declarations the probe did not find ------------------------------------------------

    def not_found(self, name: str) -> str:
        """Why the probe has no record of `name`, for a finding: the declaration is not in any
        module the probe loaded. When a project module that is not listed in `modules` declares
        it (as far as its source text shows), that module is named, and recorded in
        `unlisted_declarers` for `check --fix-modules`; when several do, they are named and none
        is offered."""
        mods = []
        try:
            if self._unlisted is None:
                from .probe import lib_names
                from .simple import built_modules
                root = self.cfg.lean_root
                built, unbuilt = built_modules(root, lib_names(root))
                listed = set(self.cfg.modules)
                self._unlisted = [m for m in built + unbuilt if m not in listed]
            from .simple import declaring_modules
            mods = declaring_modules(self.cfg.lean_root, self._unlisted, name)
        except (OSError, ValueError, AttributeError):
            mods = []
        if mods:
            self.unlisted_declarers[name] = mods
        if len(mods) == 1:
            return (f"{name}: not found by the probe; it is declared in {mods[0]}, which is not "
                    "listed in `modules` (`machinechecked check --fix-modules` lists it)")
        if mods:
            return (f"{name}: not found by the probe; it is declared in "
                    f"{' and '.join([', '.join(mods[:-1]), mods[-1]])}, none of which is listed "
                    "in `modules`: list the one meant")
        return f"{name}: not found by the probe; is its module listed in `modules`?"

    # -- reviews --------------------------------------------------------------------------

    def review_state(self, target: str, name: str, rec: dict | None,
                     claim: str | None = None) -> dict:
        """The state of the review of `name`: `reviewed` (current, by a reviewer other than the
        authors of the statements), `author-reviewed`, `stale` (the declaration, or the paper
        text the review read, changed since; `why` says which) or `pending` (none).

        A review reads the passages of the claims that state or name the declaration
        (`review_sources.py`). For `claim`, the review must have read that claim's current
        passage; without one, the current passage of every claim it reads. The record is the
        last marker at the declaration's current hash that did, provided the declaration's last
        marker is at that hash. A marker without digests read a passage only while the history
        shows it unchanged since the marker was written. A marker with no review text records
        no reading and does not count (`why` "no-reading"), unless its reviewer is one the
        configuration allows bare markers by (`bare_markers_by`). When the last marker is at
        another hash but an earlier one would be the record without it, `why` is "shadowed" and
        `shadowed` names both markers; the state is stale all the same."""
        hist = history(self.reviews, target, name)
        last = hist[-1] if hist else None
        readers = review_sources.digests(self.inv, target, name, self.tex)
        need = {claim: readers[claim]} if claim in readers else readers
        why = source_claim = bare = split = shadowed = None
        record = last
        if last is None:
            state = "pending"
        elif rec is None or last.hash not in _hashes(rec):
            state, why = "stale", "declaration"
            shadowed = self._shadowed(hist, rec, need)
            if shadowed:
                why = "shadowed"
        else:
            at = [r for r in hist if r.hash in _hashes(rec)]
            read = [r for r in at if self._reads(r, need)]
            record = next((r for r in reversed(read) if self.has_reading(r)), None)
            if record is None and read:
                why, state, bare = "no-reading", "stale", read[-1]
            elif record is None:
                why, source_claim = self._unread(last, need)
                state = "stale"
                split = self._split(at, need)
            else:
                state = "author-reviewed" if record.by in self.authors else "reviewed"
        current = state in ("reviewed", "author-reviewed")
        out = {"state": state, "current": [record.to_json()] if current else [],
               "stale": [r.to_json() for r in hist if r is not record or state == "stale"],
               "source_sha256": readers}
        if current:
            # The marker the state rests on, and the passages whose reading it counts for here.
            out["rests_on"] = {"file": record.file, "line": record.line, "by": record.by,
                               "passages": sorted(need)}
        if why:
            out["why"] = why
            if source_claim:
                out["source_claim"] = source_claim
            if bare is not None:
                out["marker"] = {"file": bare.file, "line": bare.line}
            if split:
                out["split"] = split
            if shadowed:
                out["shadowed"] = shadowed
        return out

    def _shadowed(self, hist: list[Review], rec: dict | None,
                  need: dict[str, str]) -> dict | None:
        """When the last marker of `hist` is at another hash than the declaration's current
        one, but an earlier marker would be the record without it (at a current hash, with a
        reading of every passage in `need`): that marker (`reading`) and the last one
        (`record`), each with its file, line, hash and reviewer. The last marker is the
        record, so the review is stale; this says where to act."""
        if rec is None or not hist:
            return None
        hashes = _hashes(rec)
        reading = next((r for r in reversed(hist[:-1]) if r.hash in hashes
                        and self._reads(r, need) and self.has_reading(r)), None)
        if reading is None:
            return None
        return {k: {"file": r.file, "line": r.line, "hash": r.hash, "by": r.by}
                for k, r in (("reading", reading), ("record", hist[-1]))}

    @staticmethod
    def _shadowed_words(r: dict) -> str:
        """The two markers of `shadowed`, each with its place, reviewer and hash, for a finding
        or a blocker: what follows "the review". The hashes are given in full: legacy hashes of
        different declarations can share a long prefix."""
        a, b = r["shadowed"]["reading"], r["shadowed"]["record"]
        return (f"at {a['file']}:{a['line']} by {a['by']} records the current hash {a['hash']}, "
                f"but a marker later in the review files, at {b['file']}:{b['line']} by "
                f"{b['by']}, records {b['hash']} and is the record")

    @staticmethod
    def _mentions(text: str, claim: dict) -> bool:
        """Whether review text names a claim, by its id or its printed number."""
        if claim["id"] in text:
            return True
        num = claim.get("number")
        return bool(num) and re.search(r"(?<![\w.])" + re.escape(num) + r"(?![\w]|\.\d)",
                                       text) is not None

    def _warn_other_section(self, claim: dict, subj: str, name: str, r: dict, rec: dict):
        """A warning when the definition claim `claim` is reviewed through a marker whose review
        text names another claim that names `name`, and not this one: the reading may have been
        written against the other passage."""
        if not r.get("current"):
            return
        text = r["current"][0].get("text") or ""
        if self._mentions(text, claim):
            return
        others = [c for c in review_sources.reading_claims(self.inv, "def", name)
                  if c["id"] != claim["id"] and self._mentions(text, c)]
        if others:
            m = r["current"][0]
            self.add_warning(
                "def-review-other-claim", subj, name,
                {"fingerprint": rec.get("fingerprint") or rec.get("legacy_hash")},
                f"{self._claim_label(claim['id'])} is reviewed through the review of {name} at "
                f"{m['file']}:{m['line']}, whose text names "
                + ", ".join(self._claim_label(c["id"]) for c in others)
                + " and not this claim: check that it read this claim's passage",
                f"{m['file']}:{m['line']}")

    def _split(self, at: list[Review], need: dict[str, str]) -> dict | None:
        """When every passage in `need` has a current reading, but no one marker read them all:
        for each passage, the markers at the declaration's current hash that read it. A review
        must read together every passage it is asked for (a definition in a statement's closure:
        every passage that names it), so such readings do not combine."""
        if len(need) < 2:
            return None
        parts = {cid: [{"file": r.file, "line": r.line, "by": r.by} for r in at
                       if self.has_reading(r) and self._read_one(r, cid, sha) == "current"]
                 for cid, sha in sorted(need.items())}
        return parts if all(parts.values()) else None

    def has_reading(self, review: Review) -> bool:
        """Whether a marker records a reading: review text precedes it (its section, or the
        `Review by` line promotion wrote), or its reviewer is allowed bare markers."""
        return bool(review.text.strip()) or review.by in set(
            getattr(self.cfg, "bare_markers_by", None) or [])

    def _read_one(self, review: Review, cid: str, sha: str) -> str:
        """Whether `review` read the current passage `sha` of claim `cid`
        (`review_sources.marker_state`). When `sha` covers listed notation macros, a marker that
        records only the claim's pin, or no digests, read the passage without their definitions
        (`notation-unrecorded`). A passage the manuscript no longer matches (`unpinned_passages`)
        is unread by every marker until it is pinned again and read at the new pin
        (`unpinned`)."""
        if cid in self.unpinned():
            return "unpinned"
        if self._pins is None:
            self._pins = {c["id"]: c.get("source_sha256") for c in self.inv["claims"]}
        pin = self._pins.get(cid)
        if pin and sha != pin and (review.source is None or review.source.get(cid) == pin):
            return "notation-unrecorded"
        if review.source is None and self._history is None:
            self._history = review_sources.History(getattr(self.cfg, "root", None),
                                                   getattr(self.cfg, "inventory", None), self.inv)
        return review_sources.marker_state(review, cid, sha, self._history)

    def _reads(self, review: Review, need: dict[str, str]) -> bool:
        return all(self._read_one(review, c, s) == "current" for c, s in sorted(need.items()))

    def _unread(self, review: Review, need: dict[str, str]) -> tuple[str, str]:
        """Why the last marker does not cover the passages `need`, and the first claim
        concerned."""
        for cid, sha in sorted(need.items()):
            st = self._read_one(review, cid, sha)
            if st != "current":
                return {"changed": "source-changed", "unread": "source-unread",
                        "unrecorded": "source-unrecorded",
                        "notation-unrecorded": "source-notation-unrecorded",
                        "unpinned": "source-unpinned"}[st], cid
        return "source-changed", sorted(need)[0]   # not reached: the last marker read them

    def unpinned(self) -> dict[str, str]:
        """The claims whose passage in the manuscript no longer matches their pin, each with
        where it differs (`unpinned_passages`)."""
        if self._unpinned is None:
            self._unpinned = unpinned_passages(self.inv, self.tex)
        return self._unpinned

    def unpinned_note(self, cid: str | None) -> str:
        """Why the claim `cid`'s passage reads as unread, for a reason or a finding."""
        return (f"the manuscript no longer matches the pin of {self._claim_label(cid)}: "
                f"{self.unpinned().get(cid, 'its text differs')}")

    def _claim_label(self, cid: str | None) -> str:
        c = next((c for c in self.inv["claims"] if c["id"] == cid), None)
        if c is None:
            return "its claims"
        return f"{c['number']} ({cid})" if c.get("number") else cid

    def _stale_note(self, r: dict) -> str:
        """Why a review is not current, for a finding's message."""
        if r["state"] != "stale":
            return ""
        why = r.get("why")
        if why == "source-changed":
            c = next((c for c in self.inv["claims"] if c["id"] == r.get("source_claim")), None)
            notation = c is not None and (review_sources.region_of(self.tex, c) or {}).get(
                "notation")
            return (f" (the source text of {self._claim_label(r.get('source_claim'))}"
                    + (", or a definition of the notation it uses," if notation else "")
                    + " changed since its last reading)")
        if why == "source-unpinned":
            return (f" ({self.unpinned_note(r.get('source_claim'))}; pin the passage again and "
                    "record a reading of the new text)")
        if why == "source-unread" and r.get("split"):
            return (" (no single review read all the passages that name it, and a review must "
                    "read them together: " + "; ".join(
                        f"{self._claim_label(cid)} read at "
                        + ", ".join(f"{m['file']}:{m['line']}" for m in ms)
                        for cid, ms in r["split"].items()) + ")")
        if why == "source-unread":
            return (f" (its last review did not read the passage of "
                    f"{self._claim_label(r.get('source_claim'))})")
        if why == "no-reading":
            m = r.get("marker") or {}
            return (f" (its marker at {m.get('file')}:{m.get('line')} records no reading: no "
                    "review text precedes it)")
        if why == "source-notation-unrecorded":
            return (f" (its last review of {self._claim_label(r.get('source_claim'))} did not "
                    "record the definitions of the notation macros its passage uses)")
        if why == "source-unrecorded":
            return (" (its last review was made before source pins were recorded, and the "
                    f"source text of {self._claim_label(r.get('source_claim'))} cannot be shown "
                    "unchanged since)")
        if why == "shadowed":
            return (f" (its review {self._shadowed_words(r)}: record the review again after that "
                    "marker, or retire that marker)")
        return " (its last review is stale)"

    @staticmethod
    def _stale_fields(r: dict) -> dict:
        if r.get("why") == "no-reading":
            return {"reason": "no-reading", **(r.get("marker") or {})}
        if r.get("why") == "shadowed":
            return {"reason": "shadowed", **r["shadowed"]}
        if r["state"] == "stale" and r.get("why", "declaration") != "declaration":
            return {"reason": r["why"], "source_claim": r.get("source_claim")}
        return {}

    def closure_reviews(self, names: list[str]) -> dict:
        """The review state of every project declaration in the closures of `names`, other than
        the propositions of the inventory (each reviewed by its own spec-review) and the tactic
        scripts of tactic defaults (`_is_auto_param`)."""
        lean = self.lean
        out = {}
        for n in names:
            # A record of a declaration the probe did not find has no closure.
            clos = (lean["specs"][n] if n in lean["specs"] else
                    lean["defs"].get(n, {})).get("closure") or []
            for d in clos:
                if d in lean["specs"] or d in out or self._is_auto_param(d):
                    continue
                out[d] = self.review_state("def", d, lean["decls"].get(d))
        return out

    def _is_proof(self, name: str) -> bool:
        """Whether the declaration `name` is a proof: its type is a proposition (a theorem, a
        proof Lean generates such as `_proof_1`, a `Prop`-valued instance). A record without the
        probe's `proposition` field counts a theorem only; an unknown answer counts as data."""
        rec = self.lean["decls"].get(name) or {}
        if "proposition" in rec:
            return rec["proposition"] is True
        return rec.get("kind") == "theorem"

    def _is_auto_param(self, name: str) -> bool:
        """Whether the declaration `name` is the tactic script Lean stores for a tactic default
        (`pos : 0 < val := by decide`: an auto-parameter, `Pos.pos._autoParam`). Running it gives
        a proof of the proposition the field or binder states, so it fixes nothing a statement
        or a witness says. Only the probe's `auto_param` answer counts: a record without it is a
        definition like any other."""
        return (self.lean["decls"].get(name) or {}).get("auto_param") is True

    def witness_only(self) -> dict[str, list[str]]:
        """The project declarations in the closure of a witness's statement that the assessment
        asks no review for otherwise (outside every proposition, its closure, the definitions a
        definition claim maps and their closures), each with the witnesses that use it. Proofs
        (`_is_proof`) and the tactic scripts of tactic defaults (`_is_auto_param`) are left out:
        a proof carries no data and a tactic script gives only a proof, so neither can fix the
        instance a witness exhibits."""
        if self._witness_only is None:
            lean = self.lean
            covered = set(lean["specs"])
            for rec in lean["specs"].values():
                covered.update(rec.get("closure") or [])
            out: dict[str, set[str]] = {}
            for c in self.inv["claims"]:
                for cl in c.get("clauses") or []:
                    for d in cl.get("defs") or []:
                        covered.add(d)
                        covered.update((lean["defs"].get(d) or {}).get("closure") or [])
                    for w in self._witnesses(cl):
                        for d in (self._proof("witness", w, None) or {}).get("closure") or []:
                            out.setdefault(d, set()).add(w)
            self._witness_only = {d: sorted(ws) for d, ws in out.items()
                                  if d not in covered and not self._is_proof(d)
                                  and not self._is_auto_param(d)}
        return self._witness_only

    @staticmethod
    def _witnesses(cl: dict) -> list[str]:
        return [w for w in [cl.get("witness")] + [r.get("witness")
                                                  for r in cl.get("regimes") or []] if w]

    def witness_defs(self, cl: dict) -> dict[str, tuple[list[str], dict]]:
        """The witness-only declarations (`witness_only`) the witnesses of clause `cl` use, each
        with those witnesses and its review state. A list for the reviewer: unless the
        configuration requires their reviews (`require_witness_def_reviews`), they change no
        status."""
        only = self.witness_only()
        mine = self._witnesses(cl)
        out = {}
        for d, ws in only.items():
            used = [w for w in ws if w in mine]
            if used:
                out[d] = (used, self.review_state("def", d, self.lean["decls"].get(d)))
        return out

    def witness_candidates(self, defs: list[str]) -> list[dict]:
        """The witness-only declarations whose type or body uses one of `defs` (the definitions
        a definition claim maps): candidates for its mapping, for the reader. Display only."""
        out = []
        for d, ws in sorted(self.witness_only().items()):
            uses = sorted(set((self.lean["decls"].get(d) or {}).get("uses") or []) & set(defs))
            if uses:
                out.append({"name": d, "uses": uses, "witnesses": ws})
        return out

    # -- clauses --------------------------------------------------------------------------

    def replay(self, thm: str) -> dict:
        """Whether a structured Comparator record shows a kernel replay of exactly `thm` for this
        commit. The record is JSON: `{"commit": <full sha>, "replayed": [<theorem names>],
        "checker": ..., "kernels": [...]}`. Without a record the replay is `not-run`, never
        `fail`; a record of another commit, or a log ProofLens cannot read as such a record,
        is `unverified`."""
        rec = self.comparator
        if rec is None:
            return {"state": "not-run", "detail": "no Comparator record for this release"}
        if "error" in rec:
            return {"state": "unverified", "detail": rec["error"]}
        since = ""
        if not self.project_commit or not rec.get("commit"):
            return {"state": "unverified",
                    "detail": f"the Comparator record is for commit {str(rec.get('commit'))[:12]}"
                              f", not this one"}
        if rec["commit"] != self.project_commit:
            # A record committed to the project names the commit before the one holding it; it
            # counts when that commit is an ancestor and no Lean input changed since.
            from .replay import unchanged_since
            why = unchanged_since(self.cfg.lean_root, rec["commit"], self.project_commit)
            if why:
                return {"state": "unverified",
                        "detail": f"the Comparator record is for commit {rec['commit'][:12]}, not "
                                  f"this one: {why}"}
            since = f"; replayed at commit {rec['commit'][:12]}, no Lean input changed since"
        # A record made by `machinechecked replay` also says whether the run passed, whether the
        # tree was clean, and the environment it ran in; each must hold for the replay to count.
        if rec.get("passed") is False:
            return {"state": "unverified", "detail": "the Comparator run recorded did not pass"}
        if rec.get("dirty"):
            return {"state": "unverified",
                    "detail": "the Comparator run was on a tree with uncommitted changes"}
        for key, label in (("toolchain", "Lean version"),
                           ("lake_manifest_sha256", "Lake dependencies")):
            here = self._environment().get(key)
            if rec.get(key) is not None and rec.get(key) != here:
                return {"state": "unverified",
                        "detail": f"the Comparator record was made with other {label}"}
        if thm not in set(rec.get("replayed", [])):
            return {"state": "not-run", "detail": "the Comparator record does not cover this proof"}
        # A replay without Comparator's sandbox guard still counts; the fact says so.
        how = rec.get("conditions")
        guard = ("unrecorded" if not isinstance(how, dict) else
                 "guarded" if how.get("guard") not in (None, "none") else "unguarded")
        note = {"guarded": "", "unguarded": "; replayed without the sandbox guard",
                "unrecorded": "; the record does not say whether the sandbox guard was used"}
        return {"state": "pass", "guard": guard,
                "detail": "Comparator replayed the proof in a fresh kernel ("
                + ", ".join(rec.get("kernels", ["lean"])) + ")" + since + note[guard]}

    def _environment(self) -> dict:
        """The audited project's Lean version and Lake manifest hash."""
        if not hasattr(self, "_env"):
            from .util import sha256_file
            root = self.cfg.lean_root
            tc, lm = root / "lean-toolchain", root / "lake-manifest.json"
            self._env = {"toolchain": tc.read_text().strip() if tc.exists() else None,
                         "lake_manifest_sha256": sha256_file(lm) if lm.exists() else None}
        return self._env

    def _proof(self, kind, name, spec):
        return self.lean["proofs"].get(f"{kind}:{name}:{spec or ''}")

    def clause(self, claim: dict, cl: dict, k: int) -> dict:
        subj = f"{claim['id']}#{k}"
        spec = cl.get("spec")
        res = {"name": cl.get("name", "main"), "spec": spec, "accept": cl.get("accept"),
               "refute": cl.get("refute"), "corrects": cl.get("corrects"),
               "witness": cl.get("witness"), "defs": cl.get("defs", []),
               "regimes": cl.get("regimes", []), "checks": {}}
        if self.lean is None:
            res.update(state="unchecked", review="unknown")
            return res
        lean = self.lean
        if spec:
            srec = lean["specs"].get(spec)
            errs = (srec or {}).get("errors", ["missing"])
            res["checks"]["spec"] = {"ok": not errs, "errors": errs}
            for e in errs:
                self.findings.append(_finding(
                    "violation", "spec-" + e.split("=")[0], subj,
                    "proposition " + self.not_found(spec) if e == "missing" else
                    f"proposition {spec}: {e}"))
            sr = self.review_state("spec", spec, srec, claim["id"])
            dr = self.closure_reviews([spec]) if srec else {}
            res["spec_review"] = sr
            if sr["state"] in ("pending", "stale"):
                self.findings.append(_finding(
                    "obligation", "spec-review", subj,
                    f"the proposition {spec} has no current review" + self._stale_note(sr),
                    **self._stale_fields(sr)))
            states = [sr["state"]] + [d["state"] for d in dr.values()]
        else:
            srec = None
            names = list(cl.get("defs", []))
            missing = [d for d in names if d not in lean["decls"]]
            for d in missing:
                self.findings.append(_finding("violation", "def-missing", subj,
                                              "definition " + self.not_found(d)))
            dr = {d: self.review_state("def", d, lean["decls"].get(d), claim["id"])
                  for d in names}
            dr.update({d: r for d, r in self.closure_reviews(names).items() if d not in dr})
            res["spec_review"] = None
            states = [d["state"] for d in dr.values()]
        wd = self.witness_defs(cl)
        if wd and getattr(self.cfg, "require_witness_def_reviews", False):
            # Declared required: each is reviewed like a definition of the proposition, so it
            # can only hold a status back.
            for n in wd:
                if n not in dr:
                    dr[n] = self.review_state("def", n, lean["decls"].get(n))
            states += [dr[n]["state"] for n in wd]
            wd = {}
        res["witness_defs"] = [
            {"name": n, "witnesses": w, "state": r["state"]}
            for n, (w, r) in sorted(wd.items())
            if r["state"] not in ("reviewed", "author-reviewed")]
        for e in res["witness_defs"]:
            rec = lean["decls"].get(e["name"]) or {}
            self.add_warning(
                "witness-def-review", subj, e["name"],
                {"fingerprint": rec.get("fingerprint") or rec.get("legacy_hash")},
                f"the witness {', '.join(e['witnesses'])} uses {e['name']}, which is in no "
                "proposition's definitions and "
                + ("has no review" if e["state"] == "pending" else
                   "has no current review")
                + "; the instance a witness exhibits is fixed by such declarations",
                ",".join(e["witnesses"]))
        if cl.get("defs") and not spec:
            res["witness_candidates"] = self.witness_candidates(cl["defs"])
        res["def_reviews"] = dr
        if not spec:
            for n in names:
                self._warn_other_section(claim, subj, n, dr[n], lean["decls"].get(n) or {})
        for n, d in dr.items():
            if d["state"] in ("pending", "stale"):
                self.findings.append(_finding(
                    "obligation", "def-review", subj,
                    f"the definition {n} has no current review" + self._stale_note(d),
                    trigger=n, **self._stale_fields(d)))
        if any(s in ("pending", "stale") for s in states):
            res["review"] = "pending"
        elif any(s == "author-reviewed" for s in states):
            res["review"] = "author-reviewed"
        else:
            res["review"] = "reviewed"

        # Proofs, refutations and witnesses: a check that fails is a violation, and the proof
        # does not count.
        for kind in ("accept", "refute", "witness"):
            thm = cl.get(kind)
            if not thm:
                continue
            p = self._proof(kind, thm, None if kind == "witness" else spec)
            perrs = (p or {}).get("errors", ["missing"])
            res["checks"][kind] = {"ok": not perrs, "errors": perrs,
                                   "axioms": (p or {}).get("axioms", []),
                                   "sorry": (p or {}).get("sorry", False),
                                   "type": (p or {}).get("type") if kind == "witness" else None}
            res[kind + "_ok"] = not perrs
            if kind in ("accept", "refute"):
                res["checks"]["replay"] = self.replay(thm)
            for e in perrs:
                self.findings.append(_finding("violation", f"{kind}-" + e.split("=")[0], subj,
                                              self.not_found(thm) if e == "missing" else
                                              f"{thm}: {e}"))
        res["state"] = ("proved" if res.get("accept_ok") else
                        "refuted" if res.get("refute_ok") else
                        "open" if spec else
                        "stated" if cl.get("defs") else "unspecified")

        if srec:
            # A checked refutation needs no witness: a proof of ¬S exhibits an instance meeting
            # S's hypotheses (were they never met, S would hold vacuously and not be refutable).
            if not cl.get("witness") and not res.get("refute_ok"):
                self.witness_check(subj, spec, srec)
            self.totalised_warnings(subj, spec, srec)
        regs = []
        for r in cl.get("regimes", []):
            w = r.get("witness")
            p = self._proof("witness", w, None) if w else None
            ok = bool(p) and not p.get("errors")
            regs.append({**r, "discharged": ok, "type": (p or {}).get("type")})
            if not ok:
                why = (f" (its witness {self.not_found(w)})"
                       if w and "missing" in (p or {}).get("errors", ["missing"]) else "")
                self.findings.append(_finding(
                    "obligation", "regime", subj,
                    f"regime not shown to be covered: {r.get('name', '')}{why}",
                    trigger=r.get("name", "")))
        res["regimes"] = regs
        return res

    def witness_check(self, subj: str, spec: str, srec: dict) -> None:
        """The witness a proposition without one needs. A hypothesis, or an instance of a class
        not known to be inhabited, raises the `witness` obligation, naming the binders that need
        it. A proposition whose only hypotheses are instances of `inhabited_classes` over its
        own variables gets a low-signal `witness-instances` warning instead: no theorem shows
        them met, but each has a canonical instance. Neither changes a status."""
        configured = getattr(self.cfg, "inhabited_classes", None)
        allowed = set(INHABITED_CLASSES if configured is None else configured)
        earlier: set[str] = set()
        needs, classes = [], []
        for b in srec.get("binders", []):
            role, text = b.get("role"), (b.get("type") or {}).get("text", "?")
            if role == "hypothesis":
                needs.append(f"{b.get('name', '?')} : {text}")
            elif role == "instance":
                cls = instance_class(b, earlier, allowed)
                if cls is None:
                    needs.append(f"[{text}]")
                else:
                    classes.append(cls)
            if b.get("name"):
                earlier.add(b["name"])
        if needs:
            shown = "; ".join(needs[:3]) + ("; …" if len(needs) > 3 else "")
            self.findings.append(_finding(
                "obligation", "witness", subj,
                f"{spec} has hypotheses but no witness that they can be met ({shown})",
                binders=needs))
        elif classes:
            names = ", ".join(dict.fromkeys(classes))
            self.add_warning(
                "witness-instances", subj, spec, srec,
                f"{spec} has no witness; its only hypotheses are instances of classes treated "
                f"as inhabited ({names}), and no theorem shows them met together",
                "witness-instances")

    def totalised_warnings(self, subj: str, spec: str, srec: dict) -> None:
        """The totalisation warnings of a clause's proposition (`totalised_findings`). A warning
        about one application has the application's `fingerprint` and its first position `at`
        (with the statement's as `statement_fingerprint`), and its id ends in `@` and that
        position. A dismissal naming `at` and an application's fingerprint dismisses that
        application only: the one at `at` when its fingerprint matches, otherwise the one
        application with that fingerprint (it moved), and it lapses when the application at `at`
        changes. A dismissal without `at` (the form before applications were read one by one)
        dismisses every warning of its operation in the statement while the statement's
        fingerprint matches, and says so (`dismissed.form`: `statement`)."""
        fp = srec.get("fingerprint")
        items = totalised_findings(srec, spec, self.lean.get("decls") or {})
        targets: dict[tuple[str, str], tuple[str, dict]] = {}
        for d in self.dismissals:
            if d.get("code") != "totalised" or d.get("subject") != spec or "at" not in d:
                continue
            here = [(i["occurrence"]["at"][0], i["occurrence"]["fingerprint"]) for i in items
                    if i["trigger"] == d.get("trigger") and i["occurrence"]
                    and i["occurrence"]["at"]]
            same = [a for a, f in here if f and f == d.get("fingerprint")]
            if d["at"] in same:
                targets[(d["trigger"], d["at"])] = ("dismissed", d)
            elif len(same) == 1:
                targets.setdefault((d["trigger"], same[0]), ("dismissed", d))
            if d["at"] not in same and any(a == d["at"] for a, _ in here):
                targets.setdefault((d["trigger"], d["at"]), ("stale", d))
        for i in items:
            c, o = i["trigger"], i["occurrence"]
            extra, ofp = {}, None
            if o is not None:
                ofp = o.pop("fingerprint")
                extra = {"occurrences": [o], "at": o["at"][0] if o["at"] else None,
                         "statement_fingerprint": fp}
            elif i.get("incomplete"):
                extra = {"occurrences": [], "occurrences_complete": False}
            if o is not None and o.get("condition_state") == "established":
                # Every condition of the rule is supplied: the warning is resolved, with the
                # evidence in its occurrence. No status depends on it.
                extra["resolved"] = True
            self.add_warning("totalised", subj, spec, srec, i["message"], c, fingerprint=ofp,
                             legacy_only=o is not None, **extra)
            f = self.findings[-1]
            if o is None or not extra["at"]:
                continue
            f["id"] += "@" + extra["at"]
            hit = targets.get((c, extra["at"]))
            if hit and hit[0] == "dismissed":
                f.pop("dismissal_stale", None)
                f["dismissed"] = {"rationale": hit[1].get("rationale", ""),
                                  "by": hit[1].get("by", "")}
            elif hit and not f.get("dismissed"):
                f["dismissal_stale"] = True

    def add_warning(self, code, subj, name, rec, message, trigger, fingerprint=None,
                    legacy_only=False, **extra):
        """A warning, dismissed by a dismissal of its code, subject (`name`) and trigger whose
        fingerprint is the subject's current one (`rec`'s), and marked `dismissal_stale` when
        such a dismissal's fingerprint is another. The finding records `fingerprint` when given
        (what a dismissal of it records) and `rec`'s otherwise. With `legacy_only`, only
        dismissals without `at` are considered here, and one that applies is marked as naming
        the whole statement (`form`: `statement`)."""
        fp = rec.get("fingerprint")
        f = _finding("warning", code, subj, message, trigger=trigger,
                     fingerprint=fingerprint or fp,
                     signal="low" if trigger in LOW_SIGNAL else "normal", **extra)
        for d in self.dismissals:
            if d.get("code") == code and d.get("subject") == name and d.get("trigger") == trigger:
                if "at" in d and (legacy_only or code == "totalised"):
                    continue
                if d.get("fingerprint") == fp:
                    f["dismissed"] = {"rationale": d.get("rationale", ""), "by": d.get("by", "")}
                    if legacy_only:
                        f["dismissed"]["form"] = "statement"
                else:
                    f["dismissal_stale"] = True
        self.findings.append(f)

    # -- claims ---------------------------------------------------------------------------

    @staticmethod
    def claim_code(claim: dict, clauses: list[dict]) -> str:
        """The status of a claim from its clauses: a refuted original clause never hides another
        original clause."""
        scope = claim["scope"]
        if scope in OUT_OF_SCOPE:
            return "scope." + scope
        if any(c["state"] == "unchecked" for c in clauses):
            return ("definition" if scope == "definition" else "formal") + ".unchecked"
        if scope == "definition":
            if not clauses:
                return "definition.unstated"
            if not all(c["review"] in ("reviewed", "author-reviewed") for c in clauses):
                return "definition.review-pending"
            return ("definition.author-reviewed"
                    if any(c["review"] == "author-reviewed" for c in clauses)
                    else "definition.reviewed")
        if not clauses:
            return "formal.unspecified"
        originals = [c for c in clauses if not c.get("corrects")]
        if not originals:
            return "formal.malformed"
        refuted = [c for c in originals if c.get("refute_ok")]
        rest = [c for c in originals if not c.get("refute_ok")]
        rest_proved = all(c.get("accept_ok") for c in rest)
        if refuted:
            fixed = all(any(k.get("accept_ok") for k in clauses if k.get("corrects") == c["name"])
                        for c in refuted)
            return ("formal.refuted" + (".corrected" if fixed else "")
                    + ("" if rest_proved else ".open"))
        if rest_proved:
            if not all(c["review"] in ("reviewed", "author-reviewed") for c in rest):
                return "formal.review-pending"
            return ("formal.author-reviewed"
                    if any(c["review"] == "author-reviewed" for c in rest)
                    else "formal.accepted")
        return "formal.open"

    @staticmethod
    def claim_status(claim: dict, clauses: list[dict]) -> str:
        # The words of each status code are defined once, in status.py.
        return fields(Assessor.claim_code(claim, clauses))["status"]

    def blockers(self, claim: dict, clauses: list[dict]) -> list[str]:
        """Why the claim is not accepted, in plain words, most basic first: one line per reason,
        saying which clauses it affects. Empty for an accepted claim whose proofs were replayed,
        and for a claim out of scope."""
        if claim["scope"] in OUT_OF_SCOPE:
            return []
        if any(c["state"] == "unchecked" for c in clauses):
            return ["the Lean project was not checked in this build"]
        out = []
        if not claim.get("scope_reviewed", True):
            out.append("its scope was set by the automatic first pass and not checked by reading")
        if not clauses:
            out.append("no Lean proposition has been written for it" if claim["scope"] == "formal"
                       else "no Lean definition has been named for it")
        n = len(clauses)
        reasons: dict[str, list[str]] = {}

        def add(reason, clause):
            reasons.setdefault(reason, []).append(clause["name"])

        defs: dict[str, str] = {}
        shadowed: dict[str, dict] = {}
        for c in clauses:
            st = c["state"]
            if st == "unspecified":
                add("no Lean proposition has been written", c)
            elif st == "open":
                failed = [e for k in ("accept", "refute") if c["checks"].get(k)
                          and not c["checks"][k]["ok"] for e in c["checks"][k]["errors"]]
                add("its proof fails a check: " + ", ".join(failed) if failed
                    else "the proposition has no proof yet", c)
            elif st == "refuted":
                add("the printed statement is false: a theorem proves its negation", c)
            if c.get("spec") and c.get("spec_review"):
                srs = c["spec_review"]["state"]
                if srs == "author-reviewed":
                    add("the proposition was reviewed only by the author of the statements", c)
                elif srs == "pending":
                    add("the proposition has no review", c)
                elif srs == "stale" and c["spec_review"].get("why") == "shadowed":
                    add("the proposition's review " + self._shadowed_words(c["spec_review"]), c)
                elif srs == "stale":
                    add({"source-changed": "the paper's text changed after the proposition's "
                                           "last review",
                         "source-unread": "the proposition's last review did not read this "
                                          "claim's passage",
                         "source-unrecorded": "the proposition was reviewed before source pins "
                                              "were recorded",
                         "source-notation-unrecorded": "the proposition's last review did not "
                                                       "record the definitions of the notation "
                                                       "macros this claim's passage uses",
                         "source-unpinned": (
                             f"{self.unpinned_note(c['spec_review'].get('source_claim'))}; "
                             "the proposition's review counts only once the passage is pinned "
                             "again and read"),
                         "no-reading": "the proposition's review marker records no reading "
                                       "(no review text)"}.get(
                        c["spec_review"].get("why"),
                        "the proposition changed after its last review"), c)
            for d, r in (c.get("def_reviews") or {}).items():
                why = r.get("why")
                defs[d] = why if r["state"] == "stale" and why in (
                    "source-changed", "source-unread", "source-unrecorded",
                    "source-notation-unrecorded", "source-unpinned", "no-reading",
                    "shadowed") else r["state"]
                if defs[d] == "shadowed":
                    shadowed[d] = r
            if c.get("witness") and not c.get("witness_ok"):
                add("the witness that the hypotheses can be met fails its check", c)
            if any(not r["discharged"] for r in c.get("regimes", [])):
                add("a regime the paper intends is not shown to be covered", c)
            rp = c["checks"].get("replay")
            if rp and rp["state"] != "pass" and st in ("proved", "refuted"):
                add("Independent replay: not recorded (" + rp["detail"] + ")", c)
        for reason, names in reasons.items():
            if n == 1:
                out.append(reason)
            elif len(names) == n:
                out.append(f"{reason} (all {n} clauses)")
            elif reason.startswith("the printed statement is false") or len(names) <= 2:
                out.append(f"{reason}: " + "; ".join(f"“{x}”" for x in names))
            else:
                out.append(f"{reason} ({len(names)} of {n} clauses)")
        counts: dict[str, int] = {}
        for state in defs.values():
            counts[state] = counts.get(state, 0) + 1
        for state, words in (("pending", "have no review"),
                             ("stale", "changed after their review"),
                             ("source-changed", "have a paper text that changed after their "
                                                "review"),
                             ("source-unread", "have a review that did not read their passage"),
                             ("source-unpinned", "have a passage the manuscript no longer "
                                                 "matches: their review counts only once it "
                                                 "is pinned again and read"),
                             ("source-unrecorded", "were reviewed before source pins were "
                                                   "recorded"),
                             ("no-reading", "have a review marker that records no reading"),
                             ("source-notation-unrecorded", "have a review that did not record "
                                                            "the definitions of their notation"),
                             ("author-reviewed", "were reviewed only by the author")):
            if counts.get(state):
                out.append(f"{counts[state]} definition{'s' if counts[state] > 1 else ''} its "
                           f"meaning depends on {words}")
        # A review that a later marker shadows is named with both markers: the maintainer acts
        # on them, not on the definition.
        for d, r in shadowed.items():
            if defs[d] == "shadowed":
                out.append(f"the review of the definition {d} " + self._shadowed_words(r))
        if claim["scope"] == "definition" and self.claim_code(claim, clauses) != "definition.reviewed" and not out:
            out.append("its definitions are not independently reviewed")
        return list(dict.fromkeys(out))

    def step_review(self, claim: dict) -> dict:
        """A proof step's own review, from its `step-review` markers: recorded beside its status,
        never an input to it (`steps.py`)."""
        from .steps import is_step, marker_review
        region = ((self.tex or {}).get(claim["paper"], {}).get("regions") or {}).get(claim["id"])
        if not is_step(claim, region):
            return {}
        marks = [r for r in self.reviews if r.target == "step" and r.name == claim["id"]]
        # A step whose passage the manuscript no longer matches has no current reading.
        sha = None if claim["id"] in self.unpinned() else claim.get("source_sha256")
        return {"step_review": marker_review(marks, claim["id"], sha, self.authors)}

    def run(self) -> dict:
        claims = []
        for c in self.inv["claims"]:
            clauses = [self.clause(c, cl, k) for k, cl in enumerate(c.get("clauses", []))]
            state = fields(self.claim_code(c, clauses))
            claims.append({"id": c["id"], **state, "clauses": clauses,
                           "blockers": self.blockers(c, clauses), **self.step_review(c)})
        self.inventory_checks()
        self.bare_marker_checks()
        if self.lean:
            for v in self.lean.get("layering", []):
                self.findings.append(_finding(
                    "violation", "layering", v["module"],
                    f"the specification module {v['module']} imports {v['imports']}"))
            self.module_doc_checks()
            self.review_citation_checks()
        gates = self.gates(claims)
        out = {"claims": claims, "findings": self.findings, "gates": gates}
        if self.unlisted_declarers:
            # What `check --fix-modules` adds to `modules`; configuration advice, not a status.
            out["unlisted_modules"] = dict(sorted(self.unlisted_declarers.items()))
        return out

    def bare_marker_checks(self):
        """An obligation for each declaration whose last review marker has no review text
        (`has_reading`), with the marker's file and line: a marker records a reading, and one
        without text, copied between files say, records none. Such a marker never counts as a
        review (`review_state`)."""
        last: dict[tuple[str, str], Review] = {}
        for r in self.reviews:
            if r.target in ("spec", "def"):
                last[(r.target, r.name)] = r
        for (target, name), r in last.items():
            if not self.has_reading(r):
                kind = "proposition" if target == "spec" else "definition"
                self.findings.append(_finding(
                    "obligation", "review-without-reading", name,
                    f"{r.file}:{r.line}: the review marker of the {kind} {name} records no "
                    "reading: no review text precedes it", file=r.file, line=r.line))

    def module_doc_checks(self):
        """A warning for each name a module docstring of the project lists that nothing
        declares: prose that advertises a result the project does not contain. A name of a
        module the probe did not load is looked up in the sources (`undeclared_doc_names`), and
        a dependency's docstrings are its own audit's. It never changes a status, and an
        auditor can dismiss it (code `module-doc-name`, the module as subject, the name as
        trigger)."""
        from .moddocs import stale_doc_fingerprint, stale_doc_message, stale_doc_names
        from .source_names import undeclared_doc_names
        lean_root = getattr(self.cfg, "lean_root", None)
        docs = stale_doc_names(self.lean.get("moddocs", []), lean_root)
        if lean_root is not None:
            # The sources are searched only for names that resolve to nothing; a short name
            # that reaches a module or a namespace stays reported.
            plain = [d for d in docs if d.get("kind", "none") == "none"]
            found = {id(d) for d in plain} - {id(d) for d in undeclared_doc_names(plain, lean_root)}
            docs = [d for d in docs if id(d) not in found]
        for d in docs:
            self.add_warning("module-doc-name", d["module"], d["module"],
                             {"fingerprint": stale_doc_fingerprint(d)},
                             stale_doc_message(d), d["name"])
            self.findings[-1].update(file=d["file"], line=d["line"])

    def review_citation_checks(self):
        """A warning for each name or path cited in backticks by the review files that nothing
        resolves (`review_citations.py`), with its file and line; a violation when the
        configuration says `review_citations_strict`. The warning never changes a status, and
        an auditor can dismiss it (code `review-citation`, the review file as subject, the
        token as trigger)."""
        from . import review_citations as rc
        files = getattr(self.cfg, "reviews", None)
        root = getattr(self.cfg, "root", None)
        if not files or root is None:
            return
        cites = rc.citations(files, root, getattr(self.cfg, "review_citations_ignore", None))
        lean_root = getattr(self.cfg, "lean_root", None) or root
        bases = [root] + ([lean_root] if not lean_root.is_relative_to(root) else [])
        seen = set()
        for c in rc.unresolved(cites, self.lean.get("names"), bases):
            if (c["file"], c["token"]) in seen:
                continue
            seen.add((c["file"], c["token"]))
            if getattr(self.cfg, "review_citations_strict", False):
                self.findings.append(_finding("violation", "review-citation", c["file"],
                                              rc.message(c), trigger=c["token"],
                                              file=c["file"], line=c["line"]))
            else:
                self.add_warning("review-citation", c["file"], c["file"],
                                 {"fingerprint": rc.fingerprint(c)}, rc.message(c), c["token"])
                self.findings[-1].update(file=c["file"], line=c["line"])

    # -- gates ----------------------------------------------------------------------------

    def gates(self, claims: list[dict]) -> dict:
        ids = {c["id"]: c for c in self.inv["claims"]}
        violations = [f for f in self.findings if f["tier"] == "violation"]
        out = {}
        for paper in self.cfg.papers:
            pid = paper.id
            rows = [c for c in claims if ids[c["id"]]["paper"] == pid]
            mine = [f for f in violations if f["subject"].split("#")[0] in
                    {r["id"] for r in rows} or f["subject"].split(":")[0] == pid
                    or ":" not in f["subject"].split("#")[0]]
            consistency = [f["message"] for f in mine]
            reasons = []
            t = (self.tex or {}).get(pid, {})
            source = t.get("mode") or "none"
            if source == "pdf":
                reasons += self._pdf_source(pid, t)
            elif source != "latex":
                reasons.append("sources: manuscript source not compiled, source hashes unchecked")
            if self.lean is None:
                reasons.append("lean: the Lean project was not checked")
            reasons += [f"consistency: {m}" for m in consistency]
            if not rows:
                reasons.append(f"inventory: no claims for paper {pid}")
            for r in rows:
                e = ids[r["id"]]
                if not e.get("scope_reviewed", False):
                    reasons.append(f"{r['id']}: scope decision ({e['scope']}) not reviewed")
                if e["scope"] in OUT_OF_SCOPE:
                    continue
                if e["scope"] == "definition":
                    if r["status_code"] != "definition.reviewed":
                        reasons.append(f"{r['id']}: {r['status']}")
                    continue
                if r["status_code"] != "formal.accepted":
                    reasons.append(f"{r['id']}: {r['status']}")
                for c in r["clauses"]:
                    if c.get("refute_ok"):
                        reasons.append(f"{r['id']}: printed clause refuted, unresolved in the "
                                       f"manuscript: {c['name']}")
                    if c.get("witness") and not c.get("witness_ok"):
                        reasons.append(f"{r['id']}: witness fails: {c['name']}")
            names = sorted({c["accept"] for r in rows for c in r["clauses"] if c.get("accept")})
            comparator = bool(names) and all(self.replay(n)["state"] == "pass" for n in names)
            if not comparator:
                reasons.append("comparator: no successful kernel replay covering every proof "
                               "of the paper")
            out[pid] = {"source": source,
                        **({"source_note": "PDF source; statement positions are approximate. "
                            "Coverage is checked against detected headings, not guaranteed complete."} if source == "pdf" else {}),
                        "consistency": {"pass": not consistency, "failures": consistency},
                        "release": {"pass": not reasons, "reasons": reasons},
                        "comparator": comparator}
        return out

    def _pdf_source(self, pid: str, t: dict) -> list[str]:
        """Why a paper whose source is a PDF does not meet the gate's source condition: the PDF
        is pinned by the configuration (`pdf_sha256`) and matches it, and every claim in scope
        is found in it (by its heading, or placed by hand in `anchors.json`)."""
        out = []
        pinned, actual = t.get("pdf_pinned"), t.get("pdf_sha256")
        if not pinned:
            out.append("sources: the paper is a PDF and its hash is not pinned (pdf_sha256 in "
                       "machinechecked.toml), so it is not checked")
        elif pinned != actual:
            out.append(f"sources: the PDF differs from the one pinned (sha256 {str(actual)[:12]}, "
                       f"pinned {pinned[:12]})")
        manual = t.get("manual_anchors") or {}
        for c in self.inv["claims"]:
            if c["paper"] != pid or c["scope"] in OUT_OF_SCOPE:
                continue
            if c["id"] not in manual and match_anchor(c, t.get("anchors", [])) is None:
                out.append(f"sources: {c['id']} ({c.get('number') or 'unnumbered'}) is not found "
                           "in the PDF; place it by hand in anchors.json")
        return out

    # -- inventory against the compiled paper ---------------------------------------------

    def inventory_checks(self):
        """Check coverage against the detected paper statements, and LaTeX source pins."""
        for pid, t in (self.tex or {}).items():
            if t.get("mode") == "pdf":
                claims = [c for c in self.inv["claims"] if c["paper"] == pid]
                for anchor in t.get("anchors", []):
                    if not any(match_anchor(c, [anchor]) is not None for c in claims):
                        label = f"{anchor['env'].capitalize()} {anchor.get('number', '')}"
                        self.findings.append(_finding(
                            "violation", "inventory-gap",
                            f"{pid}:{anchor['env']}:{anchor.get('number', '')}:{anchor['id']}",
                            f"{label} is detected in the PDF but not in the inventory"))
                continue
            if t.get("mode") != "latex":
                continue
            anchors = t["anchors"]
            matched = set()
            for c in [c for c in self.inv["claims"] if c["paper"] == pid]:
                line = line_location(c)
                if line is not None:
                    region = (t.get("regions") or {}).get(c["id"], {})
                    if c.get("source_hash_scheme") not in SOURCE_SCHEMES:
                        self.findings.append(_finding(
                            "violation", "source-hash-scheme", c["id"],
                            f"{c['location']}: source regions must be pinned at the original "
                            "revision (machinechecked inventory regions --paper "
                            f"{pid}); then rebuild"))
                    elif c["id"] in self.unpinned():
                        self.findings.append(_finding(
                            "violation", "source-changed", c["id"],
                            self.unpinned()[c["id"]]))
                    self.region_advice(c, region)
                    macros = region.get("macros") or []
                    if macros:
                        # One warning per passage. Its trigger is the set of macros, so a
                        # dismissal (tied to the passage's digest) reopens when another macro
                        # defined outside the passage comes into use.
                        names = " ".join(m["macro"] for m in macros)
                        where = "; ".join(f"{m['macro']} at {', '.join(m['defined'])}"
                                          for m in macros)
                        self.add_warning(
                            "source-macro-unpinned", c["id"], c["id"],
                            {"fingerprint": c.get("source_sha256")},
                            f"the source region at {c['location']} uses macros defined outside "
                            f"it ({where}); a change to those definitions does not change the "
                            "pin. Pin the definitions whose values are part of the claim "
                            "(machinechecked inventory rebound --macro NAME), and list the "
                            "notation in notation_macros", names)
                    continue
                a = match_anchor(c, anchors)
                if a is None:
                    if c.get("kind") in t.get("envs", []):
                        self.findings.append(_finding(
                            "violation", "inventory-unanchored", c["id"],
                            f"{c.get('number', c['id'])} is not found in the compiled paper"))
                    continue
                matched.add(a["id"])
                if c["id"] in self.unpinned():
                    self.findings.append(_finding(
                        "violation", "source-changed", c["id"], self.unpinned()[c["id"]]))
            for a in anchors:
                if a["id"] not in matched:
                    self.findings.append(_finding(
                        "violation", "inventory-gap", f"{pid}:{a.get('label') or a['env']}",
                        f"{a['env'].capitalize()} {a.get('number')} ({a['file']}:{a['line']}) "
                        f"is in the paper but not in the inventory"))

    def region_advice(self, claim: dict, region: dict):
        """A warning for each way the claim's source region may not hold its text
        (`source_regions.advice`): a label line, a region that starts or ends inside a sentence,
        one that runs into another section, one that cuts an environment. It names the passage likely meant, never changes a
        status, and an auditor can dismiss it (code `source-region`, the claim as subject, the
        kind as trigger); a dismissal lapses when the region's text changes."""
        from .source_regions import SCHEME, advice_message
        # The digest of the claim's own passage (a pin of several passages records it apart).
        passage = region.get("passage_sha256") or region.get("sha256")
        for a in region.get("advice") or []:
            self.add_warning("source-region", claim["id"], claim["id"],
                             {"fingerprint": f"{SCHEME}:{passage}"},
                             advice_message(claim["id"], region, a), a["kind"])
            if a.get("suggested"):
                self.findings[-1]["suggested"] = a["suggested"]


def unpinned_passages(inventory: dict, tex: dict | None) -> dict[str, str]:
    """The claims whose passage in the manuscript no longer matches their pin, each with the
    message of the source check's finding (`source-changed`), which says where it differs. Only a paper read from its LaTeX
    source is compared. A line-located claim is compared by its region (each further passage
    and macro definition included); a statement environment by the digest of its text. A pin
    under a scheme the check does not accept is reported apart (`source-hash-scheme`) and is not
    listed.

    A review reads the paper's text, so a reading of such a passage does not count until the
    passage is pinned again and read at the new pin (`Assessor._read_one`)."""
    out: dict[str, str] = {}
    for c in inventory.get("claims", []):
        t = (tex or {}).get(c.get("paper")) or {}
        if t.get("mode") != "latex":
            continue
        if line_location(c) is not None:
            if c.get("source_hash_scheme") not in SOURCE_SCHEMES or source_matches(c, t):
                continue
            region = (t.get("regions") or {}).get(c["id"], {})
            where = changed_line(c, region) if region else None
            out[c["id"]] = f"the source region at {c['location']} " + (region.get("error") or (
                "is missing; rebuild the source evidence" if not region else
                "differs from the frozen source region" + (f": {where}" if where else "")))
            continue
        a = match_anchor(c, t.get("anchors") or [])
        if a and c.get("source_sha256") and a.get("source_sha256") and \
                c["source_sha256"] != a["source_sha256"]:
            out[c["id"]] = (f"the source of {c.get('number', c['id'])} differs from the frozen "
                            "inventory")
    return out


def line_location(claim: dict) -> int | None:
    """The line of a claim recorded as `<file>:<line>`, else None."""
    loc = claim.get("location") or ""
    head, _, tail = loc.rpartition(":")
    return int(tail) if head and tail.isdigit() else None


def match_anchor(claim: dict, anchors: list[dict]) -> dict | None:
    pid = claim["paper"]
    cid = claim["id"]
    for a in anchors:
        lab = a.get("label")
        if lab and (lab == claim.get("label") or lab == cid or f"{pid}:{lab}" == cid):
            return a
    for a in anchors:
        if a.get("number") and claim.get("number") == f"{a['env'].capitalize()} {a['number']}":
            return a
    return None
