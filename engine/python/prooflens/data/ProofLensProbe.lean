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
sub-term, which depends on the proposition only, not on how it is printed or split. An expression
that is not part of the proposition (a defining equation) has a prefix (`pfx`, the equation
theorem's name) before its positions. -/
partial def segments (vars : Array FVarId) (root : SubExpr.Pos) (pfx : String)
    (t : Widget.CodeWithInfos)
    (ref : Option (String × Json)) (acc : Array Json) (terms : Array (Nat × Nat × String)) :
    Array Json × Array (Nat × Nat × String) :=
  match t with
  | Widget.TaggedText.text s =>
    match ref with
    | some (k, v) => (acc.push (Json.mkObj [("t", s), (k, v)]), terms)
    | none => (acc.push (Json.mkObj [("t", s)]), terms)
  | Widget.TaggedText.append xs =>
    xs.foldl (fun (a, ts) x => segments vars root pfx x ref a ts) (acc, terms)
  | Widget.TaggedText.tag info sub =>
    let r := match info.info.val.info with
      | .ofTermInfo ti => match ti.expr with
        | .const n _ => some ("ref", Json.str n.toString)
        | .fvar id => (vars.findIdx? (· == id)).map fun i => ("var", toJson i)
        | _ => none
      | _ => none
    let start := acc.size
    let slot := terms.size
    let id := pfx ++ toString (root.append info.subexprPos)
    let (acc', terms') := segments vars root pfx sub r acc (terms.push (start, start, id))
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
`root` is the position of `e` in the whole proposition (`id`), after the prefix `pfx`. -/
def ppFields (e : Expr) (vars : Array FVarId := #[]) (root : SubExpr.Pos := .root)
    (pfx : String := "") : MetaM (List (String × Json)) := do
  try
    -- The type of a bound variable is printed (`pp.funBinderTypes`): `∃ Φ : T, …` says what Φ
    -- is. The head of every application is tagged too (`pp.tagAppFns`), so that the function a
    -- term applies is a constant the reader can name. The text and the tagged code are printed
    -- with the same options.
    let typed := fun (o : Options) => o.setBool `pp.funBinderTypes true
    let code ← withOptions (fun o => (typed o).setBool `pp.tagAppFns true) (Widget.ppExprTagged e)
    let text := toString (← withOptions typed (ppExpr e))
    let (segs, terms) := segments vars root pfx code none #[] #[]
    return [("text", Json.str text), ("segments", Json.arr segs), ("terms", termsJson terms),
      ("id", Json.str (pfx ++ toString root))]
  catch _ =>
    try
      return [("text", Json.str (toString (← ppExpr e)))]
    catch err =>
      return [("text", Json.str "(not printable)"),
        ("error", Json.str (toString (← err.toMessageData.toString)))]

def ppJson (e : Expr) (vars : Array FVarId := #[]) (root : SubExpr.Pos := .root)
    (pfx : String := "") : MetaM Json :=
  return Json.mkObj (← ppFields e vars root pfx)

/-- How a binder is written: `(x : T)`, `{x : T}`, `⦃x : T⦄` or `[T]`. -/
def binderStr : BinderInfo → String
  | .default => "explicit" | .implicit => "implicit"
  | .strictImplicit => "strict-implicit" | .instImplicit => "instance"

/-- A binder's name as the reader shows it: without macro scopes, or `_` when it has none. -/
def binderName (n : Name) : String :=
  let m := n.eraseMacroScopes
  if m.isAnonymous then "_" else m.toString

def isExistsApp (e : Expr) : Option (Name × Expr) :=
  if e.isAppOfArity ``Exists 2 then
    match e.appArg! with
    | .lam n _ _ _ => some (n, e.appArg!)
    | _ => none
  else none

/-- Whether a name is one a reader looks for: not generated by the compiler or elaborator. -/
def userFacing (n : Name) : Bool :=
  !n.isInternal && !(n.components.any fun c =>
    let s := c.toString
    s.startsWith "_" || s.startsWith "match_" || s.startsWith "proof_" || s == "eq_def"
      || s.startsWith "eq_" && (s.drop 3).all Char.isDigit)

/-- At most this many equations of one definition are exported; the record says how many more
there are. -/
def maxEquations : Nat := 64

/-! ## A definition at its actual arguments

An application of one of the project's definitions inside a printed expression (`JetBound f S
(n + 5) C`) is expanded where it stands. A definition given by a body is its body with those
arguments substituted (`Expr.beta`: a bound variable is never captured), checked by Lean to have
the application's type; arguments not supplied stay parameters. A definition given by equations
is each equation theorem whose left side matches the application, specialised to its arguments,
with the variables and conditions that remain, and checked by Lean to follow from the theorem.
An expansion has identities of its own (prefixed `<occurrence>=`), apart from those of the
general definition and of the statement. Display only. -/

/-- At most this many applications of one printed expression are expanded; the record says how
many more there are. -/
def maxExpansions : Nat := 16

/-- How deep a statement's applications are expanded: an application, and those inside its
expansion. Further definitions stay references to their declarations. -/
def statementDepth : Nat := 2

/-- At most this many nodes of one printed expression are visited looking for applications. -/
def maxVisits : Nat := 4000

/-- Whether an application of `c` is expanded: a definition of the project's (`roots`) that a
reader looks for, of data or of a predicate, and not an instance or a structure's projection. -/
def expandable (roots : Array Name) (c : Name) : MetaM Bool := do
  let env ← getEnv
  let some (.defnInfo d) := env.find? c | return false
  unless inScope roots env c && userFacing c do return false
  if (← isInstance c) || (← isProjectionFn c) then return false
  return !(← isProp d.type)

/-- How a definition's parameters are written and named, for its first `n` arguments. -/
def paramInfos (type : Expr) (n : Nat) : MetaM (Array (Name × BinderInfo)) :=
  forallBoundedTelescope type (some n) fun xs _ => xs.mapM fun x => do
    let d ← x.fvarId!.getDecl
    return (d.userName, d.binderInfo)

/-- The statement `t` (the type of `thm`) with each of its leading variables replaced by the
value its metavariable in `ms` was assigned, and those left unassigned kept as hypotheses, in
their order. The result is checked to follow from `thm`. -/
partial def keepUndetermined (thm : Expr) (ms : Array Expr) (t : Expr) (i : Nat)
    (kept : Array Expr) : MetaM Expr := do
  match t with
  | .forallE n d b bi =>
    let m ← instantiateMVars ms[i]!
    if m.isMVar then
      withLocalDecl n bi (← instantiateMVars d) fun x => do
        m.mvarId!.assign x
        keepUndetermined thm ms (b.instantiate1 x) (i + 1) (kept.push x)
    else keepUndetermined thm ms (b.instantiate1 m) (i + 1) kept
  | _ =>
    let stmt ← mkForallFVars kept (← instantiateMVars t)
    let prf ← mkLambdaFVars kept (← instantiateMVars (mkAppN thm ms))
    check prf
    unless ← isDefEq (← inferType prf) stmt do
      throwError "the specialised equation does not follow from {thm}"
    return stmt

/-- The equation `eqn` of a definition at the application `e`, when its left side matches it:
the statement with every variable the match determines replaced by its value, and the others
(variables, and conditions such as a case excluded by an earlier pattern) kept as hypotheses.
Run it under `withoutModifyingState`: it assigns metavariables. -/
def specialiseEquation (eqn : Name) (us : List Level) (e : Expr) : MetaM (Option Expr) := do
  let ci ← getConstInfo eqn
  let lvls ← if ci.levelParams.length == us.length then pure us
    else ci.levelParams.mapM fun _ => mkFreshLevelMVar
  let thm := mkConst eqn lvls
  let ty ← inferType thm
  let (ms, _, body) ← forallMetaTelescope ty
  let some (_, lhs, _) := body.eq? | return none
  let la := lhs.getAppArgs
  let ea := e.getAppArgs
  unless lhs.getAppFn.constName? == e.getAppFn.constName? && la.size == ea.size do return none
  for (a, b) in la.zip ea do
    unless ← isDefEq a b do return none
  some <$> keepUndetermined thm ms ty 0 #[]

mutual

/-- The parameters of a definition (the leading `fun` binders of its value) and the body under
them, each printed with positions rooted at the value, so that the body's sub-terms have the
identities they have in `value`. Unless `bind`, the parameters are not numbered among the
variables `vars` (an expansion's parameters are not variables of the statement). The body's
applications of the project's definitions are expanded to `depth` (`ppExpanded`); in an
equation (`eqn`), not the application its left side states. -/
partial def paramsAndBody (e : Expr) (acc : Array Json := #[]) (vars : Array FVarId := #[])
    (pos : SubExpr.Pos := .root) (pfx : String := "") (lambdas : Bool := true) (bind : Bool := true)
    (roots : Array Name := #[]) (depth : Nat := 0) (eqn : Bool := false) :
    MetaM (Array Json × Json) := do
  match e, lambdas with
  | .lam n t b bi, true | .forallE n t b bi, false =>
    let tj ← ppJson t vars pos.pushBindingDomain pfx
    withLocalDecl n bi t fun x => do
      let j := Json.mkObj [("name", binderName n), ("binder", binderStr bi),
        ("id", Json.str (pfx ++ toString pos)), ("type", tj),
        ("proposition", toJson (← isProp t))]
      paramsAndBody (b.instantiate1 x) (acc.push j) (if bind then vars.push x.fvarId! else vars)
        pos.pushBindingBody pfx lambdas bind roots depth eqn
  | _, _ => return (acc, ← ppExpanded roots depth e vars pos pfx eqn)

/-- The fields of a printed expression (`ppFields`), with the expansions of the applications of
the project's definitions inside it (`expansions`) when `depth` is positive. When `e` is an
equation (`eqn`), the application its left side states is the one being expanded: only its
arguments and the right side are. -/
partial def ppExpanded (roots : Array Name) (depth : Nat) (e : Expr) (vars : Array FVarId)
    (root : SubExpr.Pos) (pfx : String := "") (eqn : Bool := false) : MetaM Json := do
  let fields ← ppFields e vars root pfx
  if depth == 0 || roots.isEmpty then return Json.mkObj fields
  let found ← IO.mkRef ((0, 0) : Nat × Nat)
  let out ← if eqn && e.isAppOfArity ``Eq 3 then do
      let lhs := e.getArg! 1
      let lp := root.pushNaryArg 3 1
      let la := lhs.getAppArgs
      let mut acc := #[]
      for i in [:la.size] do
        acc := acc ++
          (← expansionsIn roots depth vars pfx found la[i]! (lp.pushNaryArg la.size i))
      pure (acc ++ (← expansionsIn roots depth vars pfx found (e.getArg! 2) (root.pushNaryArg 3 2)))
    else expansionsIn roots depth vars pfx found e root
  if out.isEmpty then return Json.mkObj fields
  return Json.mkObj (fields ++ [("expansions", Json.arr out),
    ("expansions_omitted", toJson ((← found.get).1 - out.size))])

/-- The applications of the project's definitions inside `e` (at `pos`), outermost first, each
expanded in the local context where it stands. Only what is printed is searched: the explicit
arguments of an application, not its implicit and instance arguments (whose terms can be very
large shared structures). `found` counts the applications and the nodes visited; applications
after the first `maxExpansions` are counted only, and the search stops after `maxVisits`
nodes. -/
partial def expansionsIn (roots : Array Name) (depth : Nat) (vars : Array FVarId) (pfx : String)
    (found : IO.Ref (Nat × Nat)) (e : Expr) (pos : SubExpr.Pos) : MetaM (Array Json) := do
  found.modify fun (n, v) => (n, v + 1)
  if (← found.get).2 > maxVisits then return #[]
  match e with
  | .app .. =>
    let f := e.getAppFn
    let args := e.getAppArgs
    let mut out := #[]
    if let .const c us := f then
      if ← expandable roots c then
        found.modify fun (n, v) => (n + 1, v)
        if (← found.get).1 ≤ maxExpansions then
          out := out.push (← expansionAt roots depth vars pfx e c us pos)
    else
      out := out ++ (← expansionsIn roots depth vars pfx found f (pos.pushNaryFn args.size))
    let explicit ← try
        let info ← getFunInfoNArgs f args.size
        pure (info.paramInfo.map (·.binderInfo.isExplicit))
      catch _ => pure #[]
    for i in [:args.size] do
      if explicit.getD i true then
        out := out ++
          (← expansionsIn roots depth vars pfx found args[i]! (pos.pushNaryArg args.size i))
    return out
  | .lam n t b bi | .forallE n t b bi =>
    let a ← expansionsIn roots depth vars pfx found t pos.pushBindingDomain
    withLocalDecl n bi t fun x => do
      return a ++
        (← expansionsIn roots depth vars pfx found (b.instantiate1 x) pos.pushBindingBody)
  | .mdata _ b => expansionsIn roots depth vars pfx found b pos
  | _ => return #[]

/-- The expansion of the application `e` of `c` at `pos`: its arguments, by the definition's
parameters; and the body at those arguments, or the equations that apply to them. A failure is
recorded on the expansion (`error`) and stops nothing else. -/
partial def expansionAt (roots : Array Name) (depth : Nat) (vars : Array FVarId) (pfx : String)
    (e : Expr) (c : Name) (us : List Level) (pos : SubExpr.Pos) : MetaM Json := do
  let at_ := pfx ++ toString pos
  let xp := at_ ++ "="
  let base : List (String × Json) := [("at", Json.str at_), ("id", Json.str xp),
    ("name", Json.str c.toString)]
  let act : MetaM Json := withCurrHeartbeats do
    let ci ← getConstInfo c
    let args := e.getAppArgs
    let infos ← paramInfos (ci.instantiateTypeLevelParams us) args.size
    let mut argsJ : Array Json := #[]
    for i in [:args.size] do
      let (n, bi) := infos[i]?.getD (.anonymous, .default)
      -- A parameter without a written name (one matched by a pattern) has none here.
      let nm := if n.hasMacroScopes then "" else binderName n
      argsJ := argsJ.push (Json.mkObj [("name", Json.str nm),
        ("binder", Json.str (binderStr bi)),
        ("value", ← ppJson args[i]! vars (pos.pushNaryArg args.size i) pfx)])
    let eqs? ← getEqnsFor? c
    let byEqns := match eqs? with
      | some eqs => eqs.size > 1
      | none => false
    let byEqns := byEqns || (eqs?.isSome && (← isRecursiveDefinition c))
    if let some eqs := eqs? then
      if byEqns then
        let mut applied : Array Json := #[]
        let mut other : Array Json := #[]
        for q in eqs.toList.take maxEquations do
          let r ← withoutModifyingState do
            match ← specialiseEquation q us e with
            | some stmt =>
              let qp := xp ++ q.toString ++ ":"
              let sj ← ppJson stmt vars .root qp
              let (params, eqn) ← paramsAndBody stmt #[] vars .root qp (lambdas := false)
                (bind := false) roots (depth - 1) (eqn := true)
              pure (some (Json.mkObj [("name", Json.str q.toString), ("statement", sj),
                ("params", Json.arr params), ("equation", eqn)]))
            | none => pure none
          match r with
          | some j => applied := applied.push j
          | none => other := other.push (Json.str q.toString)
        return Json.mkObj (base ++ [("defined_by", Json.str "equations"),
          ("args", Json.arr argsJ), ("equations", Json.arr applied),
          ("equations_not_applying", Json.arr other),
          ("equations_omitted", toJson (eqs.size - min eqs.size maxEquations)),
          ("checked", Json.bool true)])
    let v := (ci.instantiateValueLevelParams! us).beta args
    check v
    unless ← isDefEq (← inferType v) (← inferType e) do
      throwError "the expansion does not have the type of the application"
    -- Parameters left unapplied stay parameters of the expansion.
    lambdaTelescope v fun xs b => do
      let mut params : Array Json := #[]
      let mut p := SubExpr.Pos.root
      for x in xs do
        let d ← x.fvarId!.getDecl
        params := params.push (Json.mkObj [("name", Json.str (binderName d.userName)),
          ("binder", Json.str (binderStr d.binderInfo)), ("id", Json.str (xp ++ toString p)),
          ("type", ← ppJson d.type vars p.pushBindingDomain xp),
          ("proposition", toJson (← isProp d.type))])
        p := p.pushBindingBody
      let bodyJ ← ppExpanded roots (depth - 1) b vars p xp
      return Json.mkObj (base ++ [("defined_by", Json.str "body"), ("args", Json.arr argsJ),
        ("params", Json.arr params), ("body", bodyJ), ("checked", Json.bool true)])
  tryCatchRuntimeEx act fun err => do
    return Json.mkObj (base ++ [("error",
      Json.str s!"probe-error: {← err.toMessageData.toString}")])

end

/-! ## Properties carried by a type

A condition can be part of an object's type rather than a hypothesis of the statement: the
predicate of a subtype, a proof field of a structure, the law of a class. For each object of a
statement whose type is a structure (a subtype and a class are structures) with a field that is
a proposition, every field of the structure is projected from the object, inherited fields
included and each once (`getStructureFieldsFlattened`), and exported with its statement as it
applies to that object, whether it is data or a proposition, and where it comes from (the
structure, the parent structure that declares it, the projection). Display only. -/

/-- At most this many fields of one object are exported; the record says how many more there
are. -/
def maxFields : Nat := 32

/-- The fields carried by the type of the local `x` (`properties`), each with its statement
specialised to `x`; nothing when the type is not a structure or has no field that is a
proposition. An object of a type that is a proposition (`x` a proof) has properties only when
`ofProp` is set, and a conjunction or an equivalence never has (`logic` shows its parts). The
positions of a field's statement are prefixed by `pfx` and the field's name. A failure is
recorded (`properties_error`) and stops nothing else. -/
def propertiesOf (x : Expr) (vars : Array FVarId) (pfx : String) (ofProp : Bool := false) :
    MetaM (List (String × Json)) := do
  let act : MetaM (List (String × Json)) := withCurrHeartbeats do
    let env ← getEnv
    let ty ← whnfR (← instantiateMVars (← inferType x))
    let .const S _ := ty.getAppFn | return []
    unless isStructure env S do return []
    if S == ``And || S == ``Iff then return []
    if (← isProp ty) != ofProp then return []
    let fields := getStructureFieldsFlattened env S (includeSubobjectFields := false)
    let mut out : Array Json := #[]
    let mut anyProp := false
    for f in fields.toList.take maxFields do
      let p ← mkProjection x f
      let t ← instantiateMVars (← inferType p)
      let prop ← isProp t
      anyProp := anyProp || prop
      let decl := (findField? env S f).getD S
      let proj := getProjFnForField? env decl f
      out := out.push (Json.mkObj [("field", f.toString),
        ("kind", if prop then "proposition" else "data"),
        ("structure", S.toString), ("declared_in", decl.toString),
        ("inherited", toJson (decl != S)),
        ("projection", match proj with | some q => Json.str q.toString | none => Json.null),
        ("module", match proj with
          | some q => Json.str (moduleOf env q).toString | none => Json.null),
        ("range", ← match proj with | some q => rangeJson q | none => pure Json.null),
        ("term", Json.str (toString (← ppExpr p))),
        ("type", ← ppJson t vars .root s!"{pfx}{f}:")])
    unless anyProp do return []
    return [("properties", Json.arr out),
      ("properties_omitted", toJson (fields.size - out.size))]
  tryCatchRuntimeEx act fun err => do
    return [("properties_error", Json.str s!"probe-error: {← err.toMessageData.toString}")]

/-- The objects a proposition quantifies over inside itself (a hypothesis's own "for every" and
"there is"), each with the connectives that enclose it (`scope`, outermost first) and the
properties its type carries; only those whose type carries one. Their occurrences are not
numbered as variables of the statement: they belong to the proposition. -/
partial def innerObjects (e : Expr) (vars : Array FVarId) (pos : SubExpr.Pos)
    (scope : Array String := #[]) : MetaM (Array Json) := do
  let two : String → MetaM (Array Json) := fun op => do
    let a ← innerObjects e.appFn!.appArg! vars pos.pushAppFn.pushAppArg (scope.push op)
    let b ← innerObjects e.appArg! vars pos.pushAppArg (scope.push op)
    return a ++ b
  if e.isAppOfArity ``And 2 then return ← two "and"
  if e.isAppOfArity ``Or 2 then return ← two "or"
  if e.isAppOfArity ``Iff 2 then return ← two "iff"
  if e.isAppOfArity ``Not 1 then
    return ← innerObjects e.appArg! vars pos.pushAppArg (scope.push "not")
  let one : String → Name → Expr → Expr → BinderInfo → SubExpr.Pos → MetaM (Array Json) :=
    fun op n t body bi at_ => withLocalDecl n bi t fun x => do
      let props ← propertiesOf x vars s!"{at_}#"
      let inner ← innerObjects (body.instantiate1 x) vars at_.pushBindingBody (scope.push op)
      if props.isEmpty then return inner
      let tj ← ppJson t vars at_.pushBindingDomain
      return #[Json.mkObj ([("op", Json.str op), ("name", Json.str (binderName n)),
        ("id", Json.str (toString at_)), ("type", tj), ("scope", toJson scope)] ++ props)] ++ inner
  if let .forallE n t body bi := e then
    if (← isProp t) && !body.hasLooseBVars then
      let a ← innerObjects t vars pos.pushBindingDomain (scope.push "if")
      let b ← innerObjects body vars pos.pushBindingBody (scope.push "then")
      return a ++ b
    return ← one "forall" n t body bi pos
  match isExistsApp e with
  | some (_, .lam n t body bi) => one "exists" n t body bi pos.pushAppArg
  | _ => return #[]


/-- The logical shape of a conclusion: a conjunction, disjunction, equivalence, negation,
implication, "for every" or "there is" as a tree whose leaves are pretty-printed propositions. A
quantifier inside the conclusion is a node (`forall`, `exists`) with its variable's name, type and
number, and its body as its one part. `vars` is
threaded through the tree, so that every witness has a variable of its own: two witnesses in
sibling parts never share one. `pos` is the position of `e` in the whole proposition; each
node and variable carries its own (`id`). Display only; it changes no record that is assessed. -/
partial def logicJson (roots : Array Name) (vars : Array FVarId) (e : Expr) (pos : SubExpr.Pos) :
    MetaM (Json × Array FVarId) := do
  let op := if e.isAppOfArity ``And 2 then some "and"
    else if e.isAppOfArity ``Or 2 then some "or"
    else if e.isAppOfArity ``Iff 2 then some "iff" else none
  match op with
  | some o =>
    let (a, vars) ← logicJson roots vars e.appFn!.appArg! pos.pushAppFn.pushAppArg
    let (b, vars) ← logicJson roots vars e.appArg! pos.pushAppArg
    return (Json.mkObj [("op", o), ("id", Json.str (toString pos)),
      ("args", Json.arr #[a, b])], vars)
  | none =>
    if e.isAppOfArity ``Not 1 then
      let (a, vars) ← logicJson roots vars e.appArg! pos.pushAppArg
      return (Json.mkObj [("op", "not"), ("id", Json.str (toString pos)),
        ("args", Json.arr #[a])], vars)
    if let .forallE n t body bi := e then
      if (← isProp t) && !body.hasLooseBVars then
        -- An implication inside a part: its premise is a part of its own, not an assumption
        -- of the whole statement.
        let (a, vars) ← logicJson roots vars t pos.pushBindingDomain
        let (b, vars) ← logicJson roots vars body pos.pushBindingBody
        return (Json.mkObj [("op", "implies"), ("id", Json.str (toString pos)),
          ("args", Json.arr #[a, b])], vars)
      let tj ← ppExpanded roots statementDepth t vars pos.pushBindingDomain
      return ← withLocalDecl n bi t fun x => do
        let idx := vars.size
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{pos}#"
        let (b, vars') ←
          logicJson roots (vars.push x.fvarId!) (body.instantiate1 x) pos.pushBindingBody
        return (Json.mkObj (([("op", "forall"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString pos)), ("type", tj),
          ("args", Json.arr #[b])] : List (String × Json)) ++ props), vars')
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      -- The witness is bound by the predicate `fun x => …`, the second argument of `Exists`.
      let lam := pos.pushAppArg
      let tj ← ppExpanded roots statementDepth t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let idx := vars.size
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{lam}#"
        let (b, vars') ←
          logicJson roots (vars.push x.fvarId!) (body.instantiate1 x) lam.pushBindingBody
        return (Json.mkObj (([("op", "exists"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString lam)), ("type", tj),
          ("args", Json.arr #[b])] : List (String × Json)) ++ props), vars')
    | _ => return (Json.mkObj [("leaf", ← ppExpanded roots statementDepth e vars pos)], vars)

/-! ## The inspection representation -/

/-- Split a proposition into its quantifier prefix and its conclusion. Universal binders are
`forall` (data), `hypothesis` (a proposition) or `instance`; existential binders are `exists`.
Definitions are not unfolded: the prefix is the one written in the specification. -/
partial def telescope (roots : Array Name) (e : Expr) (acc : Array Json) (vars : Array FVarId := #[])
    (pos : SubExpr.Pos := .root) : MetaM (Array Json × Json) := do
  match e with
  | .forallE n t body bi =>
    let isHyp ← isProp t
    let role :=
      if bi.isInstImplicit then "instance" else if isHyp then "hypothesis" else "forall"
    let tj ← ppExpanded roots statementDepth t vars pos.pushBindingDomain
    withLocalDecl n bi t fun x => do
      let hyps := (acc.filter fun j => j.getObjValD "role" == Json.str "hypothesis").size
      let nm := if n.hasMacroScopes || n.isAnonymous then s!"h{hyps + 1}"
        else n.toString
      -- What an instance supplies: a proposition (`[Nonempty E]`) or data (`[Inhabited E]`).
      let supplies := if isHyp then "proposition" else "data"
      -- What the object's type carries, or, for a hypothesis, the objects inside it whose type
      -- carries something. A hypothesis whose type is a structure of propositions
      -- (`[IsProbability Ω]`) lists what its fields state.
      let extra ← if isHyp then do
          let objs ← innerObjects t vars pos.pushBindingDomain
          let states ← propertiesOf x (vars.push x.fvarId!) s!"{pos}#" (ofProp := true)
          pure ((if objs.isEmpty then [] else [("objects", Json.arr objs)]) ++ states)
        else propertiesOf x (vars.push x.fvarId!) s!"{pos}#"
      let j := Json.mkObj (([("role", role), ("name", nm), ("id", Json.str (toString pos)),
        ("type", tj), ("binder", binderStr bi), ("supplies", supplies)] : List (String × Json))
        ++ extra)
      telescope roots (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) pos.pushBindingBody
  | _ =>
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      let lam := pos.pushAppArg
      let tj ← ppExpanded roots statementDepth t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{lam}#"
        let j := Json.mkObj (([("role", "exists"), ("name", n.eraseMacroScopes.toString),
          ("id", Json.str (toString lam)), ("type", tj), ("binder", binderStr bi)]
          : List (String × Json)) ++ props)
        telescope roots (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) lam.pushBindingBody
    | _ =>
      -- The conclusion, with its logical shape when it has one (`logic`, display only).
      -- Without a shape, the conclusion is the one leaf, with its expansions.
      let (logic, _) ← logicJson roots vars e pos
      match logic.getObjVal? "leaf" with
      | .ok leaf => return (acc, leaf)
      | .error _ => return (acc, Json.mkObj ((← ppFields e vars pos) ++ [("logic", logic)]))

/-- Constants of the project that `e` uses directly. -/
def projectConsts (roots : Array Name) (e : Expr) : MetaM (Array String) := do
  let env ← getEnv
  return e.getUsedConstants.filter (inScope roots env) |>.map toString

/-! ## What a definition says

A definition is shown as it is written: its parameters and the body under them, or, for a
definition by pattern matching or recursion, the equations Lean derives from it (its equation
theorems, `getEqnsFor?`), each with its exact statement. The compiled value stays in `value`. -/

/-- The equation theorems of a definition, each with its exact statement and, read as an
equation, its variables (`params`) and the equation under them (`equation`). The positions of an
equation's sub-terms are prefixed by the theorem's name: an equation is not part of any other
expression. -/
def equationsJson (n : Name) : MetaM (Option (Array Name × Array Json)) := do
  let some eqs ← getEqnsFor? n | return none
  let mut out : Array Json := #[]
  for q in eqs.toList.take maxEquations do
    let ci ← getConstInfo q
    let pfx := q.toString ++ ":"
    let stmt ← ppJson ci.type #[] .root pfx
    let (params, eqn) ← paramsAndBody ci.type #[] #[] .root pfx (lambdas := false)
    out := out.push (Json.mkObj [("name", q.toString), ("statement", stmt),
      ("params", Json.arr params), ("equation", eqn)])
  return some (eqs, out)

/-- What a definition of data or of a predicate says (`defined_by`: `body` or `equations`), with
its parameters, body and the body's type (`result`), its equations, or the error that stopped their extraction. A
definition by recursion or with several equations is presented by its equations. The
extraction has its own heartbeat budget, and a failure is recorded here and stops nothing else. -/
def definitionFields (roots : Array Name) (n : Name) (type value : Expr) : MetaM (List (String × Json)) := do
  let act : MetaM (List (String × Json)) := withCurrHeartbeats do
    let eqns ← equationsJson n
    let recursive ← isRecursiveDefinition n
    let byEqns := match eqns with
      | some (eqs, _) => recursive || eqs.size > 1
      | none => false
    let eqFields : List (String × Json) := match eqns with
      | some (eqs, items) =>
        [("equations", Json.arr items), ("equation_names", toJson (eqs.map toString)),
         ("equations_omitted", toJson (eqs.size - items.size))]
      | none => [("equations", Json.null)]
    if byEqns then
      return [("defined_by", Json.str "equations")] ++ eqFields
    let (params, body) ← paramsAndBody value (roots := roots) (depth := 1)
    -- The type of the body: the definition's type under its parameters, prefixed `type:` (its
    -- positions are in the type, not in the value).
    let result ← forallBoundedTelescope type (some params.size) fun xs r => do
      let pos := xs.foldl (fun p _ => p.pushBindingBody) SubExpr.Pos.root
      ppJson r (xs.map (·.fvarId!)) pos "type:"
    return [("defined_by", Json.str "body"), ("params", Json.arr params), ("body", body),
      ("result", result)] ++ eqFields
  tryCatchRuntimeEx act fun err => do
    return [("defined_by", Json.null),
      ("definition_error", Json.str s!"probe-error: {← err.toMessageData.toString}")]

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
  -- What a definition says, for the definitions a reader looks for (not a compiler's helper, not
  -- an instance, not a proposition such as a locked statement).
  let defn ← match ci with
    | .defnInfo d =>
      if value != Json.null && userFacing n && !(← isInstance n) then definitionFields roots n ci.type d.value
      else pure []
    | _ => pure []
  let doc ← findDocString? env n
  let fields : List (String × Json) := [
    ("record", "decl"), ("name", n.toString), ("kind", kindOf ci),
    ("module", (moduleOf env n).toString), ("range", ← rangeJson n),
    ("doc", match doc with | some d => Json.str d | none => Json.null),
    ("legacy_hash", lh), ("canon", c), ("signature", sig), ("value", value),
    ("uses", Json.arr ((used.filter fun u => inScope roots env u && !u.isInternal).map
      (Json.str ·.toString)))]
  return (Json.mkObj (fields ++ defn), used)

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
    | .defnInfo d => telescope roots d.value #[]
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
  let (binders, concl) ← telescope roots stmt #[]
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
        | _ => pure ())
        (fun err => do
          emit h (Json.mkObj [("record", if r.kind == "decl" then "defclosure" else r.kind),
            ("name", r.name), ("spec", match r.spec with | some x => Json.str x | none => Json.null),
            ("errors", toJson #[s!"probe-error: {← err.toMessageData.toString}"])]))
    emit h (Json.mkObj [("record", "done")])
