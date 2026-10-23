/-!
# The ProofLens probe

Body of the probe that `prooflens probe` runs inside a Lean project. The CLI prepends
`import Lean` and the project's modules and runs the result with `lake env lean`, so this file
has no imports of its own and is not built as part of any library.

Input: the JSON query named by `PROOFLENS_QUERY`. Output: JSON lines written to the file named
by `PROOFLENS_OUT`, one record per request and one per declaration of the definition closure,
and last a `done` record with the number of bytes written before it.

For a specification the record holds two representations of the proposition:

* the verification representation: the declaration, its axioms, the constants it uses, its
  structural hashes (`legacy_hash`, a 128-bit structural hash kept for compatibility with
  existing review markers, and `canon`, a canonical serialisation the CLI hashes with SHA-256),
  and each application of a totalised operation (a supremum, a division, an integral) with the
  type it is taken in (`order_ops`);
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
  /-- For `names`: the names to resolve. -/
  names : Option (Array String) := none
  deriving FromJson, Inhabited

structure Query where
  scope_roots : Array String
  spec_prefix : String
  accept_prefix : String
  /-- Every prefix of the statement layer, and of the proof layer, when a layer has several;
  `spec_prefix`, `accept_prefix` alone if none. -/
  spec_prefixes : Option (Array String) := none
  accept_prefixes : Option (Array String) := none
  allowed_axioms : Array String
  requests : Array Request
  /-- Each request's heartbeat budget, in thousands as `maxHeartbeats`; Lean's default if none. -/
  max_heartbeats : Option Nat := none
  /-- The most nodes of a proof term, and the most facts, a `proof-facts` request walks and
  reports; the probe's defaults if none. -/
  facts_nodes : Option Nat := none
  facts_items : Option Nat := none
  deriving FromJson, Inhabited

/-- The module prefixes of a layer: the listed ones, or the single one when none are listed. -/
def layerPrefixes (one : String) (many : Option (Array String)) : Array Name :=
  match many with
  | some ps => if ps.isEmpty then #[one.toName] else ps.map (·.toName)
  | none => #[one.toName]

def Query.specLayer (q : Query) : Array Name := layerPrefixes q.spec_prefix q.spec_prefixes

def Query.acceptLayer (q : Query) : Array Name := layerPrefixes q.accept_prefix q.accept_prefixes

/-- Whether a module lies in a layer: under one of the layer's prefixes. -/
def inLayer (layer : Array Name) (mod : Name) : Bool := layer.any (·.isPrefixOf mod)

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

/-- Whether a constant is declared in a module of `roots`, by module index: one lookup per
constant, for the hundreds of thousands of references a large project has. -/
def scopeTest (roots : Array Name) : CoreM (Name → Bool) := do
  let env ← getEnv
  let names := env.header.moduleNames
  let mut inside : Std.HashSet Nat := {}
  for i in [:names.size] do
    if roots.contains names[i]!.getRoot then inside := inside.insert i
  return fun n => match env.getModuleIdxFor? n with
    | some i => inside.contains i.toNat
    | none => false

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

/-- Whether an application of `c` is expanded: a definition of the project's (`inside`) that a
reader looks for, of data or of a predicate, and not an instance or a structure's projection. -/
def expandable (inside : Name → Bool) (c : Name) : MetaM Bool := do
  let env ← getEnv
  let some (.defnInfo d) := env.find? c | return false
  unless inside c && userFacing c do return false
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
    (inside : Name → Bool := fun _ => false) (depth : Nat := 0) (eqn : Bool := false) :
    MetaM (Array Json × Json) := do
  match e, lambdas with
  | .lam n t b bi, true | .forallE n t b bi, false =>
    let tj ← ppJson t vars pos.pushBindingDomain pfx
    withLocalDecl n bi t fun x => do
      let j := Json.mkObj [("name", binderName n), ("binder", binderStr bi),
        ("id", Json.str (pfx ++ toString pos)), ("type", tj),
        ("proposition", toJson (← isProp t))]
      paramsAndBody (b.instantiate1 x) (acc.push j) (if bind then vars.push x.fvarId! else vars)
        pos.pushBindingBody pfx lambdas bind inside depth eqn
  | _, _ => return (acc, ← ppExpanded inside depth e vars pos pfx eqn)

/-- The fields of a printed expression (`ppFields`), with the expansions of the applications of
the project's definitions inside it (`expansions`) when `depth` is positive. When `e` is an
equation (`eqn`), the application its left side states is the one being expanded: only its
arguments and the right side are. -/
partial def ppExpanded (inside : Name → Bool) (depth : Nat) (e : Expr) (vars : Array FVarId)
    (root : SubExpr.Pos) (pfx : String := "") (eqn : Bool := false) : MetaM Json := do
  let fields ← ppFields e vars root pfx
  if depth == 0 then return Json.mkObj fields
  let found ← IO.mkRef ((0, 0) : Nat × Nat)
  let out ← if eqn && e.isAppOfArity ``Eq 3 then do
      let lhs := e.getArg! 1
      let lp := root.pushNaryArg 3 1
      let la := lhs.getAppArgs
      let mut acc := #[]
      for i in [:la.size] do
        acc := acc ++
          (← expansionsIn inside depth vars pfx found la[i]! (lp.pushNaryArg la.size i))
      pure (acc ++ (← expansionsIn inside depth vars pfx found (e.getArg! 2) (root.pushNaryArg 3 2)))
    else expansionsIn inside depth vars pfx found e root
  if out.isEmpty then return Json.mkObj fields
  return Json.mkObj (fields ++ [("expansions", Json.arr out),
    ("expansions_omitted", toJson ((← found.get).1 - out.size))])

/-- The applications of the project's definitions inside `e` (at `pos`), outermost first, each
expanded in the local context where it stands. Only what is printed is searched: the explicit
arguments of an application, not its implicit and instance arguments (whose terms can be very
large shared structures). `found` counts the applications and the nodes visited; applications
after the first `maxExpansions` are counted only, and the search stops after `maxVisits`
nodes. -/
partial def expansionsIn (inside : Name → Bool) (depth : Nat) (vars : Array FVarId) (pfx : String)
    (found : IO.Ref (Nat × Nat)) (e : Expr) (pos : SubExpr.Pos) : MetaM (Array Json) := do
  found.modify fun (n, v) => (n, v + 1)
  if (← found.get).2 > maxVisits then return #[]
  match e with
  | .app .. =>
    let f := e.getAppFn
    let args := e.getAppArgs
    let mut out := #[]
    if let .const c us := f then
      if ← expandable inside c then
        found.modify fun (n, v) => (n + 1, v)
        if (← found.get).1 ≤ maxExpansions then
          out := out.push (← expansionAt inside depth vars pfx e c us pos)
    else
      out := out ++ (← expansionsIn inside depth vars pfx found f (pos.pushNaryFn args.size))
    let explicit ← try
        let info ← getFunInfoNArgs f args.size
        pure (info.paramInfo.map (·.binderInfo.isExplicit))
      catch _ => pure #[]
    for i in [:args.size] do
      if explicit.getD i true then
        out := out ++
          (← expansionsIn inside depth vars pfx found args[i]! (pos.pushNaryArg args.size i))
    return out
  | .lam n t b bi | .forallE n t b bi =>
    let a ← expansionsIn inside depth vars pfx found t pos.pushBindingDomain
    withLocalDecl n bi t fun x => do
      return a ++
        (← expansionsIn inside depth vars pfx found (b.instantiate1 x) pos.pushBindingBody)
  | .mdata _ b => expansionsIn inside depth vars pfx found b pos
  | _ => return #[]

