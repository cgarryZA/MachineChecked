"""Search the project's declarations by mathematical content (#126).

Every user-facing declaration of the project's built modules is indexed from its complete
statement, its docstring, its name and the definitions its statement uses, whether or not it is
linked to a claim. A query is a claim's printed statement, a Lean expression or a few words; a
result says which terms it shares with the query and where they occur, which candidate it was
reached from when it uses one (a wrapper of a helper, say), and whether the order of its
quantifiers differs from the paper's.

The scoring is deterministic and inexpensive: no model, no Lean session. The terms of a text
are its words (split at underscores and capitals, lower case, with plurals and `-ed`/`-ing`
removed), the mathematical symbols it uses (`\\le` and `≤` are one term, `ℕ`, `Nat` and
"natural" another), its numerals, and the project constants it names. A term's weight is its
rarity among the project's declarations. A declaration's content score is the share of the
query's weight it covers, so 1 means it carries every term of the query.

The reader's search (`web/src/lib/retrieval.js`) implements the same terms and scores over the
exported index (`export_index`); `tests/fixtures/retrieval/cases.json` holds cases both must
answer identically. A result is a candidate to inspect: it never makes a link or changes a
status.
"""

from __future__ import annotations

import math
import re
import unicodedata

SCHEMA = "machinechecked/retrieval@1"

# Field weights: a term in the statement or the docstring counts fully; one in the name, or in
# the name or docstring of a definition the statement uses, counts half.
FIELDS = {"s": 1.0, "d": 1.0, "n": 0.5, "u": 0.5}
FIELD_WORDS = {"s": "its statement", "d": "its docstring", "n": "its name",
               "u": "the definitions it uses"}
MATCH_K = 0.5            # a term's match strength is w / (w + MATCH_K)
UNSEEN = 0.25            # the weight, relative to its rarity, of a query term no declaration has
QUERY_TF_MAX = 3
EXPAND_TOP = 10          # candidates whose users are added
EXPAND_MIN = 0.25        # ... when their content score is at least this
EXPAND_FACTOR = 0.9      # a user's score through a candidate
DIGITS = 6               # scores are compared rounded, so that every implementation agrees

TEX_MACROS = {
    "le": "≤", "leq": "≤", "leqslant": "≤", "ge": "≥", "geq": "≥", "geqslant": "≥",
    "ne": "≠", "neq": "≠", "lt": "<", "gt": ">",
    "sum": "∑", "prod": "∏", "int": "∫", "iint": "∫", "oint": "∫", "sqrt": "√",
    "infty": "∞", "in": "∈", "notin": "∉", "subseteq": "⊆", "subset": "⊂", "cup": "∪",
    "cap": "∩", "circ": "∘", "iff": "↔", "Leftrightarrow": "↔", "leftrightarrow": "↔",
    "neg": "¬", "lnot": "¬", "partial": "∂", "nabla": "∇", "times": "×",
    "forall": "∀", "exists": "∃", "lVert": "‖", "rVert": "‖", "Vert": "‖", "mid": "∣",
    "lfloor": "⌊", "rfloor": "⌋", "lceil": "⌈", "rceil": "⌉",
    "varepsilon": "ε", "epsilon": "ε", "delta": "δ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "sigma": "σ", "pi": "π", "alpha": "α", "beta": "β", "gamma": "γ", "theta": "θ",
    "vartheta": "θ", "phi": "φ", "varphi": "φ", "omega": "ω", "rho": "ρ", "varrho": "ρ",
    "tau": "τ", "xi": "ξ", "eta": "η", "kappa": "κ", "zeta": "ζ", "psi": "ψ", "chi": "χ",
    "Delta": "Δ", "Gamma": "Γ", "Lambda": "Λ", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ",
    "Theta": "Θ", "Omega": "Ω", "Pi": "Π", "Xi": "Ξ",
    "exp": "exp", "log": "log", "ln": "log", "sin": "sin", "cos": "cos", "tan": "tan",
    "lim": "lim", "limsup": "limsup", "liminf": "liminf", "sup": "sup", "inf": "inf",
    "max": "max", "min": "min", "det": "det", "dim": "dim", "deg": "deg", "gcd": "gcd",
}
BLACKBOARD = {"N": "ℕ", "R": "ℝ", "Z": "ℤ", "Q": "ℚ", "C": "ℂ"}
# The symbols that are terms; others (=, +, →, brackets, ∀, ∃) occur in nearly everything.
# `a ≥ b` is the same term as `b ≤ a`, the way Lean states it.
SYMBOLS = set("≤<≠∑∏∫√∞∈∉⊆⊂∪∩∘↔¬∂∇×‖^∣⌊⌋⌈⌉ℕℝℤℚℂ"
              "αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ")
