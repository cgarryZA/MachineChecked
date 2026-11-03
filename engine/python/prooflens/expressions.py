"""Expressions of the paper read as mathematics, put in a normal form and compared with the
Lean's.

The paper's side is read by a bounded TeX reader: sums and differences, products (`\\cdot`,
`\\times`, `*` or juxtaposition), quotients (`/`, `\\frac`), powers, numerals, identifiers (a
letter or a Greek letter, with a subscript, primes or a `*`), brackets of any size, `|·|` and
`\\|·\\|`, and a notation the caller matches with a Lean definition applied to its arguments
(`J_x(D, k, C)`). It gives the probe's `math` vocabulary (`op`, `num`, `local` for an
identifier, `apply` for a notation applied). Anything else is refused as "unsupported: …"; the
comparison then keeps both exact texts and compares nothing.

A notation applied is compared with Lean's application of a definition: when the paper's
notation is matched with another definition than the one Lean applies, the two differ in their
`head`; when it is the same definition, the arguments are compared in order.

Both sides are put in one normal form: a polynomial with rational coefficients, in which a
quotient by a monomial is a negative power and each absolute value or norm is a variable of its
own (with its constant factor taken out). Variables are compared only through a correspondence
the caller gives (an alignment of a requirement's variable with a Lean variable, or a symbol
link): a variable outside it leaves the pair not compared, never different. Lean's operations
are read in the type they are taken in: a subtraction Lean cuts off at zero (in ℕ) or a
quotient it rounds (in ℕ or ℤ) is not this arithmetic, and is not compared.

A comparison is a pointer for the auditor to inspect. It establishes nothing, and nothing reads
it as a status.
"""

from __future__ import annotations

import re
from fractions import Fraction

MAX_CHARS = 400
MAX_NODES = 400
MAX_TERMS = 256
MAX_EXPONENT = 32


class Unsupported(ValueError):
    """The paper's expression uses something the reader does not read."""


class NotCompared(ValueError):
    """The two expressions cannot be compared, and why."""


# -- identifiers -------------------------------------------------------------------------------

GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
         "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "θ",
         "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
         "varpi": "π", "rho": "ρ", "varrho": "ρ", "sigma": "σ", "varsigma": "σ", "tau": "τ",
         "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ", "psi": "ψ", "omega": "ω",
         "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ", "Pi": "Π",
         "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω", "ell": "ℓ"}
# Letters that are one letter in two shapes.
VARIANTS = {"ϵ": "ε", "ϑ": "θ", "ϱ": "ρ", "ς": "σ", "ϕ": "φ", "ϖ": "π"}


def name_key(name: str) -> str:
    """The identifier `name` (as TeX writes it, `C_{\\varepsilon}`, or in Unicode, `C_ε`) in one
    form, so that a requirement's variable and the paper's symbol are matched: Greek commands as
    their letters, one shape of each letter, without braces or spaces."""
    s = re.sub(r"\\([A-Za-z]+)", lambda m: GREEK.get(m.group(1), m.group(0)), str(name))
    s = s.replace("\\prime", "'").replace("\\ast", "*")
    s = re.sub(r"[{}\s]", "", s)
    return "".join(VARIANTS.get(ch, ch) for ch in s)


# -- the TeX reader ---------------------------------------------------------------------------

TOKEN = re.compile(r"\\[A-Za-z]+|\\.|\d+(?:\.\d+)?|\S", re.S)
SPACING = {"\\,", "\\;", "\\:", "\\!", "\\ ", "\\>", "~", "\\quad", "\\qquad"}
SIZES = {"\\left", "\\right", "\\big", "\\Big", "\\bigg", "\\Bigg", "\\bigl", "\\bigr", "\\Bigl",
         "\\Bigr", "\\biggl", "\\biggr", "\\Biggl", "\\Biggr", "\\bigm", "\\Bigm"}
