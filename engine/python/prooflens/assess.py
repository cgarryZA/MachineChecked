"""From evidence to statuses, findings and gates.

Every status shown by any ProofLens view is computed here, from the probe records, the TeX
anchors, the review markers and the inventory; the views only display it.

Findings come in three tiers:

* `violation`: a mechanical fact that contradicts acceptance (a disallowed axiom, a proof whose
  type is not the proposition, a stale source hash, a claim of the paper missing from the
  inventory). A violation fails the consistency check; it does not change a status, which
  records what is proved: a proof that fails its check is not a proof, so its clause is open.
* `warning`: a pattern that may change the meaning of a statement (a totalised operation, for
  instance). It asks for investigation, may be wrong, and can be dismissed with a recorded
  rationale tied to the subject's fingerprint.
* `obligation`: a judgement only a reviewer can make (a review of a proposition or definition, a
  witness that the hypotheses can be met, a regime the paper intends to cover).

Two gates per paper: the consistency check (no violation) and the release gate (sources checked, consistency clean, every scope decision reviewed, every formal
claim accepted and every definition claim reviewed, no printed clause refuted, every witness
valid, and a Comparator replay of every proof).
"""

from __future__ import annotations

from .status import fields

from .reviews import Review, history

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
}


# Totalised operations so common in analysis that a warning about them is rarely informative.
LOW_SIGNAL = {"HDiv.hDiv", "Inv.inv"}


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


