/-!
# The ProofLens probe

Body of the probe that `prooflens probe` runs inside a Lean project. The CLI prepends
`import Lean` and the project's modules and runs the result with `lake env lean`, so this file
has no imports of its own and is not built as part of any library.

Input: the JSON query named by `PROOFLENS_QUERY`. Output: JSON lines written to the file named
by `PROOFLENS_OUT`, one record per request and one per declaration of the definition closure.

For a specification the record holds two representations of the proposition:

* the verification representation: the declaration, its axioms, the constants it uses, its
  structural hashes (`legacy_hash`, a 128-bit structural hash kept for compatibility with
  existing review markers, and `canon`, a canonical serialisation the CLI hashes with SHA-256);
* the inspection representation: the body of the definition split into a quantifier prefix
  (universal variables, hypotheses, instances, existential witnesses) and a conclusion, each
  pretty-printed with the constants it mentions marked for navigation.
-/

open Lean Meta Elab

namespace ProofLensProbe

/-! ## The query -/

structure Request where
  kind : String
  name : String
  spec : Option String := none
  /-- For `apps`: the declarations to look in; every declaration of the project if none. -/
  callers : Option (Array String) := none
  deriving FromJson, Inhabited

structure Query where
  scope_roots : Array String
  spec_prefix : String
  accept_prefix : String
  allowed_axioms : Array String
  requests : Array Request
  /-- Each request's heartbeat budget, in thousands as `maxHeartbeats`; Lean's default if none. -/
  max_heartbeats : Option Nat := none
  deriving FromJson, Inhabited

/-- Runs `x` with a heartbeat budget of `n` thousand heartbeats when one is given. -/
def withBudget (n? : Option Nat) (x : MetaM α) : MetaM α :=
  match n? with
  | some n => withTheReader Core.Context (fun c => { c with maxHeartbeats := n * 1000 }) x
  | none => x

/-! ## Environment helpers -/

def moduleOf (env : Environment) (n : Name) : Name :=
  match env.getModuleIdxFor? n with
  | some idx => env.header.moduleNames[idx.toNat]!
  | none => `«this file»

def inScope (roots : Array Name) (env : Environment) (n : Name) : Bool :=
  roots.contains (moduleOf env n).getRoot

def kindOf : ConstantInfo → String
  | .thmInfo _ => "theorem" | .defnInfo _ => "def" | .inductInfo _ => "inductive"
  | .ctorInfo _ => "ctor" | .opaqueInfo _ => "opaque" | .recInfo _ => "rec"
  | .axiomInfo _ => "axiom" | .quotInfo _ => "quot"

def rangeJson (n : Name) : MetaM Json := do
  match ← findDeclarationRanges? n with
  | some r => return Json.mkObj [("line", r.range.pos.line), ("end_line", r.range.endPos.line)]
  | none => return Json.null

/-! ## Proof erasure and fingerprints -/

/-- The expression with every proof replaced by one constant, so that hashes see statements and
data only. -/
def erase (e : Expr) : MetaM Expr := do
  let e ← instantiateMVars e
  transform e (pre := fun x => do
    if x.isFVar || x.isBVar || x.isSort then return .continue
    let p ← try isProof x catch _ => pure false
    if p then return .done (mkConst `«erased proof»)
    return .continue)

/-- A 64-bit structural hash, blind to binder
names and metadata; its form is fixed so that existing review markers keep matching. -/
partial def deepHash (e : Expr) : StateM (Std.HashMap Expr UInt64) UInt64 := do
  if let some h := (← get)[e]? then return h
  let h ← match e with
    | .bvar i => pure (mixHash 11 (hash i))
    | .fvar i => pure (mixHash 13 (hash i.name.toString))
    | .mvar i => pure (mixHash 17 (hash i.name.toString))
    | .sort l => pure (mixHash 19 (hash (toString l)))
    | .const n ls => pure (mixHash 23 (mixHash (hash n.toString) (hash (toString ls))))
    | .lit (.natVal k) => pure (mixHash 29 (hash k))
    | .lit (.strVal t) => pure (mixHash 31 (hash t))
    | .mdata _ b => deepHash b
    | .app f a => do pure (mixHash 37 (mixHash (← deepHash f) (← deepHash a)))
    | .lam _ t b bi => do
      pure (mixHash 41 (mixHash (hash (toString (repr bi)))
        (mixHash (← deepHash t) (← deepHash b))))
    | .forallE _ t b bi => do
      pure (mixHash 43 (mixHash (hash (toString (repr bi)))
        (mixHash (← deepHash t) (← deepHash b))))
    | .letE _ t v b _ => do
      pure (mixHash 47 (mixHash (← deepHash t) (mixHash (← deepHash v) (← deepHash b))))
    | .proj s i b => do
      pure (mixHash 53 (mixHash (hash s.toString) (mixHash (hash i) (← deepHash b))))
  modify (·.insert e h)
  return h

/-- The first `n` characters of `s`. (`String.take` returns a slice on some Lean versions and a
string on others; this is the same on all.) -/
def prefixOf (s : String) (n : Nat) : String :=
  (s.toList.take n).foldl String.push ""

def hex (h : UInt64) : String :=
  let s := (Nat.toDigits 16 h.toNat).foldl String.push ""
  "".pushn '0' (16 - s.length) ++ s

/-- State of the canonical serialisation: the index of every node already emitted. -/
structure CanonState where
  ids : Std.HashMap Expr Nat := {}
  lines : Array String := #[]

/-- Canonical serialisation of an expression as a table of shared nodes, in post-order. Binder
names and metadata are omitted; binder kinds, constants, universe levels and literals are kept.
The table form keeps the size linear in the number of distinct subterms. -/
partial def canon (e : Expr) : StateM CanonState Nat := do
  if let some i := (← get).ids[e]? then return i
  let line ← match e with
    | .bvar i => pure s!"bvar {i}"
    | .fvar i => pure s!"fvar {i.name}"
    | .mvar i => pure s!"mvar {i.name}"
    | .sort l => pure s!"sort {l}"
    | .const n ls => pure s!"const {n} {ls}"
    | .lit (.natVal k) => pure s!"nat {k}"
    | .lit (.strVal t) => pure s!"str {(toJson t).compress}"
    | .mdata _ b => return ← canon b
    | .app f a => do pure s!"app {← canon f} {← canon a}"
    | .lam _ t b bi => do pure s!"lam {repr bi} {← canon t} {← canon b}"
    | .forallE _ t b bi => do pure s!"pi {repr bi} {← canon t} {← canon b}"
    | .letE _ t v b _ => do pure s!"let {← canon t} {← canon v} {← canon b}"
    | .proj s i b => do pure s!"proj {s} {i} {← canon b}"
  let s ← get
  let i := s.lines.size
  set ({ ids := s.ids.insert e i, lines := s.lines.push line } : CanonState)
  return i

def canonString (ty : Expr) (val : Option Expr) : String :=
  let act : StateM CanonState (Nat × Option Nat) := do
    let t ← canon ty
    let v ← match val with | some v => some <$> canon v | none => pure none
    return (t, v)
  let ((t, v), s) := act.run {}
  let root := match v with | some v => s!"root {t} {v}" | none => s!"root {t}"
  "\n".intercalate (s.lines.push root).toList