OPEN = {"(": ")", "[": "]", "\\{": "\\}", "\\lbrace": "\\rbrace", "\\lbrack": "\\rbrack"}
CLOSE = set(OPEN.values())
ABS = {"|", "\\vert", "\\lvert", "\\rvert", "\\mid"}
NORM = {"\\|", "\\Vert", "\\lVert", "\\rVert", "‖"}
TIMES = {"\\cdot", "\\times", "*", "·", "×"}
MINUS = {"-", "−"}
FRAC = {"\\frac", "\\dfrac", "\\tfrac"}
DECORATIONS = {"*": "*", "\\ast": "*", "\\prime": "'", "'": "'"}


def _strip_math(tex: str) -> str:
    s = tex.strip()
    for a, b in (("$$", "$$"), ("$", "$"), ("\\(", "\\)"), ("\\[", "\\]")):
        if s.startswith(a) and s.endswith(b) and len(s) > len(a) + len(b):
            return s[len(a):-len(b)].strip()
    return s


class _Reader:
    def __init__(self, tex: str, heads: frozenset = frozenset()):
        self.toks = [t for t in TOKEN.findall(_strip_math(tex)) if t not in SPACING]
        self.i = 0
        self.nodes = 0
        self.heads = heads

    def peek(self, k: int = 0) -> str | None:
        j = self.i + k
        return self.toks[j] if j < len(self.toks) else None

    def take(self) -> str:
        t = self.peek()
        if t is None:
            raise Unsupported("unsupported: the expression ends too early")
        self.i += 1
        return t

    def node(self, **fields) -> dict:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise Unsupported("unsupported: the expression is too long to read")
        return fields

    def op(self, op: str, *args) -> dict:
        return self.node(k="op", op=op, args=list(args))

    def delim(self) -> str | None:
        """The delimiter at this point, after a size command (`\\left(` is `(`)."""
        t = self.peek()
        if t in SIZES:
            nxt = self.peek(1)
            return nxt if nxt in OPEN or nxt in CLOSE or nxt in ABS or nxt in NORM else None
        return t

    def take_delim(self) -> str:
        if self.peek() in SIZES:
            self.take()
        return self.take()

    # expr := ['-'|'+'] term (('+'|'-') term)*
    def expr(self, stop: frozenset) -> dict:
        node = self.term(stop)
        while self.peek() in MINUS or self.peek() == "+":
            op = "add" if self.take() == "+" else "sub"
            node = self.op(op, node, self.term(stop))
        return node

    def starts_factor(self, stop: frozenset) -> bool:
        d = self.delim()
        if d is None:
            return False
        if d in stop or d in CLOSE or d in MINUS or d in ("+", "/", "}", "^", "_") or d in TIMES:
            return False
        return True

    def term(self, stop: frozenset) -> dict:
        node = self.factor(stop)
        while True:
            t = self.peek()
            if t in TIMES:
                self.take()
                node = self.op("mul", node, self.factor(stop))
            elif t == "/":
                self.take()
                node = self.op("div", node, self.factor(stop))
            elif self.starts_factor(stop):
                if node.get("k") == "local" and self.delim() in ("(", "["):
                    raise Unsupported(f"unsupported: {node['tex']}(…) may be a function applied "
                                      "or a product")
                node = self.op("mul", node, self.factor(stop))
            else:
                return node

    def factor(self, stop: frozenset) -> dict:
        if self.peek() in MINUS:
            self.take()
            return self.op("neg", self.factor(stop))
        if self.peek() == "+":
            self.take()
            return self.factor(stop)
        base = self.primary(stop)
        if self.peek() == "^":
            self.take()
            base = self.op("pow", base, self.argument())
        return base

    def argument(self) -> dict:
        """A group `{…}`, or one token: what `^`, `\\frac` and `_` take."""
        t = self.peek()
        if t == "{":
            self.take()
            inner = self.expr(frozenset({"}"}))
            self.expect("}")
            return inner
        if t is not None and (t[0].isdigit() and "." not in t):
            # One token: `n^23` is n² · 3 in TeX.
            self.take()
            if len(t) > 1:
                self.toks[self.i:self.i] = [t[1:]]
                t = t[0]
            return self.node(k="num", value=t)
        return self.primary(frozenset())

    def expect(self, want: str) -> None:
        t = self.take()
        if t != want:
            raise Unsupported(f"unsupported: {t}" if t not in CLOSE | {"}"} else
                              f"unsupported: brackets that do not match ({t} where {want} closes)")

    def subscript(self) -> str:
        t = self.take()
        if t != "{":
            if t[0].isdigit() and len(t) > 1:
                # One token: `x_12` is x₁ · 2 in TeX.
                self.toks[self.i:self.i] = [t[1:]]
                t = t[0]
            return t
        depth, out = 1, []
        while True:
            t = self.take()
            if t == "{":
                depth += 1
            elif t == "}":
                depth -= 1
                if depth == 0:
                    return "{" + "".join(out) + "}"
            out.append(t)

    def identifier(self, t: str) -> dict:
        tex = t
        while True:
            nxt = self.peek()
            if nxt == "_" and "_" not in tex:
                self.take()
                tex += "_" + self.subscript()
            elif nxt == "'":
                self.take()
                tex += "'"
            elif nxt == "^" and (self.peek(1) in DECORATIONS or (
                    self.peek(1) == "{" and self.peek(2) in DECORATIONS and self.peek(3) == "}")):
                self.take()
                if self.take() == "{":
                    tex += "^{" + self.take() + "}"
                    self.take()
                else:
                    tex += "^" + self.toks[self.i - 1]
            else:
                break
        return self.node(k="local", name=name_key(tex.replace("^", "")), tex=tex)

    def primary(self, stop: frozenset) -> dict:
        d = self.delim()
        if d in OPEN:
            self.take_delim()
            inner = self.expr(frozenset({OPEN[d]}))
            if self.delim() != OPEN[d]:
                raise Unsupported("unsupported: brackets that do not match")
            self.take_delim()
            return inner
        if d in ABS or d in NORM:
            kind = "abs" if d in ABS else "norm"
            closing = ABS if kind == "abs" else NORM
            self.take_delim()
            inner = self.expr(frozenset(closing))
            if self.delim() not in closing:
                raise Unsupported("unsupported: brackets that do not match")
            self.take_delim()
            return self.op(kind, inner)
        t = self.peek()
        if t is None:
            raise Unsupported("unsupported: the expression ends too early")
        if t in SIZES:
            raise Unsupported(f"unsupported: {t}{self.peek(1) or ''}")
        self.take()
        if t == "{":
            inner = self.expr(frozenset({"}"}))
            self.expect("}")
            return inner
        if t[0].isdigit():
            return self.node(k="num", value=t)
        if t in FRAC:
            num = self.argument()
            den = self.argument()
            return self.op("div", num, den)
        if (len(t) == 1 and t.isalpha()) or (t.startswith("\\") and t[1:] in GREEK):
            node = self.identifier(t)
            if node["name"] in self.heads and self.delim() == "(":
                return self.application(node)
            return node
        raise Unsupported(f"unsupported: {t}")

    def application(self, head: dict) -> dict:
        """A notation the caller matches with a definition, applied to its arguments:
        `J_x(D, k, C)`."""
        self.take_delim()
        args = []
        while True:
            args.append(self.expr(frozenset({",", ")"})))
            d = self.delim()
            if d == ",":
                self.take()
            elif d == ")":
                self.take_delim()
                return self.node(k="apply", name=head["name"], tex=head["tex"], args=args)
            else:
                raise Unsupported("unsupported: brackets that do not match")


