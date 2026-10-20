import Uses.Main

namespace Uses

/-- The general result the paper states: every good positive number exceeds its half, and four
exceeds two. -/
theorem main_bound (n : Nat) (h : Good n) (hpos : 0 < n) : n / 2 < n ∧ 4 / 2 < 4 :=
  ⟨half_lt n h hpos, half_lt_four⟩

end Uses