class Assessor:
    def __init__(self, cfg, inventory, lean, tex, reviews: list[Review], dismissals,
                 comparator_log: str | None = None, project_commit: str | None = None):
        self.cfg, self.inv, self.lean, self.tex = cfg, inventory, lean, tex
        self.reviews, self.dismissals = reviews, dismissals
        self.comparator = parse_comparator(comparator_log)
        self.project_commit = project_commit
        self.findings: list[dict] = []
        self.authors = set(cfg.statement_authors)

    # -- reviews --------------------------------------------------------------------------

    def review_state(self, target: str, name: str, rec: dict | None) -> dict:
        """The state of the last review of `name`: `reviewed` (current, by a reviewer other than
        the authors of the statements), `author-reviewed`, `stale` (the declaration changed since)
        or `pending` (none)."""
        hist = history(self.reviews, target, name)
        last = hist[-1] if hist else None
        if last is None:
            state = "pending"
        elif rec is None or last.hash not in _hashes(rec):
            state = "stale"
        elif last.by in self.authors:
            state = "author-reviewed"
        else:
            state = "reviewed"
        return {"state": state, "current": [last.to_json()] if state in (
                    "reviewed", "author-reviewed") else [],
                "stale": [r.to_json() for r in hist if r is not last or state == "stale"]}

    def closure_reviews(self, names: list[str]) -> dict:
        """The review state of every project declaration in the closures of `names`, other than
        the propositions of the inventory (each reviewed by its own spec-review)."""
        lean = self.lean
        out = {}
        for n in names:
            clos = lean["specs"][n]["closure"] if n in lean["specs"] else \
                lean["defs"].get(n, {}).get("closure", [])
            for d in clos:
                if d in lean["specs"] or d in out:
                    continue
                out[d] = self.review_state("def", d, lean["decls"].get(d))
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
        return {"state": "pass", "detail": "Comparator replayed the proof in a fresh kernel ("
                + ", ".join(rec.get("kernels", ["lean"])) + ")" + since}

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
                self.findings.append(_finding("violation", "spec-" + e.split("=")[0], subj,
                                              f"proposition {spec}: {e}"))
            sr = self.review_state("spec", spec, srec)
            dr = self.closure_reviews([spec]) if srec else {}
            res["spec_review"] = sr
            if sr["state"] in ("pending", "stale"):
                self.findings.append(_finding(
                    "obligation", "spec-review", subj,
                    f"the proposition {spec} has no current review" +
                    (" (its last review is stale)" if sr["state"] == "stale" else "")))
            states = [sr["state"]] + [d["state"] for d in dr.values()]
        else:
            srec = None
            names = list(cl.get("defs", []))
            missing = [d for d in names if d not in lean["decls"]]
            for d in missing:
                self.findings.append(_finding("violation", "def-missing", subj,
                                              f"definition {d} is not in the environment"))
            dr = {d: self.review_state("def", d, lean["decls"].get(d)) for d in names}
            dr.update({d: r for d, r in self.closure_reviews(names).items() if d not in dr})
            res["spec_review"] = None
            states = [d["state"] for d in dr.values()]
        res["def_reviews"] = dr
        for n, d in dr.items():
            if d["state"] in ("pending", "stale"):
                self.findings.append(_finding(
                    "obligation", "def-review", subj,
                    f"the definition {n} has no current review" +
                    (" (its last review is stale)" if d["state"] == "stale" else ""), trigger=n))
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
                                              f"{thm}: {e}"))
        res["state"] = ("proved" if res.get("accept_ok") else
                        "refuted" if res.get("refute_ok") else
                        "open" if spec else
                        "stated" if cl.get("defs") else "unspecified")

        if srec:
            roles = [b["role"] for b in srec.get("binders", [])]
            # A checked refutation needs no witness: a proof of ¬S exhibits an instance meeting
            # S's hypotheses (were they never met, S would hold vacuously and not be refutable).
            if ("hypothesis" in roles or "instance" in roles) and not cl.get("witness") \
                    and not res.get("refute_ok"):
                self.findings.append(_finding(
                    "obligation", "witness", subj,
                    f"{spec} has hypotheses but no witness that they can be met"))
            for c in srec.get("consts", []):
                if c in TOTALISED:
                    self.add_warning("totalised", subj, spec, srec,
                                     f"{TOTALISED[c]} ({c} occurs in {spec})", c)
        regs = []
        for r in cl.get("regimes", []):
            w = r.get("witness")
            p = self._proof("witness", w, None) if w else None
            ok = bool(p) and not p.get("errors")
            regs.append({**r, "discharged": ok, "type": (p or {}).get("type")})
            if not ok:
                self.findings.append(_finding(
                    "obligation", "regime", subj,
                    f"regime not shown to be covered: {r.get('name', '')}",
                    trigger=r.get("name", "")))
        res["regimes"] = regs
        return res

    def add_warning(self, code, subj, name, rec, message, trigger):
        fp = rec.get("fingerprint")
        f = _finding("warning", code, subj, message, trigger=trigger, fingerprint=fp,
                     signal="low" if trigger in LOW_SIGNAL else "normal")
        for d in self.dismissals:
            if d.get("code") == code and d.get("subject") == name and d.get("trigger") == trigger:
                if d.get("fingerprint") == fp:
                    f["dismissed"] = {"rationale": d.get("rationale", ""), "by": d.get("by", "")}
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
                elif srs == "stale":
                    add("the proposition changed after its last review", c)
            for d, r in (c.get("def_reviews") or {}).items():
                defs[d] = r["state"]
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
                             ("author-reviewed", "were reviewed only by the author")):
            if counts.get(state):
                out.append(f"{counts[state]} definition{'s' if counts[state] > 1 else ''} its "
                           f"meaning depends on {words}")
        if claim["scope"] == "definition" and self.claim_code(claim, clauses) != "definition.reviewed" and not out:
            out.append("its definitions are not independently reviewed")
        return list(dict.fromkeys(out))

    def run(self) -> dict:
        claims = []
        for c in self.inv["claims"]:
            clauses = [self.clause(c, cl, k) for k, cl in enumerate(c.get("clauses", []))]
            state = fields(self.claim_code(c, clauses))
            claims.append({"id": c["id"], **state, "clauses": clauses,
                           "blockers": self.blockers(c, clauses)})
        self.inventory_checks()
        if self.lean:
            for v in self.lean.get("layering", []):
                self.findings.append(_finding(
                    "violation", "layering", v["module"],
                    f"the specification module {v['module']} imports {v['imports']}"))
        gates = self.gates(claims)
        return {"claims": claims, "findings": self.findings, "gates": gates}

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
                        **({"source_note": "the source is a PDF: its hash is pinned and checked, "
                            "and claim positions are approximate"} if source == "pdf" else {}),
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
        """Compare the inventory with the environments the compiled papers contain."""
        for pid, t in (self.tex or {}).items():
            if t.get("mode") != "latex":
                continue
            anchors = t["anchors"]
            matched = set()
            for c in [c for c in self.inv["claims"] if c["paper"] == pid]:
                line = line_location(c)
                if line is not None:
                    # A claim recorded by file and line (an equation, a part, a prose claim): its
                    # hash is the hash of that source line, as in `acceptance.py`.
                    got = (t.get("lines") or {}).get(c["location"])
                    if c.get("source_sha256") and got != c["source_sha256"]:
                        self.findings.append(_finding(
                            "violation", "source-changed", c["id"],
                            f"the source line {c['location']} of {c.get('number', c['id'])} "
                            + ("is missing" if got is None else
                               "differs from the frozen inventory")))
                    continue
                a = match_anchor(c, anchors)
                if a is None:
                    if c.get("kind") in t.get("envs", []):
                        self.findings.append(_finding(
                            "violation", "inventory-unanchored", c["id"],
                            f"{c.get('number', c['id'])} is not found in the compiled paper"))
                    continue
                matched.add(a["id"])
                if c.get("source_sha256") and a.get("source_sha256") and \
                        c["source_sha256"] != a["source_sha256"]:
                    self.findings.append(_finding(
                        "violation", "source-changed", c["id"],
                        f"the source of {c.get('number', c['id'])} differs from the frozen "
                        f"inventory"))
            for a in anchors:
                if a["id"] not in matched:
                    self.findings.append(_finding(
                        "violation", "inventory-gap", f"{pid}:{a.get('label') or a['env']}",
                        f"{a['env'].capitalize()} {a.get('number')} ({a['file']}:{a['line']}) "
                        f"is in the paper but not in the inventory"))


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