def read_tex(tex: str, heads=frozenset()) -> dict:
    """The expression `tex` (TeX, as the paper's source writes it) as mathematics, in the probe's
    `math` vocabulary. An identifier among `heads` (name keys) followed by a bracket is that
    notation applied (`apply`). Raises `Unsupported` for anything outside the reader's
    grammar."""
    if not isinstance(tex, str) or not tex.strip():
        raise Unsupported("unsupported: an empty expression")
    if len(tex) > MAX_CHARS:
        raise Unsupported(f"unsupported: an expression longer than {MAX_CHARS} characters")
    r = _Reader(tex, frozenset(heads))
    if not r.toks:
        raise Unsupported("unsupported: an empty expression")
    node = r.expr(frozenset())
    if r.peek() is not None:
        raise Unsupported(f"unsupported: {r.peek()}")
    return node


# -- the normal form --------------------------------------------------------------------------

# A polynomial: monomial -> coefficient, a monomial a sorted tuple of (variable key, power).
Poly = dict


def _const(c) -> Poly:
    c = Fraction(c)
    return {(): c} if c else {}


def _var(key: str) -> Poly:
    return {((key, 1),): Fraction(1)}


def _add(a: Poly, b: Poly) -> Poly:
    out = dict(a)
    for m, c in b.items():
        v = out.get(m, 0) + c
        if v:
            out[m] = v
        else:
            out.pop(m, None)
    return out


