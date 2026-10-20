"""A synthetic content-matching corpus for the retrieval (#126): declarations as the probe's
index records give them (complete statements as Lean prints them, docstrings, the project
constants each statement and value uses) and paper claims, each with the declaration that
states it. Names and docstring numbers are deliberately unhelpful in several cases."""

from __future__ import annotations

import random

FILLER = " → ".join(f"0 ≤ x{i}" for i in range(700))    # a statement over 4000 characters


def decl(name, type_, doc=None, kind="theorem", uses=(), value_uses=(), line=1):
    return {"record": "index", "name": name, "kind": kind, "module": name.rsplit(".", 1)[0],
            "range": {"line": line}, "type": type_, "doc": doc, "uses": list(uses),
            "value_uses": list(value_uses)}


DECLS = [
    decl("Seq.bounded_of_tendsto",
         "∀ {u : ℕ → ℝ} {L : ℝ}, Filter.Tendsto u Filter.atTop (nhds L) → ∃ C, ∀ (n : ℕ), |u n| ≤ C",
         "A convergent sequence is bounded."),
    # No docstring, and a name that says nothing.
    decl("Seq.aux7",
         "∀ (u : ℕ → ℝ), Monotone u → BddAbove (Set.range u) → ∃ L, Filter.Tendsto u Filter.atTop (nhds L)"),
    # A docstring with the number of an earlier version of the paper.
    decl("Ineq.amgm_two", "∀ (a b : ℝ), 0 ≤ a → 0 ≤ b → √(a * b) ≤ (a + b) / 2",
         "Theorem 3.2: the arithmetic-geometric mean inequality for two numbers."),
    decl("Ineq.cauchy_schwarz_fin",
         "∀ (n : ℕ) (x y : Fin n → ℝ), (∑ i, x i * y i) ^ 2 ≤ (∑ i, x i ^ 2) * ∑ i, y i ^ 2"),
    decl("Ineq.triangle_abs", "∀ (a b : ℝ), |a + b| ≤ |a| + |b|"),
    decl("Num.prime_factor_exists", "∀ (n : ℕ), 2 ≤ n → ∃ p, Nat.Prime p ∧ p ∣ n",
         "Every integer at least two has a prime factor."),
    decl("Num.inf_primes", "∀ (n : ℕ), ∃ p, n ≤ p ∧ Nat.Prime p"),
    decl("Num.gcd_dvd_left'", "∀ (a b : ℕ), Nat.gcd a b ∣ a"),
    decl("Num.IsPerfect", "ℕ → Prop",
         "A number is perfect when it is the sum of its proper divisors.", kind="def"),
    decl("Num.six_perfect", "Num.IsPerfect 6", uses=["Num.IsPerfect"]),
    # A specialised helper, and the generic estimate whose proof uses it.
    decl("Fn.deriv_inv_bound_aux", "∀ (x : ℝ), 1 ≤ x → |deriv (fun y => y⁻¹) x| ≤ 1",
         "The derivative of the inverse function is bounded by one on [1, ∞)."),
    decl("Fn.main_estimate",
         "∀ (k : ℕ) (x : ℝ), 1 ≤ x → |iteratedDeriv k (fun y => y⁻¹) x| ≤ ↑k.factorial",
         value_uses=["Fn.deriv_inv_bound_aux"]),
    # The same words, with the quantifiers in either order.
    decl("Unif.exists_const_forall", "∃ C, ∀ (n : ℕ), Unif.f n ≤ C",
         "A bound for f by a constant.", uses=["Unif.f"]),
    decl("Unif.forall_exists_const", "∀ (n : ℕ), ∃ C, Unif.f n ≤ C",
         "A bound for f by a constant.", uses=["Unif.f"]),
    decl("Unif.f", "ℕ → ℕ", "The sequence f.", kind="def"),
    # Two long statements that differ only after character 4000.
    decl("Long.big_a", f"∀ (g : ℕ → ℝ), {FILLER} → Summable g → ∃ s, HasSum g s"),
    decl("Long.big_b", f"∀ (g : ℕ → ℝ), {FILLER} → Integrable g → ∃ s, HasSum g s"),
    # A name citing a number, with unrelated content.
    decl("Seq.thm_4_1", "∀ (a : ℕ), a + 0 = a", "Theorem 4.1."),
]