/-- Fingerprint data of a constant with its proofs erased, and the constants it uses. -/
def constPrint (ci : ConstantInfo) : MetaM (String × String × Array Name) := do
  let ty ← erase ci.type
  let mut used := ty.getUsedConstants
  let mut vh : UInt64 := 0
  let mut val : Option Expr := none
  match ci with
  | .defnInfo d =>
    let v ← erase d.value
    vh := (deepHash v).run' {}
    val := some v
    used := used ++ v.getUsedConstants
  | .inductInfo i => used := used ++ i.ctors.toArray
  | .ctorInfo c => used := used.push c.induct
  | _ => pure ()
  let lvls := " ".intercalate (ci.levelParams.map toString)
  let c := s!"levels {lvls}\n" ++ canonString ty val
  return (hex ((deepHash ty).run' {}) ++ hex vh, c, used)

/-! ## Pretty-printing with navigation -/

/-- Flatten tagged code into segments; a segment carries the constant it names (`ref`), or the
index of the statement's binder it refers to (`var`, a position in `vars`), when the innermost
subexpression around it is one. Each tagged subexpression is also recorded as the range of
segments it covers (`terms`, in printing order, an outer one before those inside it), so that the
reader can select a whole sub-term, with its position in the whole proposition (`root`, the
position of the printed expression, extended by the tag's own `subexprPos`): the identity of a
sub-term, which depends on the proposition only, not on how it is printed or split. -/
partial def segments (vars : Array FVarId) (root : SubExpr.Pos) (t : Widget.CodeWithInfos)
    (ref : Option (String × Json)) (acc : Array Json) (terms : Array (Nat × Nat × String)) :
    Array Json × Array (Nat × Nat × String) :=
  match t with
  | Widget.TaggedText.text s =>
    match ref with
    | some (k, v) => (acc.push (Json.mkObj [("t", s), (k, v)]), terms)
    | none => (acc.push (Json.mkObj [("t", s)]), terms)
  | Widget.TaggedText.append xs =>
    xs.foldl (fun (a, ts) x => segments vars root x ref a ts) (acc, terms)
  | Widget.TaggedText.tag info sub =>
    let r := match info.info.val.info with
      | .ofTermInfo ti => match ti.expr with
        | .const n _ => some ("ref", Json.str n.toString)
        | .fvar id => (vars.findIdx? (· == id)).map fun i => ("var", toJson i)
        | _ => none
      | _ => none
    let start := acc.size
    let slot := terms.size
    let id := toString (root.append info.subexprPos)
    let (acc', terms') := segments vars root sub r acc (terms.push (start, start, id))
    (acc', terms'.set! slot (start, acc'.size, id))

/-- The sub-terms worth selecting: those covering two segments or more, each range once (the
outermost tag of a range keeps it), and none for a very large term. -/
def termsJson (terms : Array (Nat × Nat × String)) : Json := Id.run do
  let mut out : Array Json := #[]
  let mut seen : Array (Nat × Nat) := #[]
  for (a, b, id) in terms do
    if b - a ≥ 2 && !seen.contains (a, b) then
      seen := seen.push (a, b)
      out := out.push (Json.mkObj [("from", toJson a), ("to", toJson b), ("id", Json.str id)])
  return Json.arr (if out.size > 3000 then #[] else out)

/-- The fields of a pretty-printed expression with navigable constants and binders; plain text
if tagging fails, and a marker if printing fails, so that one large term cannot stop the probe.
`root` is the position of `e` in the whole proposition (`id`). -/
def ppFields (e : Expr) (vars : Array FVarId := #[]) (root : SubExpr.Pos := .root) :
    MetaM (List (String × Json)) := do
  try
    -- The type of a bound variable is printed (`pp.funBinderTypes`): `∃ Φ : T, …` says what Φ
    -- is. The head of every application is tagged too (`pp.tagAppFns`), so that the function a
    -- term applies is a constant the reader can name. The text and the tagged code are printed
    -- with the same options.
    let typed := fun (o : Options) => o.setBool `pp.funBinderTypes true
    let code ← withOptions (fun o => (typed o).setBool `pp.tagAppFns true) (Widget.ppExprTagged e)
    let text := toString (← withOptions typed (ppExpr e))
    let (segs, terms) := segments vars root code none #[] #[]
    return [("text", Json.str text), ("segments", Json.arr segs), ("terms", termsJson terms),
      ("id", Json.str (toString root))]
  catch _ =>
    try
      return [("text", Json.str (toString (← ppExpr e)))]
    catch err =>
      return [("text", Json.str "(not printable)"),
        ("error", Json.str (toString (← err.toMessageData.toString)))]

def ppJson (e : Expr) (vars : Array FVarId := #[]) (root : SubExpr.Pos := .root) : MetaM Json :=
  return Json.mkObj (← ppFields e vars root)

def isExistsApp (e : Expr) : Option (Name × Expr) :=
  if e.isAppOfArity ``Exists 2 then
    match e.appArg! with
    | .lam n _ _ _ => some (n, e.appArg!)
    | _ => none
  else none

/-- The logical shape of a conclusion: a conjunction, disjunction, equivalence, negation,
implication, "for every" or "there is" as a tree whose leaves are pretty-printed propositions. A
quantifier inside the conclusion is a node (`forall`, `exists`) with its variable's name, type and
number, and its body as its one part. `vars` is
threaded through the tree, so that every witness has a variable of its own: two witnesses in
sibling parts never share one. `pos` is the position of `e` in the whole proposition; each
node and variable carries its own (`id`). Display only; it changes no record that is assessed. -/
partial def logicJson (vars : Array FVarId) (e : Expr) (pos : SubExpr.Pos) :
    MetaM (Json × Array FVarId) := do
  let op := if e.isAppOfArity ``And 2 then some "and"
    else if e.isAppOfArity ``Or 2 then some "or"
    else if e.isAppOfArity ``Iff 2 then some "iff" else none
  match op with
  | some o =>
    let (a, vars) ← logicJson vars e.appFn!.appArg! pos.pushAppFn.pushAppArg
    let (b, vars) ← logicJson vars e.appArg! pos.pushAppArg
    return (Json.mkObj [("op", o), ("id", Json.str (toString pos)),
      ("args", Json.arr #[a, b])], vars)
  | none =>
    if e.isAppOfArity ``Not 1 then
      let (a, vars) ← logicJson vars e.appArg! pos.pushAppArg
      return (Json.mkObj [("op", "not"), ("id", Json.str (toString pos)),
        ("args", Json.arr #[a])], vars)
    if let .forallE n t body bi := e then
      if (← isProp t) && !body.hasLooseBVars then
        -- An implication inside a part: its premise is a part of its own, not an assumption
        -- of the whole statement.
        let (a, vars) ← logicJson vars t pos.pushBindingDomain
        let (b, vars) ← logicJson vars body pos.pushBindingBody
        return (Json.mkObj [("op", "implies"), ("id", Json.str (toString pos)),
          ("args", Json.arr #[a, b])], vars)
      let tj ← ppJson t vars pos.pushBindingDomain
      return ← withLocalDecl n bi t fun x => do
        let idx := vars.size
        let (b, vars') ←
          logicJson (vars.push x.fvarId!) (body.instantiate1 x) pos.pushBindingBody
        return (Json.mkObj [("op", "forall"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString pos)), ("type", tj),
          ("args", Json.arr #[b])], vars')
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      -- The witness is bound by the predicate `fun x => …`, the second argument of `Exists`.
      let lam := pos.pushAppArg
      let tj ← ppJson t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let idx := vars.size
        let (b, vars') ←
          logicJson (vars.push x.fvarId!) (body.instantiate1 x) lam.pushBindingBody
        return (Json.mkObj [("op", "exists"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString lam)), ("type", tj),
          ("args", Json.arr #[b])], vars')
    | _ => return (Json.mkObj [("leaf", ← ppJson e vars pos)], vars)

/-! ## The inspection representation -/

/-- Split a proposition into its quantifier prefix and its conclusion. Universal binders are
`forall` (data), `hypothesis` (a proposition) or `instance`; existential binders are `exists`.
Definitions are not unfolded: the prefix is the one written in the specification. -/
partial def telescope (e : Expr) (acc : Array Json) (vars : Array FVarId := #[])
    (pos : SubExpr.Pos := .root) : MetaM (Array Json × Json) := do
  match e with
  | .forallE n t body bi =>
    let isHyp ← isProp t
    let role :=
      if bi.isInstImplicit then "instance" else if isHyp then "hypothesis" else "forall"
    let tj ← ppJson t vars pos.pushBindingDomain
    withLocalDecl n bi t fun x => do
      let hyps := (acc.filter fun j => j.getObjValD "role" == Json.str "hypothesis").size
      let nm := if n.hasMacroScopes || n.isAnonymous then s!"h{hyps + 1}"
        else n.toString
      -- What an instance supplies: a proposition (`[Nonempty E]`) or data (`[Inhabited E]`).
      let supplies := if isHyp then "proposition" else "data"
      let j := Json.mkObj [("role", role), ("name", nm), ("id", Json.str (toString pos)),
        ("type", tj), ("binder", binderStr bi), ("supplies", supplies)]
      telescope (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) pos.pushBindingBody
  | _ =>
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      let lam := pos.pushAppArg
      let tj ← ppJson t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let j := Json.mkObj [("role", "exists"), ("name", n.eraseMacroScopes.toString),
          ("id", Json.str (toString lam)), ("type", tj), ("binder", binderStr bi)]
        telescope (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) lam.pushBindingBody
    | _ =>
      -- The conclusion, with its logical shape when it has one (`logic`, display only).
      let fields ← ppFields e vars pos
      let (logic, _) ← logicJson vars e pos
      let shaped := (logic.getObjVal? "op").toOption.isSome
      return (acc, Json.mkObj (if shaped then fields ++ [("logic", logic)] else fields))
where
  binderStr : BinderInfo → String
    | .default => "explicit" | .implicit => "implicit"
    | .strictImplicit => "strict-implicit" | .instImplicit => "instance"

/-- Constants of the project that `e` uses directly. -/
def projectConsts (roots : Array Name) (e : Expr) : MetaM (Array String) := do
  let env ← getEnv
  return e.getUsedConstants.filter (inScope roots env) |>.map toString

/-! ## Records -/

def emit (h : IO.FS.Handle) (j : Json) : IO Unit := h.putStrLn j.compress

def declRecord (roots : Array Name) (n : Name) (ci : ConstantInfo) : MetaM (Json × Array Name) := do
  let env ← getEnv
  let (lh, c, used) ← constPrint ci
  let sig ← ppJson ci.type
  let value ← match ci with
    | .defnInfo d =>
      if (← isProp ci.type) then pure Json.null
      else ppJson d.value
    | _ => pure Json.null
  let doc ← findDocString? env n
  let j := Json.mkObj [
    ("record", "decl"), ("name", n.toString), ("kind", kindOf ci),
    ("module", (moduleOf env n).toString), ("range", ← rangeJson n),
    ("doc", match doc with | some d => Json.str d | none => Json.null),
    ("legacy_hash", lh), ("canon", c), ("signature", sig), ("value", value),
    ("uses", Json.arr ((used.filter fun u => inScope roots env u && !u.isInternal).map
      (Json.str ·.toString)))]
  return (j, used)

def emitClosure (h : IO.FS.Handle) (roots : Array Name) (root : Name) (used : Array Name)
    (seen : IO.Ref NameSet) : MetaM (Array String) := do
  let env ← getEnv
  let mut stack := used
  let mut members : Array String := #[]
  let mut visited : NameSet := {}
  while !stack.isEmpty do
    let n := stack.back!
    stack := stack.pop
    if visited.contains n || n == root then continue
    visited := visited.insert n
    unless inScope roots env n do continue
    let some c := env.find? n | continue
    members := members.push n.toString
    -- Each member has its own heartbeat budget: a closure can hold thousands.
    let (j, more) ← withCurrHeartbeats (declRecord roots n c)
    unless (← seen.get).contains n do
      seen.modify (·.insert n)
      emit h j
    stack := stack ++ more
  return members.qsort (· < ·)

def disallowed (allowed : Array Name) (axs : Array Name) : Array Name :=
  axs.filter (!allowed.contains ·)

def specRecord (h : IO.FS.Handle) (q : Query) (roots : Array Name) (seen : IO.Ref NameSet)
    (spec : Name) : MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? spec
    | emit h (Json.mkObj [("record", "spec"), ("name", spec.toString), ("errors", toJson #["missing"])])
  let mut errs : Array String := #[]
  unless ci matches .defnInfo _ do errs := errs.push "not-a-def"
  unless ci.type == .sort .zero do errs := errs.push "type-not-Prop"
  unless q.spec_prefix.toName.isPrefixOf (moduleOf env spec) do errs := errs.push "outside-spec-layer"
  let axs ← collectAxioms spec
  let bad := disallowed (q.allowed_axioms.map (·.toName)) axs
  unless bad.isEmpty do errs := errs.push s!"axioms={bad.toList}"
  let (j, used) ← declRecord roots spec ci
  let (binders, concl) ← match ci with
    | .defnInfo d => telescope d.value #[]
    | _ => pure (#[], Json.null)
  let exact ← match ci with
    | .defnInfo d => ppJson d.value
    | _ => pure Json.null
  let closure ← emitClosure h roots spec used seen
  let direct ← match ci with
    | .defnInfo d => projectConsts roots d.value
    | _ => pure #[]
  let consts := match ci with
    | .defnInfo d => d.value.getUsedConstants.map toString
    | _ => #[]
  emit h (Json.mkObj [("record", "spec"), ("name", spec.toString), ("errors", toJson errs),
    ("axioms", toJson (axs.map toString)), ("decl", j),
    ("binders", Json.arr binders), ("conclusion", concl), ("exact", exact),
    ("direct", toJson direct), ("consts", toJson consts), ("closure", toJson closure)])

def levelsMatch (ls : List Level) (params : List Name) : Bool :=
  let ps := ls.filterMap fun l => match l with | .param p => some p | _ => none
  ps.length == ls.length && ps.eraseDups.length == ps.length && ps.length == params.length
    && params.all ps.contains

/-- `accept`: the type is exactly the specification; `refute`: exactly its negation; `witness`:
any theorem of the acceptance layer. -/
def proofRecord (h : IO.FS.Handle) (q : Query) (kind : String) (thm : Name)
    (spec : Option Name) : MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? thm
    | emit h (Json.mkObj [("record", kind), ("name", thm.toString), ("errors", toJson #["missing"])])
  let mut errs : Array String := #[]
  unless ci matches .thmInfo _ do errs := errs.push "not-a-theorem"
  unless q.accept_prefix.toName.isPrefixOf (moduleOf env thm) do
    errs := errs.push "outside-accept-layer"
  match kind, spec with
  | "accept", some s =>
    match ci.type with
    | .const c ls => unless c == s && levelsMatch ls ci.levelParams do errs := errs.push "type-not-spec"
    | _ => errs := errs.push "type-not-spec"
  | "refute", some s =>
    match ci.type with
    | .app (.const ``Not []) (.const c _) => unless c == s do errs := errs.push "type-not-negated-spec"
    | .forallE _ (.const c _) (.const ``False []) _ =>
      unless c == s do errs := errs.push "type-not-negated-spec"
    | _ => errs := errs.push "type-not-negated-spec"
  | _, _ => pure ()
  let axs ← collectAxioms thm
  let bad := disallowed (q.allowed_axioms.map (·.toName)) axs
  unless bad.isEmpty do errs := errs.push s!"axioms={bad.toList}"
  let ty ← ppJson ci.type
  emit h (Json.mkObj [("record", kind), ("name", thm.toString),
    ("spec", match spec with | some s => Json.str s.toString | none => Json.null),
    ("errors", toJson errs), ("axioms", toJson (axs.map toString)),
    ("type", ty), ("module", (moduleOf env thm).toString), ("range", ← rangeJson thm),
    ("sorry", toJson (axs.contains ``sorryAx))])

/-- Whether a name is one a reader looks for: not generated by the compiler or elaborator. -/
def userFacing (n : Name) : Bool :=
  !n.isInternal && !(n.components.any fun c =>
    let s := c.toString
    s.startsWith "_" || s.startsWith "match_" || s.startsWith "proof_" || s == "eq_def"
      || s.startsWith "eq_" && (s.drop 3).all Char.isDigit)

/-- Every user-facing theorem, definition and type declared in the modules of `roots`: name,
kind, module, line, docstring and statement as text. -/
def indexRecords (h : IO.FS.Handle) (roots : Array Name) : MetaM Unit := do
  let env ← getEnv
  let names := env.header.moduleNames
  for i in [:names.size] do
    let mod := names[i]!
    unless roots.contains mod.getRoot do continue
    for n in env.header.moduleData[i]!.constNames do
      unless userFacing n do continue
      let some ci := env.find? n | continue
      let kind := match ci with
        | .thmInfo _ => some "theorem" | .defnInfo _ => some "def"
        | .inductInfo _ => some "inductive" | .opaqueInfo _ => some "opaque"
        | .axiomInfo _ => some "axiom" | _ => none
      let some k := kind | continue
      if k == "def" && (← isInstance n) then continue
      -- Each declaration printed has its own heartbeat budget: a project can hold tens of
      -- thousands, more than one budget prints.
      let ty ← withCurrHeartbeats do
        try pure (toString (← ppExpr ci.type)) catch _ => pure "(not printable)"
      let doc ← findDocString? env n
      emit h (Json.mkObj [("record", "index"), ("name", n.toString), ("kind", k),
        ("module", mod.toString), ("range", ← rangeJson n),
        ("doc", match doc with | some d => Json.str d | none => Json.null),
        ("type", if ty.length > 4000 then prefixOf ty 4000 ++ " …" else ty)])

/-! ## Names in module docstrings -/

def charsToString (s : List Char) : String :=
  s.foldl String.push ""

/-- The parts of `s` between occurrences of `c`. -/
def splitChars (c : Char) (s : List Char) : Array (List Char) :=
  let (done, cur) := s.foldl (fun (acc : Array (List Char) × List Char) x =>
    if x == c then (acc.1.push acc.2.reverse, []) else (acc.1, x :: acc.2)) (#[], [])
  done.push cur.reverse

/-- Whether a backticked piece of a docstring has the shape of a declaration name. -/
def nameLike (s : List Char) : Bool :=
  let ok := fun (c : Char) => c.isAlphanum || c == '_' || c == '\'' || c == '!' || c == '?'
    || c.toNat > 127
  match s with
  | [] => false
  | c :: _ => !c.isDigit && c != '.' && s.getLast? != some '.'
    && (splitChars '.' s).all (fun p => !p.isEmpty && p.all ok)

/-- Every backticked name in the docstrings of the modules of `roots` that is no declaration,
namespace or module: its module, its line, the heading it is under and whether it begins a list
item. A name is tried as written and inside each namespace the module declares into. -/
def moduleDocRecords (h : IO.FS.Handle) (roots : Array Name) : MetaM Unit := do
  let env ← getEnv
  let names := env.header.moduleNames
  for i in [:names.size] do
    let mod := names[i]!
    unless roots.contains mod.getRoot do continue
    let some docs := getModuleDoc? env mod | continue
    if docs.isEmpty then continue
    let mut declared : NameSet := {}
    let mut spaces : Array Name := #[]
    for c in env.header.moduleData[i]!.constNames do
      let u := privateToUserName c
      declared := declared.insert u
      let mut p := u.getPrefix
      while !p.isAnonymous do
        unless spaces.contains p do spaces := spaces.push p
        p := p.getPrefix
    let known := fun (n : Name) => env.contains n || declared.contains n || env.isNamespace n
      || (env.getModuleIdx? n).isSome
    for d in docs do
      let mut heading : List Char := []
      let mut fence := false
      -- Lean stores the text without its leading whitespace, so its first line is counted back
      -- from the closing `-/`.
      let mut line := d.declarationRange.endPos.line - (d.doc.toList.filter (· == '\n')).length
      for l in splitChars '\n' d.doc.toList do
        let t := l.dropWhile Char.isWhitespace
        if "```".toList.isPrefixOf t then
          fence := !fence
        else if !fence then
          if t.head? == some '#' then
            heading := (t.dropWhile (· == '#')).dropWhile Char.isWhitespace
          let item := t.length ≥ 2 && ['*', '-', '+'].contains t[0]! && t[1]! == ' '
          let parts := splitChars '`' l
          let mut k := 1
          while k + 1 < parts.size do
            let tok := parts[k]!
            if nameLike tok then
              let n := (splitChars '.' tok).foldl (fun n p => Name.str n (charsToString p))
                .anonymous
              unless known n || spaces.any (fun ns => known (ns ++ n)) do
                emit h (Json.mkObj [("record", "moddoc"), ("module", mod.toString),
                  ("line", toJson line), ("name", Json.str (charsToString tok)),
                  ("heading", Json.str (charsToString heading)),
                  ("item_lead", toJson (item && k == 1))])
            k := k + 2
        line := line + 1

/-- A theorem of a link: its statement split like a specification, and its axioms. -/
def linkRecord (h : IO.FS.Handle) (q : Query) (roots : Array Name) (seen : IO.Ref NameSet)
    (n : Name) : MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? n
    | emit h (Json.mkObj [("record", "link"), ("name", n.toString), ("errors", toJson #["missing"])])
  -- A theorem whose type is a closed proposition (a locked statement) shows that proposition.
  let stmt ← match ci.type with
    | .const c _ => match env.find? c with
      | some (.defnInfo d) => if d.type == .sort .zero then pure d.value else pure ci.type
      | _ => pure ci.type
    | _ => pure ci.type
  let (binders, concl) ← telescope stmt #[]
  let exact ← ppJson stmt
  let axs ← collectAxioms n
  let bad := disallowed (q.allowed_axioms.map (·.toName)) axs
  let (j, used) ← declRecord roots n ci
  let closure ← emitClosure h roots n used seen
  emit h (Json.mkObj [("record", "link"), ("name", n.toString), ("kind", kindOf ci),
    ("errors", toJson (if bad.isEmpty then #[] else #[s!"axioms={bad.toList}"])),
    ("axioms", toJson (axs.map toString)), ("sorry", toJson (axs.contains ``sorryAx)),
    ("decl", j), ("binders", Json.arr binders), ("conclusion", concl), ("exact", exact),
    ("closure", toJson closure)])

/-! ## Dependencies, proofs included

The closures above erase proofs, so that fingerprints see statements and data only. A `deps`
request answers a different question, what a declaration rests on: the constants its statement
mentions and, kept apart, those its value uses (a theorem's proof, a definition's body), without
erasing anything. It adds records of its own and changes none of the others. -/

/-- The constants a declaration's statement mentions, and those its value uses. -/
def statementAndValueConsts (ci : ConstantInfo) : Array Name × Array Name :=
  let value := match ci with
    | .defnInfo d => d.value.getUsedConstants
    | .thmInfo t => t.value.getUsedConstants
    | .opaqueInfo o => o.value.getUsedConstants
    | .inductInfo i => i.ctors.toArray
    | .ctorInfo c => #[c.induct]
    | _ => #[]
  (ci.type.getUsedConstants, value)

/-- One declaration reached from a `deps` root: what it is, how far from the root, and its own
statement and value dependencies, split into the project's (`roots`) and the rest. -/
def depNode (roots : Array Name) (n : Name) (ci : ConstantInfo) (depth : Nat) : MetaM Json := do
  let env ← getEnv
  let (st, va) := statementAndValueConsts ci
  let inside := fun (a : Array Name) => Json.arr ((a.filter (inScope roots env)).map (Json.str ·.toString))
  let outside := fun (a : Array Name) =>
    Json.arr ((a.filter (!inScope roots env ·)).map (Json.str ·.toString))
  -- Each declaration printed has its own heartbeat budget: a closure can hold thousands.
  let ty ← withCurrHeartbeats do
    try
      let f ← ppExpr ci.type
      pure (toString f)
    catch _ => pure "(not printable)"
  let doc ← findDocString? env n
  return Json.mkObj [("record", "depnode"), ("name", n.toString), ("kind", kindOf ci),
    ("module", (moduleOf env n).toString), ("range", ← rangeJson n),
    ("user_facing", toJson (userFacing n)), ("depth", toJson depth),
    ("doc", match doc with | some d => Json.str d | none => Json.null),
    ("type", if ty.length > 4000 then prefixOf ty 4000 ++ " …" else ty),
    ("statement_uses", inside st), ("value_uses", inside va),
    ("statement_external", outside st), ("value_external", outside va)]

/-- Every declaration of the project reachable from `root` through statements and values, each
once, at its least distance from the root, then a `deps` record with the root's axioms. -/
def depsRecords (h : IO.FS.Handle) (roots : Array Name) (root : Name) : MetaM Unit := do
  let env ← getEnv
  unless env.contains root do
    emit h (Json.mkObj [("record", "deps"), ("name", root.toString), ("errors", toJson #["missing"])])
    return
  let mut seen : NameSet := {}
  let mut queue : Array (Name × Nat) := #[(root, 0)]
  let mut i := 0
  let mut reached := 0
  while i < queue.size do
    let (n, d) := queue[i]!
    i := i + 1
    if seen.contains n then continue
    seen := seen.insert n
    let some ci := env.find? n | continue
    unless n == root || inScope roots env n do continue
    emit h (← depNode roots n ci d)
    reached := reached + 1
    let (st, va) := statementAndValueConsts ci
    for c in st ++ va do
      unless seen.contains c do
        if inScope roots env c then queue := queue.push (c, d + 1)
  let axs ← collectAxioms root
  emit h (Json.mkObj [("record", "deps"), ("name", root.toString), ("errors", Json.arr #[]),
    ("module", (moduleOf env root).toString), ("axioms", toJson (axs.map toString)),
    ("sorry", toJson (axs.contains ``sorryAx)), ("reached", toJson reached)])

/-- Every module of the environment with the modules it imports directly: what a record
extracted in this environment can depend on. -/
def moduleRecords (h : IO.FS.Handle) : CoreM Unit := do
  let env ← getEnv
  let names := env.header.moduleNames
  for i in [:names.size] do
    let imports := env.header.moduleData[i]!.imports.map (·.module.toString)
    emit h (Json.mkObj [("record", "module"), ("name", names[i]!.toString),
      ("imports", toJson imports)])

/-- Every module of the specification layer that imports a module of the acceptance layer. -/
def layering (h : IO.FS.Handle) (q : Query) : CoreM Unit := do
  -- Without both layers named (the zero-configuration view) there is no layering to check;
  -- every module would otherwise count as both layers and every import as a violation.
  if q.spec_prefix.isEmpty || q.accept_prefix.isEmpty then
    emit h (Json.mkObj [("record", "layering"), ("violations", Json.arr #[])])
    return
  let env ← getEnv
  let names := env.header.moduleNames
  let mut violations : Array Json := #[]
  for i in [:names.size] do
    let mod := names[i]!
    unless q.spec_prefix.toName.isPrefixOf mod do continue
    let mut seen : NameSet := {}
    let mut stack : Array Name := #[mod]
    while !stack.isEmpty do
      let m := stack.back!
      stack := stack.pop
      if seen.contains m then continue
      seen := seen.insert m
      if q.accept_prefix.toName.isPrefixOf m then
        violations := violations.push (Json.mkObj [("module", mod.toString), ("imports", m.toString)])
      let some idx := env.getModuleIdx? m | continue
      for imp in env.header.moduleData[idx.toNat]!.imports do
        stack := stack.push imp.module
  emit h (Json.mkObj [("record", "layering"), ("violations", Json.arr violations)])

/-! ## Uses and applications

`refs` reports, for every declaration of the project, the project's constants its statement
mentions and those its value uses (a proof, a definition's body): the reverse references of every
declaration follow from it. `apps` reports where one declaration is used and, inside each user's
value, every application of it: the actual argument supplied for each binder, the premise each
proof argument instantiates and where that proof comes from, and the conclusion obtained. The
arguments are read from the elaborated terms, never from the source text.

Both are bounded so that a large project stays fast: a value is entered only along subterms that
mention the declaration (each shared subterm examined once, at most `scanNodes` of them), at most
`appsPerUser` applications are described in each of at most `appsUsers` users, and a term larger
than `termNodes` is shown by its head constant only. What a bound leaves out is reported. -/

def scanNodes : Nat := 1000000
def appsUsers : Nat := 30
def appsPerUser : Nat := 8
def termNodes : Nat := 600

/-- The last component of a name. -/
def lastStr : Name → String
  | .str _ s => s | .num _ k => toString k | .anonymous => ""

/-- The inductive type a generated part of it (a constructor, recursor, projection or the lemmas
Lean derives for them) belongs to. -/
def partOf (env : Environment) (n : Name) : Option Name :=
  let p := n.getPrefix
  if p.isAnonymous then none else
  match env.find? n with
  | some (.ctorInfo c) => some c.induct
  | some (.recInfo _) => some p
  | _ =>
    if isAuxRecursor env n || isNoConfusion env n || (env.getProjectionFnInfo? n).isSome then
      some p
    else match env.find? p with
      | some (.ctorInfo c) => some c.induct
      | some (.inductInfo _) =>
        if ["sizeOf_spec", "noConfusionType", "ext", "ext_iff", "inj", "injEq"].contains
          (lastStr n) then some p else none
      | _ => none

/-- The declaration a reader knows a constant by: a generated constant (`foo.proof_1`, a
matcher, an equation lemma, a constructor's derived lemma) stands for the declaration it was
generated for, when that is a declaration. -/
partial def ownerOf (env : Environment) (n : Name) : Name :=
  let go := fun (m : Name) =>
    let rec strip (m : Name) : Name :=
      if m.isAnonymous then m
      else if !userFacing m then strip m.getPrefix
      else match partOf env m with
        | some o => if o == m then m else strip o
        | none => m
    strip m
  let o := go (privateToUserName n)
  if !o.isAnonymous && env.contains o then o else n

def valueOf : ConstantInfo → Option Expr
  | .defnInfo d => some d.value | .thmInfo t => some t.value | .opaqueInfo o => some o.value
  | _ => none

/-- What a declaration's value is to a reader. -/
def valueKind : ConstantInfo → String
  | .thmInfo _ => "proof" | .defnInfo _ => "definition body" | .opaqueInfo _ => "definition body"
  | _ => "none"

/-- The constants a declaration's statement mentions and those its value uses, computed once
per session. -/
abbrev UsedCache := IO.Ref (Std.HashMap Name (Array Name × Array Name))

/-- The number of leading `∀` of a type: the parameters a declaration's value begins with. -/
def arity : Expr → Nat
  | .forallE _ _ b _ => arity b + 1
  | .mdata _ b => arity b
  | _ => 0

/-- A value without the types of its leading `n` parameters, which repeat the statement. -/
def stripParams : Nat → Expr → Expr
  | n + 1, .lam _ _ b _ => stripParams n b
  | n + 1, .mdata _ b => stripParams (n + 1) b
  | _, e => e

def usedOf (cache : UsedCache) (n : Name) (ci : ConstantInfo) : IO (Array Name × Array Name) := do
  if let some r := (← cache.get)[n]? then return r
  let r := (ci.type.getUsedConstants, match valueOf ci with
    | some v => (stripParams (arity ci.type) v).getUsedConstants | none => #[])
  cache.modify (·.insert n r)
  return r

/-- Every constant declared in the modules of `roots`. -/
def projectConstants (roots : Array Name) : CoreM (Array Name) := do
  let env ← getEnv
  let mut out := #[]
  for i in [:env.header.moduleNames.size] do
    if roots.contains env.header.moduleNames[i]!.getRoot then
      out := out ++ env.header.moduleData[i]!.constNames
  return out

/-- For every declaration of the project, the project's constants its statement and its value
mention. -/
def refsRecords (h : IO.FS.Handle) (roots : Array Name) (cache : UsedCache) : MetaM Unit := do
  let env ← getEnv
  for n in ← projectConstants roots do
    let some ci := env.find? n | continue
    let (st, va) ← usedOf cache n ci
    let inside := fun (a : Array Name) =>
      Json.arr ((a.filter fun c => c != n && inScope roots env c).map (Json.str ·.toString))
    emit h (Json.mkObj [("record", "refs"), ("name", n.toString),
      ("owner", (ownerOf env n).toString), ("module", (moduleOf env n).toString),
      ("kind", kindOf ci), ("user_facing", toJson (userFacing n)),
      ("value_kind", valueKind ci), ("statement", inside st), ("value", inside va)])

/-- A binder around an occurrence inside a value: a `fun` (one of the declaration's own
parameters when it is one of the value's leading binders), a `let`, a `have` (a `fun` applied
to the proof of its premise) or a `∀`. Its type and value have loose bound variables for the
binders outside it. -/
structure Binder where
  name : Name
  type : Expr
  bi : BinderInfo
  value : Option Expr := none
  pos : SubExpr.Pos
  param : Bool := false
  kind : String
  deriving Inhabited

structure Occ where
  e : Expr
  pos : SubExpr.Pos
  binders : Array Binder

structure ScanState where
  memo : Std.HashMap Expr Bool := {}
  visited : Nat := 0
  occs : Array Occ := #[]
  /-- Some occurrence is not described: the budget of subterms or of applications ran out. -/
  cut : Bool := false

/-- Whether `e` mentions the constant `f`; each shared subterm is examined once. -/
partial def mentions (f : Name) (e : Expr) : StateM ScanState Bool := do
  match e with
  | .const n _ => return n == f
  | .app .. | .lam .. | .forallE .. | .letE .. | .mdata .. | .proj .. =>
    if let some b := (← get).memo[e]? then return b
    if (← get).visited ≥ scanNodes then
      modify fun s => { s with cut := true }
      return false
    modify fun s => { s with visited := s.visited + 1 }
    let b ← match e with
      | .app g a => do if ← mentions f g then pure true else mentions f a
      | .lam _ t b _ | .forallE _ t b _ => do
        if ← mentions f t then pure true else mentions f b
      | .letE _ t v b _ => do
        if ← mentions f t then pure true
        else if ← mentions f v then pure true else mentions f b
      | .mdata _ b | .proj _ _ b => mentions f b
      | _ => pure false
    modify fun s => { s with memo := s.memo.insert e b }
    return b
  | _ => return false

/-- The applications of `f` in `e` (at position `pos`, under binders `bs`), at most `cap`.
`params` counts the leading binders still to be read as the declaration's own parameters. -/
partial def collect (f : Name) (cap : Nat) (e : Expr) (pos : SubExpr.Pos) (bs : Array Binder)
    (params : Nat) : StateM ScanState Unit := do
  unless ← mentions f e do return
  if (← get).occs.size ≥ cap then
    modify fun s => { s with cut := true }
    return
  let record := modify fun (s : ScanState) => { s with occs := s.occs.push ⟨e, pos, bs⟩ }
  match e with
  | .const n _ => if n == f then record
  | .app .. =>
    let args := e.getAppArgs
    if e.getAppFn.consumeMData.isConstOf f then
      record
      for i in [:args.size] do
        collect f cap args[i]! (pos.pushNaryArg args.size i) bs 0
    else match e with
      | .app (.lam n t b bi) v =>
        collect f cap v pos.pushAppArg bs 0
        collect f cap t pos.pushAppFn.pushBindingDomain bs 0
        collect f cap b pos.pushAppFn.pushBindingBody
          (bs.push { name := n, type := t, bi, value := some v, pos := pos.pushAppFn,
                     kind := "have" }) 0
      | .app g a =>
        collect f cap g pos.pushAppFn bs 0
        collect f cap a pos.pushAppArg bs 0
      | _ => pure ()
  | .lam n t b bi =>
    -- The type of one of the declaration's own parameters repeats its statement.
    unless params > 0 do collect f cap t pos.pushBindingDomain bs 0
    collect f cap b pos.pushBindingBody
      (bs.push { name := n, type := t, bi, pos, param := params > 0, kind := "fun" }) (params - 1)
  | .forallE n t b bi =>
    collect f cap t pos.pushBindingDomain bs 0
    collect f cap b pos.pushBindingBody (bs.push { name := n, type := t, bi, pos, kind := "forall" }) 0
  | .letE n t v b _ =>
    collect f cap t pos.pushLetVarType bs 0
    collect f cap v pos.pushLetValue bs 0
    collect f cap b pos.pushLetBody
      (bs.push { name := n, type := t, bi := .default, value := some v, pos, kind := "let" }) 0
  | .mdata _ b => collect f cap b pos bs params
  | .proj _ _ b => collect f cap b pos.pushProj bs 0
  | _ => pure ()

/-- Runs `k` with the binders `bs` as local declarations of the context, and their variables. -/
def withBinders : List Binder → Array Expr → (Array Expr → MetaM α) → MetaM α
  | [], xs, k => k xs
  | b :: bs, xs, k => do
    let ty := b.type.instantiateRev xs
    match b.value with
    | some v => withLetDecl b.name ty (v.instantiateRev xs) fun x => withBinders bs (xs.push x) k
    | none => withLocalDecl b.name b.bi ty fun x => withBinders bs (xs.push x) k

/-- The number of nodes of `e`, counted without sharing, up to just past `cap`. -/
def sizeUpTo (e : Expr) (cap : Nat) : Nat := Id.run do
  let mut stack := #[e]
  let mut n := 0
  while !stack.isEmpty && n ≤ cap do
    let x := stack.back!
    stack := stack.pop
    n := n + 1
    match x with
    | .app f a => stack := (stack.push f).push a
    | .lam _ t b _ | .forallE _ t b _ => stack := (stack.push t).push b
    | .letE _ t v b _ => stack := ((stack.push t).push v).push b
    | .mdata _ b | .proj _ _ b => stack := stack.push b
    | _ => pure ()
  return n

/-- A term printed with its variables marked, or, when it is larger than `cap` nodes, its head
constant only. -/
def ppBounded (e : Expr) (vars : Array FVarId) (cap : Nat := termNodes) : MetaM Json := do
  if sizeUpTo e cap > cap then
    let head := match e.getAppFn.consumeMData with
      | .const c _ => Json.str c.toString | _ => Json.null
    return Json.mkObj [("text", Json.str "(a large term)"), ("large", toJson true),
      ("head", head)]
  withCurrHeartbeats (ppJson e vars)

def binderInfoStr : BinderInfo → String
  | .default => "explicit" | .implicit => "implicit"
  | .strictImplicit => "strict-implicit" | .instImplicit => "instance"

/-- Where the term `e` that supplies an argument comes from, as far as the term shows: one of
the caller's own hypotheses, parameters or instances; a hypothesis or fact introduced inside the
value; a theorem or definition applied there; a constructor; a projection of a structure; an
instance; or a term built in place. Transports (`Eq.mpr`, `cast`, `id`) are looked through and
named. `depth` bounds how far the origin of a part is followed. -/
partial def originJson (xs : Array Expr) (bs : Array Binder) (helper : Bool) (depth : Nat)
    (e : Expr) (through : Array Name := #[]) : MetaM Json := do
  let e := e.consumeMData
  let env ← getEnv
  let fn := e.getAppFn.consumeMData
  let nargs := e.getAppNumArgs
  let tail := (if through.isEmpty then [] else [("through", toJson (through.map toString))])
    ++ (if nargs > 0 && !(fn matches .const ..) then [("applied", toJson true)] else [])
  let sub := fun (x : Expr) => if depth == 0 then pure Json.null
    else originJson xs bs helper (depth - 1) x
  match fn with
  | .fvar _ =>
    match xs.findIdx? (· == fn) with
    | some j =>
      let b := bs[j]!
      let prop ← try isProp (← inferType fn) catch _ => pure false
      let kind :=
        if b.param then
          if helper then "helper parameter"
          else if b.bi.isInstImplicit then "caller instance"
          else if prop then "caller hypothesis" else "caller parameter"
        else if b.value.isSome then (if prop then "local fact" else "local definition")
        else if prop then "local hypothesis" else "local variable"
      let by_ ← match b.value with
        | some v => sub (v.instantiateRevRange 0 j xs)
        | none => pure Json.null
      return Json.mkObj ([("kind", Json.str kind), ("local", toJson j),
        ("name", Json.str b.name.eraseMacroScopes.toString), ("id", Json.str (toString b.pos)),
        ("binder", Json.str b.kind)] ++ (if by_.isNull then [] else [("by", by_)]) ++ tail)
    | none => return Json.mkObj ([("kind", Json.str "local hypothesis")] ++ tail)
  | .const c _ =>
    if (c == ``id || c == ``Eq.mpr || c == ``Eq.mp || c == ``cast) && nargs ≥ 2 then
      return ← originJson xs bs helper depth e.appArg! (through.push c)
    if c == ``Eq.ndrec && nargs == 6 then
      return ← originJson xs bs helper depth (e.getArg! 3) (through.push c)
    match env.find? c with
    | some (.ctorInfo ci) =>
      let parts ← if depth == 0 then pure #[] else
        (e.getAppArgs.extract ci.numParams nargs).filterMapM fun a => do
          if ← (try isProof a catch _ => pure false) then some <$> sub a else pure none
      return Json.mkObj ([("kind", Json.str "construction"), ("name", Json.str c.toString),
        ("parts", Json.arr parts)] ++ tail)
    | _ =>
      if let some info := env.getProjectionFnInfo? c then
        let of_ ← if nargs > info.numParams then sub (e.getArg! info.numParams)
          else pure Json.null
        return Json.mkObj ([("kind", Json.str "projection"), ("name", Json.str c.toString),
          ("field", Json.str (lastStr c)), ("of", of_)] ++ tail)
      if ← isInstance c then
        return Json.mkObj ([("kind", Json.str "instance"), ("name", Json.str c.toString)] ++ tail)
      let k := match env.find? c with
        | some (.thmInfo _) => "theorem application" | _ => "application"
      return Json.mkObj ([("kind", Json.str k), ("name", Json.str c.toString),
        ("owner", Json.str (ownerOf env c).toString)] ++ tail)
  | .proj s i b =>
    let field := ((getStructureFields env s)[i]?).map (·.toString) |>.getD (toString (i + 1))
    return Json.mkObj ([("kind", Json.str "projection"), ("structure", Json.str s.toString),
      ("field", Json.str field), ("of", ← sub b)] ++ tail)
  | .lam .. | .letE .. => return Json.mkObj ([("kind", Json.str "built in place")] ++ tail)
  | .lit _ => return Json.mkObj ([("kind", Json.str "literal")] ++ tail)
  | .mvar _ => return Json.mkObj ([("kind", Json.str "unassigned")] ++ tail)
  | _ => return Json.mkObj ([("kind", Json.str "other")] ++ tail)

/-- Where a data argument comes from: a variable of the context (as `originJson` says), a field
of a structure (not of a class instance), or a term built in the caller, with its head. -/
def termOrigin (xs : Array Expr) (bs : Array Binder) (helper : Bool) (e : Expr) : MetaM Json := do
  let e := e.consumeMData
  let env ← getEnv
  let fn := e.getAppFn.consumeMData
  let field := match fn with
    | .proj s .. => !isClass env s
    | .const c _ => match env.getProjectionFnInfo? c with
      | some info => !info.fromClass
      | none => false
    | _ => false
  if fn.isFVar || field then return ← originJson xs bs helper 1 e
  let head := match fn with | .const c _ => Json.str c.toString | _ => Json.null
  return Json.mkObj [("kind", Json.str "term"), ("head", head)]

/-- One application of `f`: each binder of `f`'s type paired with the argument supplied for it,
the premise each proof argument instantiates and where it comes from, the binders left
unsupplied, and the type of the application, all in the context of the binders around it. -/
def appJson (f : Name) (caller : Name) (helper : Bool) (k : Nat) (occ : Occ) : MetaM Json :=
  withBinders occ.binders.toList #[] fun xs => do
    let env ← getEnv
    let vars := xs.map (·.fvarId!)
    let a := occ.e.instantiateRev xs
    let some fci := env.find? f | return Json.null
    let args := a.getAppArgs
    let ls := match a.getAppFn.consumeMData with | .const _ ls => ls | _ => []
    let mut ty := fci.instantiateTypeLevelParams ls
    let mut params : Array Json := #[]
    let mut extra := 0
    for i in [:args.size] do
      let arg := args[i]!
      unless ty.isForall do
        ty ← try withCurrHeartbeats (whnf ty) catch _ => pure ty
      match ty with
      | .forallE bn bt bb bbi =>
        let prop ← try isProp bt catch _ => pure false
        let role := if bbi.isInstImplicit then "instance" else if prop then "premise"
          else "parameter"
        let origin ← try
            if role == "parameter" then termOrigin xs occ.binders helper arg
            else originJson xs occ.binders helper 2 arg
          catch _ => pure (Json.mkObj [("kind", Json.str "other")])
        let shown ← if role == "premise" then pure Json.null else ppBounded arg vars
        params := params.push (Json.mkObj [("index", toJson i),
          ("binder", Json.str bn.eraseMacroScopes.toString),
          ("binder_info", Json.str (binderInfoStr bbi)), ("role", Json.str role),
          ("type", ← ppBounded bt vars (termNodes * 5)), ("argument", shown),
          ("origin", origin)])
        ty := bb.instantiate1 arg
      | _ =>
        extra := args.size - i
        break
    -- The binders the application leaves to its context: premises not supplied here.
    let open_ ← forallTelescope ty fun ys _ => ys.mapM fun y => do
      let d ← y.fvarId!.getDecl
      let prop ← try isProp d.type catch _ => pure false
      return Json.mkObj [("binder", Json.str d.userName.eraseMacroScopes.toString),
        ("role", Json.str (if d.binderInfo.isInstImplicit then "instance"
          else if prop then "premise" else "parameter"))]
    let used := (collectFVars {} a).fvarIds
    let locals ← (List.range xs.size).toArray.filterMapM fun j => do
      unless used.contains vars[j]! do return none
      let b := occ.binders[j]!
      return some (Json.mkObj [("local", toJson j),
        ("name", Json.str b.name.eraseMacroScopes.toString), ("id", Json.str (toString b.pos)),
        ("binder", Json.str b.kind), ("parameter", toJson b.param),
        ("type", ← ppBounded (← inferType xs[j]!) vars)])
    return Json.mkObj [("record", "app"), ("name", f.toString), ("caller", caller.toString),
      ("index", toJson k), ("path", Json.str (toString occ.pos)),
      ("args", toJson args.size), ("params", Json.arr params), ("extra_args", toJson extra),
      ("open", Json.arr open_), ("result", ← ppBounded ty vars (termNodes * 5)),
      ("locals", Json.arr locals)]

/-- Where `target` is used in the project (or in `callers`), and its applications there. -/
def appsRecords (h : IO.FS.Handle) (roots : Array Name) (cache : UsedCache) (target : Name)
    (callers : Option (Array String)) : MetaM Unit := do
  let env ← getEnv
  let some tci := env.find? target
    | emit h (Json.mkObj [("record", "uses"), ("name", target.toString),
        ("errors", toJson #["missing"])])
  let candidates ← match callers with
    | some cs => pure (cs.map (·.toName))
    | none => projectConstants roots
  let mut users : Array Name := #[]
  for n in candidates do
    if n == target then continue
    let some ci := env.find? n | continue
    let (st, va) ← usedOf cache n ci
    let inSt := st.contains target
    let inVa := va.contains target
    unless inSt || inVa do continue
    if inVa then users := users.push n
    emit h (Json.mkObj [("record", "user"), ("name", target.toString), ("user", n.toString),
      ("owner", (ownerOf env n).toString), ("module", (moduleOf env n).toString),
      ("kind", kindOf ci), ("user_facing", toJson (userFacing n)),
      ("value_kind", valueKind ci), ("statement", toJson inSt), ("value", toJson inVa)])
  -- Applications: user-facing users first, then generated ones, each in its own budget.
  let ordered := users.filter userFacing ++ users.filter (!userFacing ·)
  let mut described := 0
  let mut skipped := 0
  for n in ordered do
    let some ci := env.find? n | continue
    let some v := valueOf ci | continue
    if described ≥ appsUsers then
      skipped := skipped + 1
      continue
    described := described + 1
    let helper := !userFacing n
    tryCatchRuntimeEx (withCurrHeartbeats do
        let ((), s) := (collect target appsPerUser v .root #[] (arity ci.type)).run {}
        let mut k := 0
        for occ in s.occs do
          let j ← tryCatchRuntimeEx (withCurrHeartbeats (appJson target n helper k occ))
            (fun err => do return Json.mkObj [("record", "app"), ("name", target.toString),
              ("caller", n.toString), ("index", toJson k), ("path", Json.str (toString occ.pos)),
              ("errors", toJson #[s!"probe-error: {← err.toMessageData.toString}"])])
          unless j.isNull do emit h j
          k := k + 1
        emit h (Json.mkObj [("record", "appscan"), ("name", target.toString),
          ("caller", n.toString), ("found", toJson s.occs.size), ("cut", toJson s.cut),
          ("range", ← rangeJson (ownerOf env n))]))
      (fun err => do
        emit h (Json.mkObj [("record", "appscan"), ("name", target.toString),
          ("caller", n.toString), ("cut", toJson true),
          ("errors", toJson #[s!"probe-error: {← err.toMessageData.toString}"])]))
  emit h (Json.mkObj [("record", "uses"), ("name", target.toString), ("errors", Json.arr #[]),
    ("module", (moduleOf env target).toString), ("kind", kindOf tci),
    ("searched", toJson candidates.size), ("described", toJson described),
    ("not_described", toJson skipped)])

end ProofLensProbe

open ProofLensProbe in
#eval show MetaM Unit from do
  let some qpath ← IO.getEnv "PROOFLENS_QUERY" | throwError "PROOFLENS_QUERY unset"
  let some opath ← IO.getEnv "PROOFLENS_OUT" | throwError "PROOFLENS_OUT unset"
  let q ← match (Json.parse (← IO.FS.readFile qpath)) >>= fromJson? (α := Query) with
    | .ok q => pure q
    | .error e => throwError s!"bad query: {e}"
  let roots := q.scope_roots.map (·.toName)
  let seen ← IO.mkRef ({} : NameSet)
  let used : UsedCache ← IO.mkRef {}
  let h ← IO.FS.Handle.mk opath .write
  do
    emit h (Json.mkObj [("record", "env"), ("lean", Lean.versionString),
      ("githash", Lean.githash)])
    layering h q
    for r in q.requests do
      -- Each request has its own heartbeat budget. A request that fails, including by running
      -- out of heartbeats (a runtime exception, which `try` does not catch), emits an error
      -- record for itself and the probe goes on.
      tryCatchRuntimeEx (withBudget q.max_heartbeats <| withCurrHeartbeats do
        match r.kind with
        | "spec" => specRecord h q roots seen r.name.toName
        | "accept" | "refute" => proofRecord h q r.kind r.name.toName (r.spec.map (·.toName))
        | "witness" => proofRecord h q "witness" r.name.toName none
        | "index" => do indexRecords h roots; moduleDocRecords h roots
        | "moddocs" => moduleDocRecords h roots
        | "link" => linkRecord h q roots seen r.name.toName
        | "deps" => depsRecords h roots r.name.toName
        | "modules" => moduleRecords h
        | "decl" => do
          let env ← getEnv
          if let some ci := env.find? r.name.toName then
            let (j, used) ← declRecord roots r.name.toName ci
            seen.modify (·.insert r.name.toName)
            emit h j
            let members ← emitClosure h roots r.name.toName used seen
            emit h (Json.mkObj [("record", "defclosure"), ("name", r.name),
              ("closure", toJson members)])
          else
            emit h (Json.mkObj [("record", "defclosure"), ("name", r.name),
              ("errors", toJson #["missing"])])
        | "refs" => refsRecords h roots used
        | "apps" => appsRecords h roots used r.name.toName r.callers
        | _ => pure ())
        (fun err => do
          emit h (Json.mkObj [("record", if r.kind == "decl" then "defclosure" else r.kind),
            ("name", r.name), ("spec", match r.spec with | some x => Json.str x | none => Json.null),
            ("errors", toJson #[s!"probe-error: {← err.toMessageData.toString}"])]))
    emit h (Json.mkObj [("record", "done")])