def _scale(a: Poly, c) -> Poly:
    return {m: v * c for m, v in a.items()} if c else {}


def _mono_mul(m1, m2):
    pw: dict[str, int] = dict(m1)
    for k, e in m2:
        pw[k] = pw.get(k, 0) + e
    return tuple(sorted((k, e) for k, e in pw.items() if e))


def _mul(a: Poly, b: Poly) -> Poly:
    out: Poly = {}
    for m1, c1 in a.items():
        for m2, c2 in b.items():
            out = _add(out, {_mono_mul(m1, m2): c1 * c2})
    if len(out) > MAX_TERMS:
        raise NotCompared("the normal form is too large to compare")
    return out


def _pow(a: Poly, n: int) -> Poly:
    if abs(n) > MAX_EXPONENT:
        raise NotCompared(f"a power {n} is too large to expand")
    if n < 0:
        if len(a) != 1:
            raise NotCompared("a negative power of a sum")
        (m, c), = a.items()
        return {tuple((k, -e) for k, e in m): 1 / c}
    out = _const(1)
    for _ in range(n):
        out = _mul(out, a)
    return out


def _constant(a: Poly) -> Fraction | None:
    if not a:
        return Fraction(0)
    if set(a) == {()}:
        return a[()]
    return None


class _Normal:
    """The normal form of one side. `key(node)` gives a variable's key, or raises `NotCompared`;
    `names` collects how each key is written on this side; `conditions` the divisors taken to
    be nonzero."""

    def __init__(self, key, side: str):
        self.key = key
        self.side = side
        self.names: dict[str, str] = {}
        self.conditions: list[str] = []
        self.used: list[str] = []

    def __call__(self, n) -> Poly:
        if not isinstance(n, dict):
            raise NotCompared("an expression the probe did not read")
        k = n.get("k")
        if k == "num":
            try:
                return _const(Fraction(str(n.get("value"))))
            except (ValueError, ZeroDivisionError):
                raise NotCompared(f"the number {n.get('value')}") from None
        if k in ("local", "var", "bound"):
            key, name = self.key(n)
            self.names.setdefault(key, name)
            if key not in self.used:
                self.used.append(key)
            return _var(key)
        if k == "coe" and n.get("kind") == "coe":
            # A cast between number types keeps the value: the arithmetic inside it is read in
            # its own type.
            return self(n.get("of"))
        if k == "op":
            return self.op(n)
        what = {"apply": f"{n.get('name')} applied", "lean": "an expression read as exact Lean",
                "rel": "a relation", "app": "a function applied"}.get(k, f"a {k}")
        raise NotCompared(f"{self.side} expression is {what}, not arithmetic")

    def carrier(self, n) -> str | None:
        c = n.get("in")
        return c.get("name") if isinstance(c, dict) and c.get("k") == "type" else None

    def op(self, n) -> Poly:
        op, args = n.get("op"), n.get("args") or []
        lean = self.side == "Lean's"
        typ = self.carrier(n) if lean else "field"
        numbers = ("nat", "int", "rat", "real", "complex", "nnreal", "ennreal", "field")
        if lean and op in ("add", "sub", "mul", "div", "neg", "pow") and typ not in numbers:
            raise NotCompared(f"Lean takes {op} in "
                              + (f"{typ}, not a number system" if typ else
                                 "a type the probe does not name"))
        if op == "succ" and len(args) == 1:
            return _add(self(args[0]), _const(1))
        if op in ("add", "sub", "mul") and len(args) == 2:
            a, b = self(args[0]), self(args[1])
            if op == "add":
                return _add(a, b)
            if op == "mul":
                return _mul(a, b)
            if typ in ("nat", "nnreal", "ennreal"):
                raise NotCompared(f"Lean's subtraction in {WORDS[typ]} is cut off at 0")
            return _add(a, _scale(b, -1))
        if op == "neg" and len(args) == 1:
            if typ in ("nat", "nnreal", "ennreal"):
                raise NotCompared(f"Lean's negation in {WORDS[typ]}")
            return _scale(self(args[0]), -1)
        if op == "div" and len(args) == 2:
            if typ in ("nat", "int", "ennreal"):
                raise NotCompared(f"Lean's division in {WORDS[typ]} is not exact")
            a, b = self(args[0]), self(args[1])
            c = _constant(b)
            if c == 0:
                raise NotCompared("a division by zero")
            if len(b) != 1:
                raise NotCompared("a division by a sum")
            if c is None:
                self.conditions.append(fmt(b, self.names) + " ≠ 0")
            return _mul(a, _pow(b, -1))
        if op == "pow" and len(args) == 2:
            e = _constant(self(args[1]))
            if e is None or e.denominator != 1:
                raise NotCompared("a power whose exponent is not a whole number")
            if e < 0 and typ in ("nat", "int"):
                raise NotCompared(f"a negative power in {WORDS[typ]}")
            return _pow(self(args[0]), int(e))
        if op in ("abs", "norm") and len(args) == 1:
            inner = self(args[0])
            if not inner:
                return {}
            lead = inner[min(inner, key=_order)]
            unit = _scale(inner, 1 / lead)
            body = fmt(unit, self.names)
            key = ("|" if op == "abs" else "‖") + _key_text(unit) + ("|" if op == "abs" else "‖")
            self.names.setdefault(key, f"|{body}|" if op == "abs" else f"‖{body}‖")
            return _scale(_var(key), abs(lead))
        raise NotCompared(f"{self.side} expression uses {op}, which is not compared")