CLAIMS = [
    ("A", "Every convergent sequence of real numbers is bounded: if $u_n \\to L$ then there is "
          "$C$ with $|u_n| \\le C$ for all $n$.", "Seq.bounded_of_tendsto"),
    ("B", "A monotone sequence of real numbers that is bounded above converges.", "Seq.aux7"),
    ("C", "For nonnegative real numbers $a, b$ we have $\\sqrt{ab} \\le \\frac{a+b}{2}$.",
     "Ineq.amgm_two"),
    ("D", "For real $x_1, \\dots, x_n$ and $y_1, \\dots, y_n$, "
          "$\\left(\\sum_i x_i y_i\\right)^2 \\le \\left(\\sum_i x_i^2\\right)\\left(\\sum_i y_i^2\\right)$.",
     "Ineq.cauchy_schwarz_fin"),
    ("E", "For all real numbers $a, b$, the absolute value satisfies $|a + b| \\le |a| + |b|$.",
     "Ineq.triangle_abs"),
    ("F", "Every natural number $n \\ge 2$ has a prime factor $p \\mid n$.",
     "Num.prime_factor_exists"),
    ("G", "There are infinitely many primes: for every natural number $n$ there is a prime "
          "$p \\ge n$.", "Num.inf_primes"),
    ("H", "Six is a perfect number.", "Num.six_perfect"),
    ("I", "For every $x \\ge 1$, the derivative of $y \\mapsto y^{-1}$ at $x$ is at most one in "
          "absolute value.", "Fn.deriv_inv_bound_aux"),
    ("J", "There is a constant $C$ such that $f(n) \\le C$ for all natural numbers $n$.",
     "Unif.exists_const_forall"),
    ("K", "If $g$ is summable then $g$ has a sum.", "Long.big_a"),
]

QUERIES = [
    "a uniform bound for derivatives of this inverse",
    "Nat.Prime p",
    "x ≥ 1 → |deriv f x| ≤ 1",
    "\\mathbb{N} and \\mathbb{R}, \\varepsilon > 0",
    "perfect",
    "sum of squares ≤",
    "",
]


def large_index(n: int = 40000, seed: int = 126) -> list[dict]:
    """`n` synthetic declarations around the corpus: random statements over a vocabulary of
    names and symbols, the corpus itself among them."""
    rnd = random.Random(seed)
    words = ["bound", "norm", "sum", "map", "image", "fiber", "rank", "basis", "dual", "kernel",
             "cover", "chain", "orbit", "group", "ring", "field", "ideal", "module", "graph",
             "edge", "path", "cycle", "flow", "cut", "measure", "set", "space", "point", "line",
             "curve", "surface", "volume", "angle", "length", "weight", "degree", "order",
             "index", "trace", "det", "mono", "epi", "iso", "lift", "push", "pull", "glue"]
    syms = ["≤", "<", "≠", "∈", "⊆", "∑", "∫", "‖", "^", "∣"]
    types = ["ℕ", "ℝ", "ℤ", "ℚ", "ℂ"]
    out = list(DECLS)
    for k in range(n - len(DECLS)):
        a, b, c = rnd.sample(words, 3)
        ns = rnd.choice(["Alg", "Top", "Comb", "Geo", "Meas", "Lin"])
        name = f"{ns}.{a}_{b}_{c}_{k}"
        t = rnd.choice(types)
        ty = (f"∀ (x : {t}) (y : {t}), {ns}.{a.capitalize()} x → {ns}.{b.capitalize()} y "
              f"{rnd.choice(syms)} {ns}.{c} x y {rnd.choice(syms)} {rnd.randint(0, 9)}")
        out.append(decl(name, ty, f"The {a} of a {b} is a {c}." if rnd.random() < 0.5 else None,
                        uses=[f"{ns}.{a.capitalize()}"]))
    return out