SYMBOL_ALIASES = {"≥": "≤", ">": "<", "⩽": "≤", "⩾": "≤", "≦": "≤", "≧": "≤", "ϵ": "ε", "ϑ": "θ", "ϕ": "φ",
                  "ϱ": "ρ", "∥": "‖", "⁻": "^"}
ASCII_OPS = {"<=": "≤", ">=": "≤", "!=": "≠", "<->": "↔"}
# Words, Lean name parts and abbreviations that stand for a symbol or a longer word.
WORD_TERMS = {
    "nat": ["§ℕ"], "natural": ["§ℕ"], "real": ["§ℝ"], "reals": ["§ℝ"], "int": ["§ℤ"],
    "integer": ["§ℤ"], "integers": ["§ℤ"], "rat": ["§ℚ"], "rational": ["§ℚ"],
    "complex": ["§ℂ"], "sq": ["square"], "pow": ["power"], "le": ["§≤"], "lt": ["§<"],
    "ge": ["§≤"], "gt": ["§<"], "ne": ["§≠"], "pos": ["positive"], "neg": ["negative"],
    "nonneg": ["nonnegative"], "abs": ["absolute"], "deriv": ["derivative"],
    "inv": ["inverse"], "sqrt": ["§√"], "norm": ["§‖"], "prod": ["product"],
    "card": ["cardinality"], "dist": ["distance"], "lim": ["limit"], "tendsto": ["limit"],
    "exp": ["exponential"], "log": ["logarithm"], "sup": ["supremum"], "inf": ["infimum"],
    "iff": ["§↔"], "dvd": ["§∣"], "divides": ["§∣"], "mem": ["§∈"], "subset": ["§⊆"],
    "eq": [], "mk": [], "def": [], "fun": [], "type": [], "prop": [], "sort": [],
    "true": [], "false": [], "self": [], "aux": [], "lemma": [], "theorem": [],
    "bdd": ["bound"], "converge": ["limit"], "converges": ["limit"], "convergent": ["limit"],
    "convergence": ["limit"], "zero": ["#0"], "one": ["#1"], "two": ["#2"], "twice": ["#2"], "double": ["#2"],
    "three": ["#3"], "thrice": ["#3"],
}
STOP = set("""a an the of and or to in on for with by is are be been being that this these
those it its as at from then if let we our us any every each all there exist exists some such
holds hold which where when whenever whose who than so not no into onto over under also only
may can must will shall have has had do does given suppose assume assuming show shows prove
proves proved proof statement paper result results above below following follow follows
hence thus therefore i ii iii iv v vi satisfy satisfies satisfying equal equals denote
denotes call called say write consider define defined mean means give gives obtain obtains
get""".split())
ENV_WORDS = set("""theorem thm lemma lem proposition prop corollary cor definition defn
remark rem example assumption hypothesis conjecture claim section sec equation eq""".split())

# What another implementation of `terms` and `Retrieval.search` reads from an exported index,
# so that both use the same tables and constants.
PARAMS = {"fields": FIELDS, "match_k": MATCH_K, "unseen": UNSEEN, "query_tf_max": QUERY_TF_MAX,
          "expand_top": EXPAND_TOP, "expand_min": EXPAND_MIN, "expand_factor": EXPAND_FACTOR,
          "digits": DIGITS}
TABLES = {"tex_macros": TEX_MACROS, "blackboard": BLACKBOARD, "symbols": "".join(sorted(SYMBOLS)),
          "symbol_aliases": SYMBOL_ALIASES, "ascii_ops": ASCII_OPS, "word_terms": WORD_TERMS,
          "stop": sorted(STOP), "env_words": sorted(ENV_WORDS), "field_words": FIELD_WORDS}