WORDS = {"nat": "ℕ", "int": "ℤ", "rat": "ℚ", "real": "ℝ", "complex": "ℂ", "nnreal": "ℝ≥0",
         "ennreal": "ℝ≥0∞"}


def _order(m):
    return (-sum(abs(e) for _, e in m), m)


def _key_text(p: Poly) -> str:
    return ";".join(f"{c}:{','.join(f'{k}^{e}' for k, e in m)}" for m, c in sorted(p.items()))


def fmt(p: Poly, names: dict[str, str]) -> str:
    """A normal form as text: its terms by degree, a coefficient before its variables, a
    negative power as a quotient."""
    if not p:
        return "0"
    out = ""
    for i, m in enumerate(sorted(p, key=_order)):
        c = p[m]
        sign = "-" if c < 0 else "+"
        c = abs(c)
        num = [(names.get(k, k), e) for k, e in m if e > 0]
        den = [(names.get(k, k), -e) for k, e in m if e < 0]

        def part(fs):
            return "·".join(n if e == 1 else f"{n}^{e}" for n, e in sorted(fs))
        body = part(num)
        if c != 1 or not body:
            body = f"{c}" + ("·" + body if body else "")
        if den:
            body += "/" + (part(den) if len(den) == 1 else f"({part(den)})")
        out += (body if sign == "+" else "-" + body) if i == 0 else f" {sign} {body}"
    return out


# -- the comparison ---------------------------------------------------------------------------

KINDS = ("offset", "coefficient", "power", "terms", "head")
# A different definition says nothing about which feature differs (the variables differentiated,
# a norm, a domain): the auditor names it.
FEATURE = {"offset": "index offset", "coefficient": "weight", "power": "power",
           "terms": "other", "head": "other"}