/-- The expansion of the application `e` of `c` at `pos`: its arguments, by the definition's
parameters; and the body at those arguments, or the equations that apply to them. A failure is
recorded on the expansion (`error`) and stops nothing else. -/
partial def expansionAt (inside : Name → Bool) (depth : Nat) (vars : Array FVarId) (pfx : String)
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
                (bind := false) inside (depth - 1) (eqn := true)
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
      let bodyJ ← ppExpanded inside (depth - 1) b vars p xp
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
partial def logicJson (inside : Name → Bool) (vars : Array FVarId) (e : Expr) (pos : SubExpr.Pos) :
    MetaM (Json × Array FVarId) := do
  let op := if e.isAppOfArity ``And 2 then some "and"
    else if e.isAppOfArity ``Or 2 then some "or"
    else if e.isAppOfArity ``Iff 2 then some "iff" else none
  match op with
  | some o =>
    let (a, vars) ← logicJson inside vars e.appFn!.appArg! pos.pushAppFn.pushAppArg
    let (b, vars) ← logicJson inside vars e.appArg! pos.pushAppArg
    return (Json.mkObj [("op", o), ("id", Json.str (toString pos)),
      ("args", Json.arr #[a, b])], vars)
  | none =>
    if e.isAppOfArity ``Not 1 then
      let (a, vars) ← logicJson inside vars e.appArg! pos.pushAppArg
      return (Json.mkObj [("op", "not"), ("id", Json.str (toString pos)),
        ("args", Json.arr #[a])], vars)
    if let .forallE n t body bi := e then
      if (← isProp t) && !body.hasLooseBVars then
        -- An implication inside a part: its premise is a part of its own, not an assumption
        -- of the whole statement.
        let (a, vars) ← logicJson inside vars t pos.pushBindingDomain
        let (b, vars) ← logicJson inside vars body pos.pushBindingBody
        return (Json.mkObj [("op", "implies"), ("id", Json.str (toString pos)),
          ("args", Json.arr #[a, b])], vars)
      let tj ← ppExpanded inside statementDepth t vars pos.pushBindingDomain
      return ← withLocalDecl n bi t fun x => do
        let idx := vars.size
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{pos}#"
        let (b, vars') ←
          logicJson inside (vars.push x.fvarId!) (body.instantiate1 x) pos.pushBindingBody
        return (Json.mkObj (([("op", "forall"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString pos)), ("type", tj),
          ("args", Json.arr #[b])] : List (String × Json)) ++ props), vars')
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      -- The witness is bound by the predicate `fun x => …`, the second argument of `Exists`.
      let lam := pos.pushAppArg
      let tj ← ppExpanded inside statementDepth t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let idx := vars.size
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{lam}#"
        let (b, vars') ←
          logicJson inside (vars.push x.fvarId!) (body.instantiate1 x) lam.pushBindingBody
        return (Json.mkObj (([("op", "exists"), ("name", n.eraseMacroScopes.toString),
          ("var", toJson idx), ("id", Json.str (toString lam)), ("type", tj),
          ("args", Json.arr #[b])] : List (String × Json)) ++ props), vars')
    | _ => return (Json.mkObj [("leaf", ← ppExpanded inside statementDepth e vars pos)], vars)

/-! ## The inspection representation -/

/-- Split a proposition into its quantifier prefix and its conclusion. Universal binders are
`forall` (data), `hypothesis` (a proposition) or `instance`; existential binders are `exists`.
Definitions are not unfolded: the prefix is the one written in the specification. -/
partial def telescope (inside : Name → Bool) (e : Expr) (acc : Array Json) (vars : Array FVarId := #[])
    (pos : SubExpr.Pos := .root) : MetaM (Array Json × Json) := do
  match e with
  | .forallE n t body bi =>
    let isHyp ← isProp t
    let role :=
      if bi.isInstImplicit then "instance" else if isHyp then "hypothesis" else "forall"
    let tj ← ppExpanded inside statementDepth t vars pos.pushBindingDomain
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
      telescope inside (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) pos.pushBindingBody
  | _ =>
    match isExistsApp e with
    | some (_, .lam n t body bi) =>
      let lam := pos.pushAppArg
      let tj ← ppExpanded inside statementDepth t vars lam.pushBindingDomain
      withLocalDecl n bi t fun x => do
        let props ← propertiesOf x (vars.push x.fvarId!) s!"{lam}#"
        let j := Json.mkObj (([("role", "exists"), ("name", n.eraseMacroScopes.toString),
          ("id", Json.str (toString lam)), ("type", tj), ("binder", binderStr bi)]
          : List (String × Json)) ++ props)
        telescope inside (body.instantiate1 x) (acc.push j) (vars.push x.fvarId!) lam.pushBindingBody
    | _ =>
      -- The conclusion, with its logical shape when it has one (`logic`, display only).
      -- Without a shape, the conclusion is the one leaf, with its expansions.
      let (logic, _) ← logicJson inside vars e pos
      match logic.getObjVal? "leaf" with
      | .ok leaf => return (acc, leaf)
      | .error _ => return (acc, Json.mkObj ((← ppFields e vars pos) ++ [("logic", logic)]))

/-- Constants of the project that `e` uses directly. -/
def projectConsts (inside : Name → Bool) (e : Expr) : MetaM (Array String) := do
  let env ← getEnv
  return e.getUsedConstants.filter inside |>.map toString

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
def definitionFields (inside : Name → Bool) (n : Name) (type value : Expr) : MetaM (List (String × Json)) := do
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
    let (params, body) ← paramsAndBody value (inside := inside) (depth := 1)
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

def declRecord (inside : Name → Bool) (n : Name) (ci : ConstantInfo) : MetaM (Json × Array Name) := do
  let env ← getEnv
  let (lh, c, used) ← constPrint ci
  let sig ← ppJson ci.type
  -- Whether the type is a proposition: the declaration is a proof (a theorem, a proof Lean
  -- generates, a `Prop`-valued instance) and carries no data. Unknown when Lean cannot tell.
  let prop ← tryCatchRuntimeEx (some <$> isProp ci.type) fun _ => pure none
  let value ← match ci, prop with
    | .defnInfo d, some false => ppJson d.value
    | _, _ => pure Json.null
  -- What a definition says, for the definitions a reader looks for (not a compiler's helper, not
  -- an instance, not a proposition such as a locked statement).
  let defn ← match ci with
    | .defnInfo d =>
      if value != Json.null && userFacing n && !(← isInstance n) then definitionFields inside n ci.type d.value
      else pure []
    | _ => pure []
  let doc ← findDocString? env n
  let fields : List (String × Json) := [
    ("record", "decl"), ("name", n.toString), ("kind", kindOf ci),
    ("module", (moduleOf env n).toString), ("range", ← rangeJson n),
    ("doc", match doc with | some d => Json.str d | none => Json.null),
    ("legacy_hash", lh), ("canon", c), ("signature", sig), ("value", value),
    ("proposition", toJson prop),
    ("uses", Json.arr ((used.filter fun u => inside u && !u.isInternal).map
      (Json.str ·.toString)))]
  return (Json.mkObj (fields ++ defn), used)

def emitClosure (h : IO.FS.Handle) (inside : Name → Bool) (root : Name) (used : Array Name)
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
    unless inside n do continue
    let some c := env.find? n | continue
    members := members.push n.toString
    -- Each member has its own heartbeat budget: a closure can hold thousands.
    let (j, more) ← withCurrHeartbeats (declRecord inside n c)
    unless (← seen.get).contains n do
      seen.modify (·.insert n)
      emit h j
    stack := stack ++ more
  return members.qsort (· < ·)

/-! ## Totalised operations, with their carriers

What an operation gives outside its intended domain can depend on the type it is taken in. A
supremum in a complete lattice (a lattice of σ-algebras, the extended nonnegative reals) always
exists, and in a conditionally complete one (the reals) an empty or unbounded family gets a
default value; division by zero rounds in `ℕ`, gives `0` in a field and `∞` in `ℝ≥0∞`, and has no
exceptional case in a group; every function into a type with one element is integrable. For
each application of such an operation in a statement, its carrier is recorded: a type argument
(or the type of the value) after reducible unfolding, its head constant, and the structure Lean
finds on it that decides the rule. The names are matched by value, so the probe needs no import
of the library that declares them. -/

/-- The operations recorded, each with the structure that decides its rule (`order`: the lattice
instances, `division`: the group instances, `integral`: whether the type has one element, `""`:
none) and where its carrier is: its first argument (`true`) or the type of its value. -/
def totalOps : Array (Name × String × Bool) := #[
  (`iSup, "order", true), (`iInf, "order", true), (`SupSet.sSup, "order", true),
  (`InfSet.sInf, "order", true), (`sSup, "order", true), (`sInf, "order", true),
  (`HDiv.hDiv, "division", true), (`Inv.inv, "division", true), (`tsum, "", true),
  (`MeasureTheory.integral, "integral", false), (`MeasureTheory.condExp, "", false),
  (`deriv, "", false), (`Real.sqrt, "", false), (`Real.log, "", false)]

/-- The most nodes of a statement visited for its totalised operations. -/
def opsNodes : Nat := 50000

/-- `x`, or `d` when it fails, including by running out of heartbeats (a runtime exception,
which `try` does not catch). `x` has a budget of its own. -/
def orDefault (d : α) (x : MetaM α) : MetaM α :=
  tryCatchRuntimeEx (withCurrHeartbeats x) fun _ => pure d

/-- Whether Lean finds an instance of the class `c` at `α` (false also when the search fails). -/
def hasInstance (c : Name) (α : Expr) : MetaM Bool :=
  orDefault false do return (← synthInstance? (← mkAppM c #[α])).isSome

/-- `complete` when Lean finds `CompleteLattice α`, `conditional` when it finds only
`ConditionallyCompleteLattice α`, `unknown` otherwise (also when the search fails). -/
def latticeOf (α : Expr) : MetaM String := do
  if ← hasInstance `CompleteLattice α then return "complete"
  if ← hasInstance `ConditionallyCompleteLattice α then return "conditional"
  return "unknown"

/-- `group` when Lean finds `Group α`, `group-with-zero` when it finds `GroupWithZero α` (a
field, a division ring), `unknown` otherwise (also when the search fails). -/
def algebraOf (α : Expr) : MetaM String := do
  if ← hasInstance `Group α then return "group"
  if ← hasInstance `GroupWithZero α then return "group-with-zero"
  return "unknown"

/-- The structure on `α` that decides the rule of an operation of kind `kind`. -/
def structureJson (kind : String) (α : Expr) : MetaM (List (String × Json)) := do
  match kind with
  | "order" => return [("lattice", Json.str (← latticeOf α))]
  | "division" => return [("algebra", Json.str (← algebraOf α))]
  | "integral" => return [("subsingleton", Json.bool (← hasInstance `Subsingleton α))]
  | _ => return []

/-- The record of a carrier for an operation of kind `kind`, computed once per walk. -/
def carrierJson (kind : String) (α : Expr)
    (cache : IO.Ref (Array ((String × Expr) × List (String × Json)))) :
    MetaM (List (String × Json)) := do
  if let some (_, j) := (← cache.get).find? (·.1 == (kind, α)) then return j
  let r ← orDefault α (whnfR α)
  let head := match r.getAppFn with
    | .const h _ => h.toString
    | _ => ""
  let carrier ← orDefault "" (toString <$> ppExpr α)
  let j := [("carrier", Json.str carrier), ("carrier_head", Json.str head)] ++
    (← orDefault [] (structureJson kind α))
  cache.modify (·.push ((kind, α), j))
  return j

/-- The state of one walk: the applications found, the nodes left, the carriers read and the
subterms already visited (a statement shares subterms, which a walk would otherwise repeat). -/
structure OpsWalk where
  out : IO.Ref (Array Json)
  budget : IO.Ref Nat
  cache : IO.Ref (Array ((String × Expr) × List (String × Json)))
  seen : IO.Ref (Std.HashSet Expr)

/-- Record the application `e` of the operation `c`, with arguments `args`. The carrier is the
first argument or, for an operation whose type is fixed by its arguments, the type of the value
once every argument is supplied (a value that is a function is read at its result). -/
def opsRecord (e : Expr) (c : Name) (args : Array Expr) (w : OpsWalk) : MetaM Unit := do
  let some (_, kind, first) := totalOps.find? (·.1 == c) | return
  if first && args.size == 0 then return
  let j ← if first then carrierJson kind args[0]! w.cache
    else
      orDefault [("carrier", Json.str ""), ("carrier_head", Json.str "")] do
        forallTelescope (← inferType e) fun _ ty => carrierJson kind ty w.cache
  w.out.modify (·.push (Json.mkObj (("const", Json.str c.toString) :: j)))

partial def opsVisit (e : Expr) (w : OpsWalk) : MetaM Unit := do
  if (← w.budget.get) == 0 then return
  if (← w.seen.get).contains e then return
  w.seen.modify (·.insert e)
  w.budget.modify (· - 1)
  match e with
  | .forallE n t b bi | .lam n t b bi =>
    opsVisit t w
    withLocalDecl n bi t fun x => opsVisit (b.instantiate1 x) w
  | .letE n t v b _ =>
    opsVisit t w
    opsVisit v w
    withLetDecl n t v fun x => opsVisit (b.instantiate1 x) w
  | .mdata _ b => opsVisit b w
  | .proj _ _ b => opsVisit b w
  | .const c _ => opsRecord e c #[] w
  | .app .. =>
    let f := e.getAppFn
    let args := e.getAppArgs
    if let .const c _ := f then
      opsRecord e c args w
    else
      opsVisit f w
    for a in args do
      opsVisit a w
  | _ => pure ()

/-- Each application of a totalised operation in `e`, with its carrier. `complete: false` when
some applications may be missing, with the reason in `stopped`: the walk reached its limit of
nodes (`nodes`), or failed, for example by running out of heartbeats (`error`). -/
def orderOpsJson (e : Expr) : MetaM Json := do
  let w : OpsWalk := { out := ← IO.mkRef #[], budget := ← IO.mkRef opsNodes,
                       cache := ← IO.mkRef #[], seen := ← IO.mkRef {} }
  let finished ← orDefault false do
    opsVisit e w
    return true
  let left ← w.budget.get
  let stopped := if !finished then "error" else if left == 0 then "nodes" else ""
  return Json.mkObj ([("occurrences", Json.arr (← w.out.get)), ("complete", stopped == "")] ++
    (if stopped == "" then [] else [("stopped", Json.str stopped)]))

def disallowed (allowed : Array Name) (axs : Array Name) : Array Name :=
  axs.filter (!allowed.contains ·)

def specRecord (h : IO.FS.Handle) (q : Query) (inside : Name → Bool) (seen : IO.Ref NameSet)
    (spec : Name) : MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? spec
    | emit h (Json.mkObj [("record", "spec"), ("name", spec.toString), ("errors", toJson #["missing"])])
  let mut errs : Array String := #[]
  unless ci matches .defnInfo _ do errs := errs.push "not-a-def"
  unless ci.type == .sort .zero do errs := errs.push "type-not-Prop"
  unless inLayer q.specLayer (moduleOf env spec) do errs := errs.push "outside-spec-layer"
  let axs ← collectAxioms spec
  let bad := disallowed (q.allowed_axioms.map (·.toName)) axs
  unless bad.isEmpty do errs := errs.push s!"axioms={bad.toList}"
  let (j, used) ← declRecord inside spec ci
  let (binders, concl) ← match ci with
    | .defnInfo d => telescope inside d.value #[]
    | _ => pure (#[], Json.null)
  let exact ← match ci with
    | .defnInfo d => ppJson d.value
    | _ => pure Json.null
  let closure ← emitClosure h inside spec used seen
  let direct ← match ci with
    | .defnInfo d => projectConsts inside d.value
    | _ => pure #[]
  let consts := match ci with
    | .defnInfo d => d.value.getUsedConstants.map toString
    | _ => #[]
  let ops ← match ci with
    | .defnInfo d => orderOpsJson d.value
    | _ => pure Json.null
  emit h (Json.mkObj [("record", "spec"), ("name", spec.toString), ("errors", toJson errs),
    ("axioms", toJson (axs.map toString)), ("decl", j),
    ("binders", Json.arr binders), ("conclusion", concl), ("exact", exact),
    ("direct", toJson direct), ("consts", toJson consts), ("order_ops", ops),
    ("closure", toJson closure)])

def levelsMatch (ls : List Level) (params : List Name) : Bool :=
  let ps := ls.filterMap fun l => match l with | .param p => some p | _ => none
  ps.length == ls.length && ps.eraseDups.length == ps.length && ps.length == params.length
    && params.all ps.contains

/-- `accept`: the type is exactly the specification; `refute`: exactly its negation; `witness`:
any theorem of the acceptance layer, with the project declarations in the closure of its type
(the instance it exhibits lives in them). -/
def proofRecord (h : IO.FS.Handle) (q : Query) (inside : Name → Bool) (seen : IO.Ref NameSet)
    (kind : String) (thm : Name) (spec : Option Name) : MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? thm
    | emit h (Json.mkObj [("record", kind), ("name", thm.toString), ("errors", toJson #["missing"])])
  let mut errs : Array String := #[]
  unless ci matches .thmInfo _ do errs := errs.push "not-a-theorem"
  unless inLayer q.acceptLayer (moduleOf env thm) do
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
  let closure : List (String × Json) ← if kind == "witness" then
      pure [("closure", toJson (← emitClosure h inside thm ci.type.getUsedConstants seen))]
    else pure []
  let fields : List (String × Json) := [("record", kind), ("name", thm.toString),
    ("spec", match spec with | some s => Json.str s.toString | none => Json.null),
    ("errors", toJson errs), ("axioms", toJson (axs.map toString)),
    ("type", ty), ("module", (moduleOf env thm).toString), ("range", ← rangeJson thm),
    ("sorry", toJson (axs.contains ``sorryAx))]
  emit h (Json.mkObj (fields ++ closure))

/-- The project constants (`roots`) among `cs` that a reader looks for, other than `self`. -/
def projectNamesJson (roots : Array Name) (env : Environment) (self : Name) (cs : Array Name) :
    Json :=
  Json.arr ((cs.filter fun c => c != self && inScope roots env c && userFacing c).map
    (Json.str ·.toString))

/-- Every user-facing theorem, definition and type declared in the modules of `roots`: name,
kind, module, line, docstring, the complete statement as text, and the project constants its
statement mentions (`uses`) and its value uses (`value_uses`: a proof or a body). -/
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
      let value := match ci with
        | .defnInfo d => d.value.getUsedConstants
        | .thmInfo t => t.value.getUsedConstants
        | .opaqueInfo o => o.value.getUsedConstants
        | _ => #[]
      emit h (Json.mkObj [("record", "index"), ("name", n.toString), ("kind", k),
        ("module", mod.toString), ("range", ← rangeJson n),
        ("doc", match doc with | some d => Json.str d | none => Json.null),
        ("type", ty), ("uses", projectNamesJson roots env n ci.type.getUsedConstants),
        ("value_uses", projectNamesJson roots env n value)])

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

/-- `s` with its comments and string literals blanked out, its newlines kept. -/
partial def stripComments (out : Array Char) (depth : Nat) (inLine inStr : Bool) :
    List Char → Array Char
  | [] => out
  | c :: r =>
    if c == '\n' then stripComments (out.push '\n') depth false inStr r
    else if inLine then stripComments out depth true inStr r
    else if depth > 0 then
      match c, r with
      | '/', '-' :: r' => stripComments out (depth + 1) false false r'
      | '-', '/' :: r' => stripComments (out.push ' ') (depth - 1) false false r'
      | _, _ => stripComments out depth false false r
    else if inStr then
      match c, r with
      | '\\', '\n' :: r' => stripComments (out.push '\n') 0 false true r'
      | '\\', _ :: r' => stripComments out 0 false true r'
      | '"', _ => stripComments (out.push ' ') 0 false false r
      | _, _ => stripComments out 0 false true r
    else
      match c, r with
      | '-', '-' :: r' => stripComments out 0 true false r'
      | '/', '-' :: r' => stripComments out 1 false false r'
      | '"', _ => stripComments (out.push ' ') 0 false true r
      | '\'', '"' :: '\'' :: r' => stripComments (out.push ' ') 0 false false r'
      | _, _ => stripComments (out.push c) 0 false false r

/-- The words of a line of Lean, with parentheses as words of their own. -/
def words (l : List Char) : List String :=
  let spaced := l.foldr (fun c acc =>
    if c == '(' || c == ')' then ' ' :: c :: ' ' :: acc
    else if c.isWhitespace then ' ' :: acc else c :: acc) []
  ((splitChars ' ' spaced).filter (!·.isEmpty)).toList.map charsToString

/-- Runs `x` as if inside namespace `ns` with `opens` open, as Lean resolves an identifier
there. -/
def withScope (ns : Name) (opens : List OpenDecl) (x : MetaM α) : MetaM α :=
  withTheReader Core.Context (fun c => { c with currNamespace := ns, openDecls := opens }) x

/-- The namespaces a source file enters (`namespace`) and what its `open` commands open,
each resolved where the command stands. An `open … in` opens for one command only and is left
out; every other `open` is kept to the end of the file, as a docstring at the top of a file
names what the file goes on to open. -/
def fileScopes (src : String) : MetaM (Array Name × List OpenDecl) := do
  let mut stack : Array Name := #[]
  let mut spaces : Array Name := #[]
  let mut opens : List OpenDecl := []
  for l in splitChars '\n' (stripComments #[] 0 false false src.toList).toList do
    let ws := (words l).dropWhile (fun w => w ∈ ["noncomputable", "public", "private"]
      || "@[".toList.isPrefixOf w.toList)
    let cur := stack.back?.getD .anonymous
    match ws with
    | "namespace" :: n :: _ =>
      let mut ns := cur
      for c in n.toName.components do
        ns := ns ++ c
        stack := stack.push ns
        unless spaces.contains ns do spaces := spaces.push ns
    | "section" :: _ => stack := stack.push cur
    | "end" :: rest =>
      let k := match rest with | n :: _ => max 1 n.toName.components.length | [] => 1
      stack := stack.extract 0 (stack.size - k)
    | "open" :: rest =>
      if rest.contains "in" then continue
      let rest := rest.filter (· != "scoped")
      let resolve := fun (n : String) => do
        try withScope cur opens (resolveNamespaceCore n.toName (allowEmpty := true))
        catch _ => pure []
      let mut i := 0
      let mut last : List Name := []
      let mut added : List OpenDecl := []
      while i < rest.length do
        let w := rest[i]!
        if w == "(" then
          i := i + 1
          while i < rest.length && rest[i]! != ")" do
            for ns in last do
              added := .explicit rest[i]!.toName (ns ++ rest[i]!.toName) :: added
            i := i + 1
          last := []
        else if w == "hiding" then
          let exs := (rest.drop (i + 1)).map String.toName
          added := last.map (.simple · exs) ++ added
          last := []
          i := rest.length
        else if w == "renaming" || w == ")" then
          i := rest.length
        else
          added := last.map (.simple · []) ++ added
          last ← resolve w
          i := i + 1
      added := last.map (.simple · []) ++ added
      opens := opens ++ added.reverse
    | _ => pure ()
  return (spaces, opens)

/-- Every backticked name in the docstrings of the modules of `roots` that resolves to no
constant: its module, its line, the heading it is under, whether it begins a list item, and
what it is instead (`kind`: a `module`, a `namespace`, or `none`, with its `full` name). A name
is resolved as Lean resolves an identifier, inside each namespace the module's file enters or
declares into and with every namespace its file opens (`scopes`). A module or namespace written
in full is not reported: only a shorter name that reaches one through the file's namespaces. -/
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
    -- The source is read from the project the probe runs in; a module whose file is elsewhere
    -- (a dependency's) is resolved with the namespaces it declares into only.
    let file : System.FilePath := mod.components.foldl (fun p c => p / c.toString) "."
    let (entered, opens) ← try fileScopes (← IO.FS.readFile (file.addExtension "lean"))
      catch _ => pure (#[], [])
    for ns in entered do
      unless spaces.contains ns do spaces := spaces.push ns
    let scopes := #[Name.anonymous] ++ spaces
    let scopesJson := Json.arr ((spaces ++ (opens.filterMap fun
      | .simple ns _ => some ns | _ => none).toArray).map (Json.str ·.toString))
    let constant := fun (n : Name) => do
      for ns in scopes do
        -- A private declaration of the module, or a protected one, named inside its
        -- namespace.
        if env.contains (ns ++ n) || declared.contains (ns ++ n) then return true
      for ns in scopes do
        let rs ← try withScope ns opens (resolveGlobalName n) catch _ => pure []
        if rs.any (·.2.isEmpty) then return true
      return false
    let other := fun (n : Name) => do
      for ns in scopes do
        if (env.getModuleIdx? (ns ++ n)).isSome then return some ("module", ns ++ n)
      for ns in scopes do
        let r ← try withScope ns opens (resolveNamespaceCore n (allowEmpty := true))
          catch _ => pure []
        if let some full := r.head? then return some ("namespace", full)
      return (none : Option (String × Name))
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
              let inFull := (env.getModuleIdx? n).isSome || env.isNamespace n
              unless inFull || (← constant n) do
                let what ← other n
                emit h (Json.mkObj [("record", "moddoc"), ("module", mod.toString),
                  ("line", toJson line), ("name", Json.str (charsToString tok)),
                  ("heading", Json.str (charsToString heading)),
                  ("item_lead", toJson (item && k == 1)),
                  ("kind", Json.str (what.map (·.1) |>.getD "none")),
                  ("full", Json.str ((what.map (·.2)).getD n).toString),
                  ("scopes", scopesJson)])
            k := k + 2
        line := line + 1

/-! ## Names cited in review text -/

/-- Whether the components of `n` are the last components of `u`. -/
partial def isNameSuffix (n u : Name) : Bool :=
  match n, u with
  | .anonymous, _ => true
  | .str p s, .str q t => s == t && isNameSuffix p q
  | .num p i, .num q j => i == j && isNameSuffix p q
  | _, _ => false

/-- The names of `names` (dotted, as written) that nothing in the environment resolves: no
declaration, namespace or module has the name, and no declaration or namespace has it as its
last components (`bar_eq_span` for `Foo.bar_eq_span`). -/
def namesRecord (h : IO.FS.Handle) (names : Array String) : MetaM Unit := do
  let env ← getEnv
  let mut pending : Array (String × Name) := #[]
  for s in names do
    let n := (splitChars '.' s.toList).foldl (fun n p => Name.str n (charsToString p)) .anonymous
    unless env.contains n || env.isNamespace n || (env.getModuleIdx? n).isSome do
      pending := pending.push (s, n)
  let mut lasts : NameSet := {}
  for (_, n) in pending do
    if let .str _ t := n then lasts := lasts.insert (Name.mkSimple t)
  let mut found : NameSet := {}
  for md in env.header.moduleData do
    for c in md.constNames do
      let mut u := privateToUserName c
      while !u.isAnonymous do
        if let .str _ t := u then
          if lasts.contains (Name.mkSimple t) then
            for (_, n) in pending do
              if isNameSuffix n u then found := found.insert n
        u := u.getPrefix
  let unresolved := pending.filter (fun (_, n) => !found.contains n) |>.map (·.1)
  emit h (Json.mkObj [("record", "names"), ("checked", toJson names),
    ("unresolved", toJson unresolved)])

/-- A theorem of a link: its statement split like a specification, and its axioms. -/
def linkRecord (h : IO.FS.Handle) (q : Query) (inside : Name → Bool) (seen : IO.Ref NameSet)
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
  let (binders, concl) ← telescope inside stmt #[]
  let exact ← ppJson stmt
  let axs ← collectAxioms n
  let bad := disallowed (q.allowed_axioms.map (·.toName)) axs
  let (j, used) ← declRecord inside n ci
  let closure ← emitClosure h inside n used seen
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
statement and value dependencies, split into the project's (`inside`) and the rest. -/
def depNode (inside : Name → Bool) (n : Name) (ci : ConstantInfo) (depth : Nat) : MetaM Json := do
  let env ← getEnv
  let (st, va) := statementAndValueConsts ci
  let ours := fun (a : Array Name) => Json.arr ((a.filter inside).map (Json.str ·.toString))
  let others := fun (a : Array Name) =>
    Json.arr ((a.filter (!inside ·)).map (Json.str ·.toString))
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
    ("statement_uses", ours st), ("value_uses", ours va),
    ("statement_external", others st), ("value_external", others va)]

/-- Every declaration of the project reachable from `root` through statements and values, each
once, at its least distance from the root, then a `deps` record with the root's axioms. -/
def depsRecords (h : IO.FS.Handle) (inside : Name → Bool) (root : Name) : MetaM Unit := do
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
    unless n == root || inside n do continue
    emit h (← depNode inside n ci d)
    reached := reached + 1
    let (st, va) := statementAndValueConsts ci
    for c in st ++ va do
      unless seen.contains c do
        if inside c then queue := queue.push (c, d + 1)
  let axs ← collectAxioms root
  emit h (Json.mkObj [("record", "deps"), ("name", root.toString), ("errors", Json.arr #[]),
    ("module", (moduleOf env root).toString), ("axioms", toJson (axs.map toString)),
    ("sorry", toJson (axs.contains ``sorryAx)), ("reached", toJson reached)])

/-! ## Facts inside a proof

A `proof-facts` request reads one declaration's value, unerased, for the propositions its proof
establishes along the way: each `have` (or `let` of a proposition), each goal a `show` states, and
each application of a theorem of the project, or of any theorem to a local fact. Each comes with
its type, the local context it holds in (the binders and hypotheses around it, including the case
of a case split it lies in), the hypotheses it needs and its position in the term. The walk is
bounded in the nodes it visits and the facts it reports, and says when it was cut short. It adds a
record of its own and changes no other. -/

/-- The most nodes of a proof term one request visits, and the most facts it reports. -/
def factsMaxNodes : Nat := 200000
def factsMaxItems : Nat := 200

/-- A binder met on the way into a proof: where it came from and the cases it lies in. -/
structure PFLocal where
  fvar : FVarId
  origin : String
  scope : Array Nat
  ctx : Array Nat
  deriving Inhabited

/-- A fact found in a proof. For an application, `type` is the application itself. -/
structure PFItem where
  kind : String
  name : Name
  type : Expr
  ctx : Array Nat
  scope : Array Nat
  pos : SubExpr.Pos
  uses : Array Nat
  head : Name := .anonymous
  /-- The local a `have` introduces. -/
  bound : Option Nat := none
  deriving Inhabited

structure PFState where
  maxNodes : Nat := factsMaxNodes
  maxItems : Nat := factsMaxItems
  lctx : LocalContext := {}
  locals : Array PFLocal := #[]
  index : Std.HashMap FVarId Nat := {}
  scopes : Array (Name × Nat) := #[]
  items : Array PFItem := #[]
  visited : Nat := 0
  cut : Array String := #[]
  seen : Std.HashSet Expr := {}
  /-- The generated lemmas the proof applies (`_proof_1`, say): parts of it this walk does not
  enter. -/
  aux : Array Name := #[]

abbrev PFM := StateRefT PFState MetaM

/-- The locals among the free variables of `e`. -/
def pfUses (e : Expr) : PFM (Array Nat) := do
  let idx := (← get).index
  return ((collectFVars {} e).fvarIds.filterMap (idx[·]?)).qsort (· < ·)

def pfFull : PFM Bool := do
  let s ← get
  if s.items.size ≥ s.maxItems then
    unless s.cut.contains "facts" do modify fun s => { s with cut := s.cut.push "facts" }
    return true
  return false

def pfRecord (kind : String) (n : Name) (ty : Expr) (ctx scope : Array Nat) (pos : SubExpr.Pos)
    (uses : Array Nat) (head : Name := .anonymous) (bound : Option Nat := none) : PFM Unit := do
  unless ← pfFull do
    let it : PFItem :=
      { kind := kind, name := n, type := ty, ctx := ctx, scope := scope, pos := pos,
        uses := uses, head := head, bound := bound }
    modify fun s => { s with items := s.items.push it }

/-- Runs `k` with a new local `n : t`, kept (with its declaration) for the report. -/
def pfWithLocal (n : Name) (bi : BinderInfo) (t : Expr) (origin : String)
    (ctx scope : Array Nat) (k : Expr → Nat → PFM Unit) : PFM Unit :=
  withLocalDecl n bi t fun x => do
    let d ← x.fvarId!.getDecl
    let i := (← get).locals.size
    let l : PFLocal := { fvar := x.fvarId!, origin := origin, scope := scope, ctx := ctx }
    modify fun s =>
      { s with lctx := s.lctx.addDecl d, locals := s.locals.push l,
               index := s.index.insert x.fvarId! i }
    k x i

/-- Whether `a` is, up to metadata, the local of a fact (a `have` or a `let`). -/
def pfIsFact (fvs : Array Expr) (a : Expr) : PFM Bool := do
  match a.consumeMData with
  | .bvar j =>
    if j < fvs.size then
      let s ← get
      match s.index[fvs[fvs.size - 1 - j]!.fvarId!]? with
      | some i => return s.locals[i]!.origin == "have"
      | none => return false
    else return false
  | _ => return false

/-- Walk a proof term. `fvs` holds the locals of the loose bound variables of `e`, innermost
last; `ctx` their indices; `scope` the cases (an argument of an eliminator) `e` lies in; `stmt`
the binders of the statement still to enter. -/
partial def pfVisit (roots : Array Name) (e : Expr) (fvs : Array Expr) (ctx scope : Array Nat)
    (pos : SubExpr.Pos) (stmt : Nat) : PFM Unit := do
  if !(← get).cut.isEmpty then return
  modify fun s => { s with visited := s.visited + 1 }
  if (← get).visited > (← get).maxNodes then
    modify fun s => { s with cut := s.cut.push "nodes" }
    return
  if !e.hasLooseBVars then
    if (← get).seen.contains e then return
    modify fun s => { s with seen := s.seen.insert e }
  let haveLike (n : Name) (t v b : Expr) (pv pb : SubExpr.Pos) : PFM Unit := do
    let t := t.instantiateRev fvs
    pfVisit roots v fvs ctx scope pv 0
    let prop ← isProp t
    let uses ← if prop then pfUses (v.instantiateRev fvs) else pure #[]
    pfWithLocal n .default t (if prop then "have" else "let") ctx scope fun x i => do
      if prop then pfRecord "have" n t ctx scope pos uses (bound := some i)
      pfVisit roots b (fvs.push x) (ctx.push i) scope pb 0
  match e with
  | .mdata _ b => pfVisit roots b fvs ctx scope pos stmt
  | .proj _ _ b => pfVisit roots b fvs ctx scope pos.pushProj stmt
  | .lam n t b bi =>
    pfWithLocal n bi (t.instantiateRev fvs) (if stmt > 0 then "statement" else "bound") ctx
      scope fun x i => pfVisit roots b (fvs.push x) (ctx.push i) scope pos.pushBindingBody (stmt - 1)
  | .letE n t v b _ => haveLike n t v b pos.pushLetValue pos.pushLetBody
  | .app .. =>
    let f := e.getAppFn
    let args := e.getAppArgs
    let k := args.size
    if f.isConstOf ``letFun && k == 4 then
      if let .lam n t b _ := args[3]!.consumeMData then
        return ← haveLike n t args[2]! b (pos.pushNaryArg k 2)
          ((pos.pushNaryArg k 3).pushBindingBody)
    if f.isConstOf ``id && k == 2 then
      let t := args[0]!.consumeMData.instantiateRev fvs
      if ← isProp t then
        pfRecord "show" .anonymous t ctx scope pos (← pfUses (args[1]!.instantiateRev fvs))
    if let .const c _ := f then
      let env ← getEnv
      if let some (.thmInfo _) := env.find? c then
        if userFacing c && (inScope roots env c || (← args.anyM (pfIsFact fvs))) then
          pfRecord "application" c (e.instantiateRev fvs) ctx scope pos
            (← pfUses (e.instantiateRev fvs)) c
        else if !userFacing c && inScope roots env c && !(← get).aux.contains c then
          modify fun s => { s with aux := s.aux.push c }
    else
      pfVisit roots f fvs ctx scope (pos.pushNaryFn k) 0
    -- The implicit and instance arguments of a constant (types, motives, instances) hold no
    -- step of the proof: they are not entered, which keeps the walk short on large terms.
    let explicit ← match f with
      | .const c _ => do
        let mut t := (← getConstInfo c).type
        let mut out : Array Bool := #[]
        for _ in [:k] do
          let .forallE _ _ b bi := t | break
          out := out.push bi.isExplicit
          t := b
        pure out
      | _ => pure #[]
    for i in [:k] do
      let a := args[i]!
      let p := pos.pushNaryArg k i
      if !explicit.getD i true then continue
      match f, a.consumeMData with
      | .const c _, .lam .. =>
        -- A function argument of a constant is a case of what it eliminates (a branch of
        -- `dite`, the alternative of `Or.elim`, the witness of `Exists.casesOn`).
        let sid := (← get).scopes.size
        modify fun s => { s with scopes := s.scopes.push (c, i) }
        pfVisit roots a fvs ctx (scope.push sid) p 0
      | _, _ => pfVisit roots a fvs ctx scope p 0
  | _ => pure ()

/-- The locals a fact needs: those its type and its proof mention, and those their types
mention, in order. -/
def pfNeeds (s : PFState) (ty : Expr) (uses : Array Nat) : MetaM (Array Nat) := do
  let mut need : Std.HashSet Nat := {}
  let mut stack := uses ++ ((collectFVars {} ty).fvarIds.filterMap (s.index[·]?))
  while !stack.isEmpty do
    let i := stack.back!
    stack := stack.pop
    if need.contains i then continue
    need := need.insert i
    let t ← inferType (mkFVar s.locals[i]!.fvar)
    stack := stack ++ ((collectFVars {} t).fvarIds.filterMap (s.index[·]?))
  return need.toArray.qsort (· < ·)

/-- The hypotheses of an application's theorem, at the application's arguments: each with the
local that supplies it, when a local does. -/
def pfPremises (s : PFState) (app : Expr) : MetaM (Array Json) := do
  let args := app.getAppArgs
  let mut t ← inferType app.getAppFn
  let mut out : Array Json := #[]
  for i in [:args.size] do
    t ← whnfD t
    let .forallE n d b _ := t | break
    if ← isProp d then
      let by_ := match args[i]!.consumeMData with
        | .fvar f => match s.index[f]? with | some j => Json.str s!"l{j}" | none => Json.null
        | _ => Json.null
      out := out.push (Json.mkObj [("arg", toJson i), ("name", n.eraseMacroScopes.toString),
        ("type", Json.mkObj [("text", Json.str (toString (← ppExpr d)))]), ("supplied_by", by_)])
    t := b.instantiate1 args[i]!
  return out

/-- The local context of the locals `ids` alone, so that a fact prints with the names of its own
context (another case's binder of the same name does not rename it). -/
def pfContext (s : PFState) (ids : Array Nat) : LocalContext :=
  ids.foldl (fun l i => l.addDecl (s.lctx.get! s.locals[i]!.fvar)) {}

def proofFactsRecord (h : IO.FS.Handle) (q : Query) (roots : Array Name) (n : Name) :
    MetaM Unit := do
  let env ← getEnv
  let some ci := env.find? n
    | emit h (Json.mkObj [("record", "proof-facts"), ("name", n.toString),
        ("errors", toJson #["missing"])])
  let value? := match ci with
    | .thmInfo t => some t.value | .defnInfo d => some d.value | .opaqueInfo o => some o.value
    | _ => none
  let some value := value?
    | emit h (Json.mkObj [("record", "proof-facts"), ("name", n.toString),
        ("kind", kindOf ci), ("errors", toJson #["no-value"])])
  let value ← instantiateMVars value
  let arity := ci.type.getForallBinderNames.length
  let init : PFState := { maxNodes := q.facts_nodes.getD factsMaxNodes,
                          maxItems := q.facts_items.getD factsMaxItems }
  let ((), s) ← (pfVisit roots value #[] #[] #[] .root arity).run init
  withLCtx s.lctx (← getLocalInstances) do
    let vars := s.locals.map (·.fvar)
    let mut items : Array Json := #[]
    let mut wanted : Std.HashSet Nat := {}
    let mut k := 0
    for it in s.items do
      -- Each fact is printed with a heartbeat budget of its own.
      let j? ← withCurrHeartbeats <| withLCtx (pfContext s it.ctx) (← getLocalInstances) do
        try
          let ty ← if it.kind == "application" then instantiateMVars (← inferType it.type)
            else pure it.type
          let needs ← pfNeeds s ty it.uses
          let alone ← mkForallFVars (needs.map (mkFVar s.locals[·]!.fvar)) ty
          let premises ← if it.kind == "application" then pfPremises s it.type else pure #[]
          pure (some (Json.mkObj [("id", Json.str s!"f{k}"), ("kind", Json.str it.kind),
            ("name", if it.name.isAnonymous then Json.null
              else Json.str it.name.eraseMacroScopes.toString),
            ("generated_name", toJson it.name.hasMacroScopes),
            ("head", if it.head.isAnonymous then Json.null else Json.str it.head.toString),
            ("type", ← ppJson ty vars), ("at", Json.str (toString it.pos)),
            ("context", toJson (it.ctx.map (s!"l{·}"))),
            ("uses", toJson (it.uses.map (s!"l{·}"))),
            ("local", match it.bound with | some i => Json.str s!"l{i}" | none => Json.null),
            ("needs", toJson (needs.map (s!"l{·}"))),
            ("scope", toJson (it.scope.map (s!"s{·}"))),
            ("premises", Json.arr premises),
            ("standalone", Json.mkObj [("text", Json.str (toString (← ppExpr alone)))]),
            ("fact_hash", Json.str (hex ((deepHash alone).run' {})))], it.ctx))
        catch _ => pure none
      if let some (j, ctx) := j? then
        items := items.push j
        for i in ctx do wanted := wanted.insert i
      k := k + 1
    let mut locals : Array Json := #[]
    let mut scopes : Std.HashSet Nat := {}
    for i in wanted.toArray.qsort (· < ·) do
      let l := s.locals[i]!
      let d := s.lctx.get! l.fvar
      let prop ← isProp d.type
      let role := if d.binderInfo.isInstImplicit then "instance"
        else if prop then "hypothesis" else "variable"
      for sc in l.scope do scopes := scopes.insert sc
      locals := locals.push (Json.mkObj [("id", Json.str s!"l{i}"),
        ("name", Json.str d.userName.eraseMacroScopes.toString),
        ("generated_name", toJson d.userName.hasMacroScopes), ("role", Json.str role),
        ("origin", Json.str l.origin), ("scope", toJson (l.scope.map (s!"s{·}"))),
        ("type", ← withCurrHeartbeats <| withLCtx (pfContext s l.ctx) (← getLocalInstances) do
          ppJson d.type vars)])
    for it in s.items do
      for sc in it.scope do scopes := scopes.insert sc
    let scopesJson := (scopes.toArray.qsort (· < ·)).map fun i =>
      let (c, a) := s.scopes[i]!
      Json.mkObj [("id", Json.str s!"s{i}"), ("head", Json.str c.toString), ("arg", toJson a)]
    let axs ← collectAxioms n
    emit h (Json.mkObj [("record", "proof-facts"), ("name", n.toString), ("kind", kindOf ci),
      ("module", (moduleOf env n).toString), ("range", ← rangeJson n), ("errors", Json.arr #[]),
      ("statement", ← ppJson ci.type),
      ("proof_hash", Json.str (hex ((deepHash value).run' {}))),
      ("axioms", toJson (axs.map toString)), ("sorry", toJson (axs.contains ``sorryAx)),
      ("facts", Json.arr items), ("locals", Json.arr locals), ("scopes", Json.arr scopesJson),
      ("visited", toJson s.visited), ("cut", toJson s.cut),
      ("auxiliary", toJson (s.aux.map toString)),
      ("limits", Json.mkObj [("nodes", toJson s.maxNodes), ("facts", toJson s.maxItems)])])

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
  if q.specLayer.any (·.isAnonymous) || q.acceptLayer.any (·.isAnonymous) then
    emit h (Json.mkObj [("record", "layering"), ("violations", Json.arr #[])])
    return
  let env ← getEnv
  let names := env.header.moduleNames
  let mut violations : Array Json := #[]
  for i in [:names.size] do
    let mod := names[i]!
    unless inLayer q.specLayer mod do continue
    let mut seen : NameSet := {}
    let mut stack : Array Name := #[mod]
    while !stack.isEmpty do
      let m := stack.back!
      stack := stack.pop
      if seen.contains m then continue
      seen := seen.insert m
      if inLayer q.acceptLayer m then
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
  let isInside ← scopeTest roots
  for n in ← projectConstants roots do
    let some ci := env.find? n | continue
    let (st, va) ← usedOf cache n ci
    let inside := fun (a : Array Name) =>
      Json.arr ((a.filter fun c => c != n && isInside c).map (Json.str ·.toString))
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
  let inside ← scopeTest roots
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
        | "spec" => specRecord h q inside seen r.name.toName
        | "accept" | "refute" =>
          proofRecord h q inside seen r.kind r.name.toName (r.spec.map (·.toName))
        | "witness" => proofRecord h q inside seen "witness" r.name.toName none
        | "index" => do indexRecords h roots; moduleDocRecords h roots
        | "moddocs" => moduleDocRecords h roots
        | "names" => namesRecord h (r.names.getD #[])
        | "link" => linkRecord h q inside seen r.name.toName
        | "deps" => depsRecords h inside r.name.toName
        | "proof-facts" => proofFactsRecord h q roots r.name.toName
        | "modules" => moduleRecords h
        | "decl" => do
          let env ← getEnv
          if let some ci := env.find? r.name.toName then
            let (j, used) ← declRecord inside r.name.toName ci
            seen.modify (·.insert r.name.toName)
            emit h j
            let members ← emitClosure h inside r.name.toName used seen
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
    -- Every record reaches the file before `done` says how many bytes precede it, so a
    -- reader can tell a complete output from one cut short. A write that fails (a full disk)
    -- raises here or in `emit`, and the session ends with an error.
    h.flush
    let bytes := (← System.FilePath.metadata opath).byteSize
    emit h (Json.mkObj [("record", "done"), ("bytes", toJson bytes.toNat)])
    h.flush
