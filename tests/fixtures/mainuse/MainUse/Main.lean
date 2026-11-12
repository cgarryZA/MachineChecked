import MainUse.Basic

namespace MainUse

/-- The paper's theorem, proved with the variant. -/
theorem main_result (n : Nat) (h : n ≤ 4) : 2 * n ≤ 10 := bound_variant n (by omega)

end MainUse