_TEX_COMMENT = re.compile(r"(?<!\\)%[^\n]*")
_TEX_DROP = re.compile(r"\\(?:label|ref|eqref|cref|Cref|autoref|cite|citep|citet|lean|leanok|"
                       r"mathlibok|notready|uses)\*?(?:\[[^\]]*\])?(?:\{[^{}]*\})?")
_TEX_BB = re.compile(r"\\(?:mathbb|mathbf|bm)\s*\{?\s*([A-Za-z])\s*\}?")
_TEX_CMD = re.compile(r"\\([A-Za-z]+)")
_TEX_SPACE = re.compile(r"\\[,;:! ]")
_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_'!?]*(?:\.[A-Za-z_][A-Za-z0-9_'!?]*)*|[0-9]+|"
                    r"<->|<=|>=|!=|\\\||\S")
_CAMEL = re.compile(r"([a-z0-9])([A-Z])|([A-Z]+)([A-Z][a-z])")


def _stem(w: str) -> str:
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if w.endswith("sses"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed") and not w.endswith("eed"):
        return w[:-2]
    return w


def _word_terms(piece: str) -> list[str]:
    """The terms of one word or name part (already lower case)."""
    if re.fullmatch(r"[0-9]+", piece):
        return ["#" + (piece.lstrip("0") or "0")]
    if piece in WORD_TERMS:
        return list(WORD_TERMS[piece])
    if len(piece) < 2 or piece in STOP or piece in ENV_WORDS:
        return []
    return [_stem(piece)]


def _split_name(part: str) -> list[str]:
    part = _CAMEL.sub(lambda m: (m.group(1) or m.group(3)) + " " + (m.group(2) or m.group(4)),
                      part)
    return [p.lower() for p in re.split(r"[_\s'!?]+", part) if p]


def prepare_tex(text: str) -> str:
    """A LaTeX passage with its comments, labels, references and `\\lean` tags removed and its
    symbol macros replaced by the symbols."""
    text = _TEX_COMMENT.sub(" ", text or "")
    text = _TEX_DROP.sub(" ", text)
    text = _TEX_BB.sub(lambda m: " " + BLACKBOARD.get(m.group(1).upper(), " ") + " "
                       if m.group(1).isupper() else " ", text)
    text = _TEX_SPACE.sub(" ", text)
    text = text.replace("\\|", " ‖ ")
    return _TEX_CMD.sub(lambda m: " " + TEX_MACROS.get(m.group(1), " ") + " ", text)


def terms(text: str, constants: bool = True) -> list[str]:
    """The terms of a text, in order: words (`odd`), symbols (`§≤`), numerals (`#2`) and, for
    dotted names, the constant (`@Plain.Odd`) with the words of its last part."""
    out: list[str] = []
    toks = _TOKEN.findall(prepare_tex(unicodedata.normalize("NFC", text or "")))
    for k, tok in enumerate(toks):
        c = tok[0]
        if "A" <= c <= "Z" or "a" <= c <= "z" or c == "_":
            tok = tok.rstrip("'!?")
            parts = tok.split(".")
            if len(parts) > 1 and constants and all(parts):
                out.append("@" + tok)
            for p in _split_name(parts[-1]):
                out += _word_terms(p)
        elif "0" <= c <= "9":
            out += _word_terms(tok)
        elif tok in ASCII_OPS:
            out.append("§" + ASCII_OPS[tok])
        else:
            s = SYMBOL_ALIASES.get(tok, tok)
            if s in SYMBOLS:
                out.append("§" + s)
            # A power 2 (`n ^ 2`, `n^{2}`) is also a square.
            if s == "^" and [t for t in toks[k + 1:k + 3] if t != "{"][:1] == ["2"]:
                out.append("square")
    return out


def display_term(t: str) -> str:
    return t[1:] if t[:1] in "§#@" else t


# -- the order of quantifiers ----------------------------------------------------------------------

_PAPER_Q = re.compile(r"∀|\bfor (?:all|every|each|any)\b|\bwhenever\b|∃|\bthere (?:exists?|is|are)\b"
                      r"|\bfor some\b", re.I)
_OPEN, _CLOSE = "([{⟨⦃", ")]}⟩⦄"


def _collapse(seq: list[str]) -> str:
    out = ""
    for q in seq:
        if not out or out[-1] != q:
            out += q
    return out


def paper_quantifiers(text: str) -> str:
    """The order in which a passage introduces quantifiers, as `∀` and `∃` (repeats merged)."""
    t = prepare_tex(text)
    return _collapse(["∃" if m.group(0) == "∃" or m.group(0).lower().startswith(("there", "for some"))
                      else "∀" for m in _PAPER_Q.finditer(t)])


def _top_level(s: str, sep: str) -> int:
    depth = 0
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
        elif depth == 0 and s.startswith(sep, i):
            return i
        i += 1
    return -1


def lean_quantifiers(ty: str) -> str:
    """The order of the quantifiers a Lean statement's text opens with and its conclusion opens
    with, skipping its hypotheses (repeats merged). A binder `(x : T) →` counts as `∀`."""
    seq: list[str] = []
    s = (ty or "").strip()
    for _ in range(200):
        s = s.lstrip()
        if s[:1] in ("∀", "∃"):
            seq.append(s[0])
            j = _top_level(s, ",")
            if j < 0:
                break
            s = s[j + 1:]
            continue
        j = _top_level(s, "→")
        if j < 0:
            break
        head = s[:j].strip()
        if head[:1] in "({⦃[" and " : " in head:
            seq.append("∀")
        s = s[j + 1:]
    return _collapse(seq)


def quantifier_difference(paper: str, lean: str) -> str | None:
    """A plain sentence when the paper and a statement end with `∀` and `∃` in opposite orders
    (`∃ C, ∀ n` against `∀ n, ∃ C`). Only the last alternation is compared: a paper often
    leaves the outer `for all` of its inputs unsaid."""
    if len(paper) < 2 or len(lean) < 2:
        return None
    paper, lean = paper[-2:], lean[-2:]
    if paper == lean:
        return None
    words = lambda q: " then ".join("for all" if c == "∀" else "there is" for c in q)
    return (f"the quantifiers come in a different order (the paper: {words(paper)}; the Lean "
            f"statement: {words(lean)}), so what each choice may depend on differs")


# -- the index -------------------------------------------------------------------------------------

def strip_references(text: str) -> str:
    """A docstring without its references to numbered statements (`Theorem 2.1`), which are a
    separate signal (`numbering.py`) and say nothing of the content."""
    from .numbering import REF
    return REF.sub(" ", text or "")


def _short(name: str) -> str:
    return name.rsplit(".", 1)[-1]


def _doc_terms(d: dict, by_name: dict) -> dict[str, list]:
    """A declaration's weighted terms: {term: [weight, field codes]}."""
    acc: dict[str, list] = {}

    def add(ts, f):
        for t in ts:
            e = acc.setdefault(t, [0.0, ""])
            e[0] += FIELDS[f]
            if f not in e[1]:
                e[1] += f

    uses = [u for u in d.get("uses") or [] if u != d["name"]]
    st = terms(d.get("type") or "")
    if uses:
        st = [t for t in st if not t.startswith("@")] + ["@" + u for u in sorted(set(uses))]
    add(st, "s")
    add(terms(strip_references(d.get("doc") or ""), constants=False), "d")
    add(terms(_short(d["name"]), constants=False), "n")
    for u in sorted(set(uses)):
        r = by_name.get(u)
        if r is None or r.get("kind") == "theorem":
            continue
        add(set(terms(_short(u), constants=False))
            | set(terms(strip_references(r.get("doc") or ""), constants=False)), "u")
    return {t: [round(w, 3), "".join(sorted(f, key="sdnu".index))] for t, (w, f) in
            sorted(acc.items())}


class Retrieval:
    """The content index of a set of declarations, and searches over it."""

    def __init__(self, docs: list[dict]):
        self.docs = sorted(docs, key=lambda d: (d["name"], d.get("module") or ""))
        self.by_name = {}
        for i, d in enumerate(self.docs):
            self.by_name.setdefault(d["name"], i)
        self.df: dict[str, int] = {}
        self.postings: dict[str, list[int]] = {}
        for i, d in enumerate(self.docs):
            for t in d["t"]:
                self.df[t] = self.df.get(t, 0) + 1
                self.postings.setdefault(t, []).append(i)
        self.used_by: dict[str, list[tuple[str, str]]] = {}
        for d in self.docs:
            for u in sorted(set(d.get("value_uses") or [])):
                self.used_by.setdefault(u, []).append((d["name"], "value"))
            for u in sorted(set(d.get("uses") or [])):
                self.used_by.setdefault(u, []).append((d["name"], "statement"))
        self._sig: dict[int, str] = {}

    @classmethod
    def build(cls, index: list[dict]) -> "Retrieval":
        """The index of probe `index` records (complete statements)."""
        by_name = {d["name"]: d for d in index}
        return cls([{"name": d["name"], "kind": d.get("kind"), "module": d.get("module"),
                     "line": (d.get("range") or {}).get("line"),
                     "type": d.get("type") or "", "doc": d.get("doc"),
                     "uses": list(d.get("uses") or []),
                     "value_uses": list(d.get("value_uses") or []),
                     "t": _doc_terms(d, by_name)} for d in index])

    def export(self) -> dict:
        """The index as the reader's search and `compare` read it."""
        return {"schema": SCHEMA, "params": PARAMS, "tables": TABLES, "docs": self.docs}

    @classmethod
    def from_export(cls, data: dict) -> "Retrieval":
        if (data or {}).get("schema") != SCHEMA:
            raise ValueError("not a retrieval index of this version")
        return cls(data["docs"])

    def __len__(self):
        return len(self.docs)

    def idf(self, t: str) -> float:
        n = len(self.docs)
        df = self.df.get(t, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    @staticmethod
    def query_counts(q: str | list[str]) -> dict[str, int]:
        ts = terms(q) if isinstance(q, str) else q
        out: dict[str, int] = {}
        for t in ts:
            out[t] = min(QUERY_TF_MAX, out.get(t, 0) + 1)
        return out

    def _weights(self, qc: dict[str, int]) -> tuple[dict[str, float], float]:
        """Each query term's weight, and their total. A term no declaration has cannot be
        matched by any; it counts `UNSEEN` of its rarity, as prose more often than content."""
        w = {t: n * self.idf(t) for t, n in qc.items()}
        total = sum(v * (1 if self.df.get(t) else UNSEEN) for t, v in w.items())
        return w, total

    def score_doc(self, qc: dict[str, int], i: int, _w=None) -> tuple[float, list]:
        """The content score of doc `i` for query counts `qc`, and its matched terms with each
        one's contribution, largest first."""
        w, total = _w or self._weights(qc)
        if total <= 0:
            return 0.0, []
        t_d = self.docs[i]["t"]
        got, matched = 0.0, []
        for t, wt in w.items():
            e = t_d.get(t)
            if e:
                c = wt * e[0] / (e[0] + MATCH_K)
                got += c
                matched.append((t, c, e[1]))
        matched.sort(key=lambda x: (-round(x[1], DIGITS), x[0]))
        return round(got / total, DIGITS), matched

    def similarity(self, qc: dict[str, int], i: int) -> float:
        """How closely doc `i` and a paper passage (query counts `qc`) say the same thing: the
        geometric mean of the share of the passage the declaration carries (`score_doc`) and
        the share of the declaration's own statement and docstring the passage carries. Used to
        compare one declaration with several passages; constants, which a passage never
        names, are left out of the second share."""
        fwd = self.score_doc(qc, i)[0]
        own = {t: e[0] for t, e in self.docs[i]["t"].items()
               if not t.startswith("@") and ("s" in e[1] or "d" in e[1])}
        total = sum(self.idf(t) for t in own)
        if total <= 0:
            return 0.0
        back = sum(self.idf(t) for t in own if t in qc) / total
        return round(math.sqrt(fwd * back), DIGITS)

    def signature(self, i: int) -> str:
        if i not in self._sig:
            self._sig[i] = lean_quantifiers(self.docs[i].get("type") or "")
        return self._sig[i]

    def search(self, query: str | list[str], kinds=None, limit: int | None = 20,
               after: str | None = None, exclude=(), paper_order: str | None = None,
               min_score: float = 0.0) -> dict:
        """The declarations best matching `query`, best first, each with its reasons.

        `kinds`, a predicate on a declaration's kind, restricts the results; `exclude` names
        declarations left out. The best candidates' users (a wrapper whose proof applies one,
        a theorem whose statement mentions one) join the results with that relationship, at
        `EXPAND_FACTOR` of the candidate's score when that is more than their own. Ties are
        broken by name. `paper_order` is the paper's quantifier order (`paper_quantifiers`):
        a result whose order differs says so; its score is unchanged."""
        qc = self.query_counts(query)
        w, total = self._weights(qc)
        ok = (lambda i: kinds(self.docs[i].get("kind"))) if kinds else (lambda i: True)
        # Term at a time: each declaration's sum is taken in the query's term order, as
        # `score_doc` takes it.
        acc: dict[int, float] = {}
        for t, wt in w.items():
            for i in self.postings.get(t, ()):
                e = self.docs[i]["t"][t][0]
                acc[i] = acc.get(i, 0.0) + wt * e / (e + MATCH_K)
        hits: dict[int, dict] = {}
        if total > 0:
            for i, got in acc.items():
                c = round(got / total, DIGITS)
                if c > 0:
                    hits[i] = {"score": c, "content": c, "via": None}
        key = lambda i: (-hits[i]["score"], self.docs[i]["name"])
        top = sorted((i for i in hits if ok(i)), key=key)[:EXPAND_TOP]
        for i in top:
            if hits[i]["content"] < EXPAND_MIN:
                continue
            name = self.docs[i]["name"]
            for user, rel in self.used_by.get(name, ()):
                j = self.by_name.get(user)
                if j is None or j == i:
                    continue
                sc = round(EXPAND_FACTOR * hits[i]["content"], DIGITS)
                h = hits.get(j)
                if h is None:
                    hits[j] = h = {"score": 0.0, "content": 0.0, "via": None}
                if sc > h["score"]:
                    h["score"], h["via"] = sc, {"name": name, "relation": rel}
        excl = set(exclude)
        order = sorted((i for i, h in hits.items() if ok(i) and h["score"] >= min_score
                        and h["score"] > 0 and self.docs[i]["name"] not in excl), key=key)
        begin = 0
        if after:
            names = [self.docs[i]["name"] for i in order]
            if after not in names:
                raise ValueError(f"cursor {after!r} is not a result of this search")
            begin = names.index(after) + 1
        part = order[begin:begin + limit] if limit else order[begin:]
        more = begin + len(part) < len(order)
        return {"results": [self._result(i, hits[i], qc, paper_order) for i in part],
                "query": {"terms": [display_term(t) for t in qc]},
                "page": {"total": len(order), "returned": len(part), "after": after,
                         "next": self.docs[part[-1]]["name"] if more and part else None,
                         "complete": not more and not begin}}

    def _result(self, i: int, h: dict, qc: dict, paper_order: str | None) -> dict:
        d = self.docs[i]
        reasons = []
        matched = self.score_doc(qc, i)[1] if h["content"] else []
        if matched:
            reasons.append(content_reason(matched, h["content"]))
        if h["via"]:
            v = h["via"]
            rel = {"value": "its proof uses" if d.get("kind") == "theorem" else "its body uses",
                   "statement": "its statement mentions"}[v["relation"]]
            reasons.append({"signal": "uses", "via": v["name"], "relation": v["relation"],
                            "text": f"{rel} {v['name']}, a close match"})
        if paper_order:
            diff = quantifier_difference(paper_order, self.signature(i))
            if diff:
                reasons.append({"signal": "structure", "text": diff,
                                "paper": paper_order, "lean": self.signature(i)})
        return {"name": d["name"], "kind": d.get("kind"), "module": d.get("module"),
                "line": d.get("line"), "score": h["score"], "content": h["content"],
                "reasons": reasons, "statement": d.get("type") or "", "complete": True,
                "doc": d.get("doc")}


def content_reason(matched: list, score: float) -> dict:
    """The terms a declaration shares with the query (the five that weigh most), and where."""
    top = matched[:5]
    where = "".join(sorted({f for _, _, fs in top for f in fs}, key="sdnu".index))
    shared = ", ".join(display_term(t) for t, _, _ in top)
    places = [FIELD_WORDS[f] for f in where]
    place = places[0] if len(places) == 1 else ", ".join(places[:-1]) + " and " + places[-1]
    return {"signal": "content", "score": score, "terms": [display_term(t) for t, _, _ in top],
            "fields": list(where), "text": f"shares {shared} (in {place})"}