def atoms(p: Poly) -> set[str]:
    return {k for m in p for k, _ in m}


def normal_paper(node: dict, pairs: dict[str, str]) -> tuple[Poly, _Normal]:
    """The paper's expression (`read_tex`) in normal form, its identifiers replaced through
    `pairs` (paper name key -> Lean variable key)."""
    def key(n):
        k = pairs.get(n.get("name"))
        if k is None:
            raise NotCompared(f"the paper's {n.get('name')} is aligned with no Lean variable")
        return k, n.get("name")
    norm = _Normal(key, "the paper's")
    return norm(node), norm


def normal_lean(node: dict, known: dict[str, str]) -> tuple[Poly, _Normal]:
    """Lean's expression (the probe's `math`) in normal form; `known` is each Lean variable key
    the paper's variables are aligned with, with its name."""
    def key(n):
        k = f"v:{n['var']}" if n.get("k") == "var" else f"b:{n.get('binder')}"
        if k not in known:
            raise NotCompared(f"Lean's {n.get('name')} is aligned with no variable of the paper")
        return k, n.get("name") or known[k]
    norm = _Normal(key, "Lean's")
    return norm(node), norm


def classify(paper: Poly, lean: Poly) -> dict | None:
    """How Lean's normal form differs from the paper's: None when they are the same."""
    if paper == lean:
        return None
    diff = _add(lean, _scale(paper, -1))
    c = _constant(diff)
    if c is not None:
        return {"kind": "offset", "difference": str(c)}
    if paper and set(paper) == set(lean):
        ratios = {lean[m] / paper[m] for m in paper}
        if len(ratios) == 1:
            return {"kind": "coefficient", "factor": str(ratios.pop())}
    if len(paper) == 1 and len(lean) == 1:
        (mp, cp), = paper.items()
        (ml, cl), = lean.items()
        if cp == cl and {k for k, _ in mp} == {k for k, _ in ml}:
            return {"kind": "power"}
    return {"kind": "terms"}


def compare(paper_tex: str, lean: dict | None, pairs: dict[str, str],
            known: dict[str, str], heads: dict | None = None) -> dict:
    """Compare the paper's expression `paper_tex` with Lean's `lean` (its `math`), the paper's
    identifiers matched with Lean's variables through `pairs` (name key -> Lean key; `known`
    gives each Lean key's name) and its notations with Lean's definitions through `heads` (name
    key -> definition, or a list of the definitions an ambiguous notation is matched with).
    `outcome` is `same`, `differs` (with the `kind` of difference, its `feature` and the
    `difference` or `factor`; for a notation applied, `head` with `heads`, or the difference of
    the one argument that differs, with its index `argument`), or `not compared` (with the
    `reason`); each side's normal form (`paper_normal`, `lean_normal`), the divisors taken to be
    nonzero (`conditions`) and the Lean variables matched (`used`)."""
    heads = heads or {}
    try:
        node = read_tex(paper_tex, frozenset(heads))
    except Unsupported as e:
        return {"outcome": "not compared", "reason": str(e)}
    return _compare_node(node, lean, pairs, known, heads)


def _compare_node(node: dict, lean: dict | None, pairs: dict[str, str], known: dict[str, str],
                  heads: dict) -> dict:
    if node.get("k") == "apply":
        return _compare_application(node, lean, pairs, known, heads)
    try:
        p, pn = normal_paper(node, pairs)
        if lean is None:
            raise NotCompared("Lean's expression is not read as mathematics in this build")
        q, qn = normal_lean(lean, known)
    except NotCompared as e:
        return {"outcome": "not compared", "reason": str(e)}
    out = {"paper_normal": fmt(p, pn.names), "lean_normal": fmt(q, qn.names),
           "conditions": list(dict.fromkeys(pn.conditions + qn.conditions)),
           "used": list(dict.fromkeys(pn.used + qn.used))}
    how = classify(p, q)
    if how is None:
        return {"outcome": "same", **out}
    return {"outcome": "differs", **how, "feature": FEATURE[how["kind"]], **out}


