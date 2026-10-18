"""Machine-readable result codes with display labels and coarse colour classes.

Select a code from evidence, never from a sentence. Labels are presentation; changing one
must not change which claims a filter, check or review workflow includes.
"""

OUT_OF_SCOPE = {"expository", "literature", "empirical", "proof-step", "part-of", "duplicate"}

LABELS = {
    "formal.accepted": ("formal: accepted", "accepted"),
    "formal.author-reviewed": ("formal: proved, author-reviewed", "proved"),
    "formal.review-pending": ("formal: proved, review pending", "proved"),
    "formal.open": ("formal: open", "open"),
    "formal.unspecified": ("formal: unspecified", "unspecified"),
    "formal.malformed": ("formal: malformed", "malformed"),
    "formal.unchecked": ("formal: unchecked", "unspecified"),
    "definition.unchecked": ("definition: unchecked", "unspecified"),
    "definition.unstated": ("definition: not yet stated", "unspecified"),
    "definition.pending": ("definition: review pending", "open"),
    "definition.reviewed": ("definition: reviewed", "accepted"),
    "definition.author-reviewed": ("definition: author-reviewed", "proved"),
    "link.missing": ("linked: Lean declaration not found", "malformed"),
    "link.failed": ("linked: Lean could not inspect the declaration", "unspecified"),
    "link.definition": ("linked: Lean definition", "proved"),
    "link.incomplete": ("linked: Lean proof incomplete (sorry)", "open"),
    "link.axioms": ("linked: Lean proof uses further axioms", "open"),
    "link.checked": ("linked: Lean proof checked", "proved"),
    "link.unbuilt": ("linked: Lean not checked (the project is not built)", "unspecified"),
    "link.module-unbuilt": ("linked: Lean not checked (its module {module} is not built)", "unspecified"),
    "link.module-failed": ("linked: Lean not checked (its module {module} could not be loaded)", "unspecified"),
    "link.ambiguous": ("linked: Lean name is ambiguous (declared in {modules})", "unspecified"),
    "link.no-audit": ("linked: Lean not checked here (no audit published)", "declared"),
    "link.not-in-audit": ("linked: Lean not checked here (the published audit does not list it)", "declared"),
    "link.suggested": ("suggested link, not confirmed", "unspecified"),
    "link.none": ("not linked", "unspecified"),
}
for scope in OUT_OF_SCOPE:
    LABELS[f"scope.{scope}"] = (f"out of scope: {scope}", "out-of-scope")
for corrected in (False, True):
    for partial in (False, True):
        code = "formal.refuted" + (".corrected" if corrected else "") + (".partial" if partial else "")
        label = ("refuted as printed" + ("; corrected statement proved" if corrected else "")
                 + ("; other clauses open" if partial else ""))
        LABELS[code] = (label, "refuted")


def result(code: str, **context) -> dict:
    label, colour = LABELS[code]
    return {"status_code": code, "status": label.format(**context), "class": colour}


def claim_code(claim: dict, clauses: list[dict]) -> str:
    """The existing assessment policy expressed as a code, independent of its wording."""
    scope = claim["scope"]
    if scope in OUT_OF_SCOPE:
        return f"scope.{scope}"
    if any(c["state"] == "unchecked" for c in clauses):
        return "definition.unchecked" if scope == "definition" else "formal.unchecked"
    if scope == "definition":
        if not clauses:
            return "definition.unstated"
        if not all(c["review"] in ("reviewed", "author-reviewed") for c in clauses):
            return "definition.pending"
        return ("definition.author-reviewed" if any(c["review"] == "author-reviewed" for c in clauses)
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
        return "formal.refuted" + (".corrected" if fixed else "") + (".partial" if not rest_proved else "")
    if rest_proved:
        if not all(c["review"] in ("reviewed", "author-reviewed") for c in rest):
            return "formal.review-pending"
        return ("formal.author-reviewed" if any(c["review"] == "author-reviewed" for c in rest)
                else "formal.accepted")
    return "formal.open"