def _compare_application(node: dict, lean: dict | None, pairs: dict[str, str],
                         known: dict[str, str], heads: dict) -> dict:
    """The paper's notation applied (`node`) against Lean's application of a definition: a
    `head` difference when the notation is matched with another definition; with the same one,
    the arguments compared in order, and the one that differs gives the difference
    (`argument`: its index and both normal forms)."""
    head = heads.get(node["name"])
    if isinstance(head, (list, tuple)):
        return {"outcome": "not compared",
                "reason": f"the paper's {node['tex']} is aligned with more than one declaration "
                          f"({', '.join(head)})"}
    if not isinstance(lean, dict):
        return {"outcome": "not compared",
                "reason": "Lean's expression is not read as mathematics in this build"}
    if lean.get("k") != "apply":
        return {"outcome": "not compared",
                "reason": f"the paper's expression applies {node['tex']}, and Lean's is not an "
                          "application of a definition"}
    pair = {"paper": {"notation": node["tex"], "decl": head}, "lean": lean.get("name")}
    if lean.get("name") != head:
        return {"outcome": "differs", "kind": "head", "feature": FEATURE["head"], "heads": pair,
                "conditions": [], "used": []}
    pa, la = node.get("args") or [], lean.get("args") or []
    if len(pa) != len(la):
        return {"outcome": "not compared", "heads": pair,
                "reason": f"the paper applies {node['tex']} to {len(pa)} argument(s), and Lean "
                          f"applies {head} to {len(la)}"}
    results, diffs = [], []
    for i, (p, q) in enumerate(zip(pa, la)):
        r = _compare_node(p, q, pairs, known, heads)
        if r["outcome"] == "not compared":
            return {"outcome": "not compared", "heads": pair,
                    "reason": f"argument {i + 1} of {head}: {r['reason']}"}
        results.append(r)
        if r["outcome"] == "differs":
            diffs.append(i)
    out = {"heads": pair,
           "paper_normal": f"{node['tex']}({', '.join(r.get('paper_normal') or '…' for r in results)})",
           "lean_normal": f"{head}({', '.join(r.get('lean_normal') or '…' for r in results)})",
           "conditions": list(dict.fromkeys(c for r in results for c in r.get("conditions") or [])),
           "used": list(dict.fromkeys(u for r in results for u in r.get("used") or []))}
    if not diffs:
        return {"outcome": "same", **out}
    if len(diffs) > 1:
        return {"outcome": "differs", "kind": "terms", "feature": FEATURE["terms"],
                "arguments": diffs, **out}
    i = diffs[0]
    r = results[i]
    return {"outcome": "differs", "kind": r["kind"], "feature": r["feature"],
            **{k: r[k] for k in ("difference", "factor") if k in r}, **out,
            "argument": {"index": i, "paper_normal": r.get("paper_normal"),
                         "lean_normal": r.get("lean_normal"),
                         **({"heads": r["heads"]} if r.get("heads") else {})}}


def paper_head(paper_tex: str, heads: dict) -> str | None:
    """The notation the paper's expression applies (its name key), when the whole expression is
    a notation of `heads` applied; None otherwise."""
    if not heads:
        return None
    try:
        node = read_tex(paper_tex, frozenset(heads))
    except Unsupported:
        return None
    return node["name"] if node.get("k") == "apply" else None


def paper_atoms(paper_tex: str, pairs: dict[str, str]) -> set[str] | None:
    """The Lean variable keys the paper's expression uses, through `pairs`; None when it cannot
    be read or uses a variable outside them."""
    try:
        return atoms(normal_paper(read_tex(paper_tex), pairs)[0])
    except (Unsupported, NotCompared):
        return None


def lean_atoms(node: dict, known: dict[str, str]) -> set[str] | None:
    try:
        return atoms(normal_lean(node, known)[0])
    except NotCompared:
        return None
