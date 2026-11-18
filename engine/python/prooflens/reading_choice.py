"""The reading an auditor chooses for a definition the paper leaves open, and the claims whose
interpretation depends on it (#597).

A paper's "bounded" may mean uniformly or eventually bounded. The choice is a requirement of the
definition's claim with the form `reading choice` (`requirements.py`): the readings it chooses
between (`readings`, each with an `id` and its `text`), the one chosen (`chosen`) and why
(`reason`). It may name a Lean declaration stating that two of the readings agree
(`equivalence`: `theorem`, `readings`), which need not exist yet.

A claim depends on a choice only where one of its requirements or findings cites it
(`reading_choices`: `[{claim, choice}]`, the definition's claim and the choice's local id). A
finding rests on each choice it cites, and on those its requirements cite, by a digest of the
readings and the one chosen (`dependencies.py`): when the choice changes, a submitted finding is
due for review, and is never rewritten.

The equivalence is shown with the declaration's exact statement. Its dependence reads `pending`
until the declaration is in the build, a theorem, proved, with only the allowed axioms, then
`discharged`. That is all it does: no verdict moves from one reading to the other, and what it
justifies is what its statement proves.

The choice is a prior interpretation: the read and compare steps of independent review never
show it, and `review author` does. Nothing here changes a status.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

FORM = "reading choice"
DEPENDENCY = "reading choice"
KIND = "reading-equivalence"  # the facts store's kind for an equivalence's check
STATE_WORDS = {"discharged": "discharged by", "pending": "pending"}


class ChoiceError(ValueError):
    pass


def _text(v, what: str) -> str:
    if not isinstance(v, str) or not v.strip():
        raise ChoiceError(f"a reading choice states {what}")
    return v.strip()


def content(out: dict, rec: dict) -> dict:
    """The fields of a `reading choice` requirement, checked: two or more readings with distinct
    ids, the one chosen among them, the reason, and optionally the declaration stating that two
    of them agree."""
    rs = rec.get("readings")
    if not isinstance(rs, list) or len(rs) < 2:
        raise ChoiceError("a reading choice lists two or more readings (`readings`: "
                          "[{id, text}, ...])")
    readings, seen = [], set()
    for r in rs:
        if not isinstance(r, dict):
            raise ChoiceError("each reading is {id, text}")
        rid = _text(r.get("id"), "each reading's id (`id`)")
        if rid in seen:
            raise ChoiceError(f"two readings have the id {rid!r}")
        seen.add(rid)
        readings.append({"id": rid, "text": _text(r.get("text"), f"the text of reading {rid}")})
    chosen = _text(rec.get("chosen"), "the reading it chooses (`chosen`)")
    if chosen not in seen:
        raise ChoiceError(f"{chosen!r} is not one of the readings: {', '.join(sorted(seen))}")
    out.update(readings=readings, chosen=chosen,
               reason=_text(rec.get("reason"), "why that reading is chosen (`reason`)"))
    eq = rec.get("equivalence")
    if eq not in (None, {}):
        if not isinstance(eq, dict) or set(eq) - {"theorem", "readings"}:
            raise ChoiceError("an equivalence is {theorem, readings}: the Lean declaration "
                              "stating that the readings agree, and the two it relates")
        between = eq.get("readings") or []
        if not (isinstance(between, list) and len(between) == 2 and set(between) <= seen
                and between[0] != between[1]):
            raise ChoiceError("an equivalence relates two different readings of the choice "
                              "(`readings`: [id, id])")
        out["equivalence"] = {"theorem": _text(eq.get("theorem"), "the equivalence's Lean "
                                                                  "declaration (`theorem`)"),
                              "readings": list(between)}
    if rec.get("reading_choices") not in (None, []):
        raise ChoiceError("a reading choice cites no other choice")
    return out


def choices(records) -> dict[tuple[str, str], dict]:
    """The reading choices among a workspace's records, by (claim, local id)."""
    return {(r["claim"], r["local_id"]): r for r in records
            if r.get("kind") == "requirement" and r.get("form") == FORM}


def cited(value, records, resolve) -> list[dict]:
    """The choices a requirement or finding cites (`reading_choices`), checked: each one names
    the claim (resolved by `resolve`) and the local id of a reading choice of this workspace."""
    if not isinstance(value, list):
        raise ChoiceError("`reading_choices` lists the choices cited: [{claim, choice}, ...]")
    have, out = choices(records), []
    for c in value:
        if not isinstance(c, dict) or set(c) - {"claim", "choice"}:
            raise ChoiceError("a cited choice is {claim, choice}")
        claim = resolve(c.get("claim"))
        lid = _text(c.get("choice"), "the cited choice's local id (`choice`)")
        if (claim, lid) not in have:
            raise ChoiceError(f"{claim} has no reading choice {lid!r} in this workspace (add it "
                              "first)")
        if {"claim": claim, "choice": lid} not in out:
            out.append({"claim": claim, "choice": lid})
    return out


def digest(rec: dict) -> str:
    """What a finding that cites a choice records of it: its readings and the one chosen. Its
    reason alone changing does not change what the dependent interpretation rests on."""
    body = {"readings": rec.get("readings"), "chosen": rec.get("chosen")}
    return "choice-v1:" + hashlib.sha256(json.dumps(body, sort_keys=True,
                                                    ensure_ascii=False).encode()).hexdigest()


def items(f: dict, records: dict, reqs: list[dict]) -> tuple[list[dict], list[dict]]:
    """The choices finding `f` rests on: those it cites and those its requirements `reqs` cite,
    each with its digest (`dependencies.collect`), and those this workspace no longer has."""
    have = choices(records.values())
    wanted = list(f.get("reading_choices") or [])
    for r in reqs:
        wanted += [c for c in r.get("reading_choices") or [] if c not in wanted]
    out, missing = [], []
    for c in wanted:
        rec = have.get((c.get("claim"), c.get("choice")))
        if rec is None:
            missing.append({"dependency": DEPENDENCY, "claim": c.get("claim"),
                            "why": f"{c.get('claim')} has no reading choice {c.get('choice')} "
                                   "in this workspace"})
            continue
        it = {"dependency": DEPENDENCY, "record": rec["id"], "claim": rec["claim"],
              "choice": rec["local_id"], "sha256": digest(rec)}
        if it not in out:
            out.append(it)
    return out, missing


# -- the equivalence -------------------------------------------------------------------------

def check(root: Path, theorem: str, cached_only: bool = True, lake: str = "lake") -> dict:
    """Lean's record of the declaration `theorem` (the probe's `link` request, with its kind,
    statement, `sorry` and axiom errors), kept in the facts store with its module's environment
    and reused until a module of it changes. `cached_only` answers from the store or with
    `status: "not checked"`."""
    from .config import work_dir_name
    from .deps import _resolve, store
    from .facts import graphs
    from .probe import lib_names
    from .simple import ViewError, _clean, built_modules, probe_modules
    libs = lib_names(root)
    if not libs:
        raise ViewError("no Lean library found in the lakefile")
    built, unbuilt = built_modules(root, libs)
    if not built:
        raise ViewError("the Lean project is not built (run `lake build`)")
    module, answer = _resolve(root, theorem, None, built, unbuilt)
    if answer is not None:
        return {"status": answer["status"], "record": None,
                "reason": f"{theorem}: {answer['status']}"}
    st = store(root, libs)
    key = f"{theorem}\0{module or '*'}"
    entry, _ = st.get(KIND, key)
    if entry is not None:
        return entry["body"]
    if cached_only:
        return {"status": "not checked", "record": None,
                "reason": "Lean has not checked it since the Lean last changed; `machinechecked "
                          "check` checks it"}
    with st.lock(None):
        entry, _ = st.get(KIND, key)
        if entry is not None:
            return entry["body"]
        mods = [module] if module else built
        recs, failed = probe_modules(root, mods, libs, [{"kind": "link", "name": theorem},
                                                        {"kind": "modules", "name": ""}],
                                     lake, log=lambda m: None,
                                     work=root / work_dir_name(root) / "build")
        found = [r for r in recs if r.get("record") == "link" and r.get("name") == theorem
                 and "missing" not in (r.get("errors") or [])]
        if len({r.get("probe_group") for r in found}) > 1:
            return {"status": "ambiguous", "record": None,
                    "reason": f"several libraries declare {theorem}"}
        if any(str(e).startswith("probe-error") for r in recs for e in r.get("errors") or []):
            return {"status": "not checked", "record": None,
                    "reason": "the probe failed on this request; ask again"}
        if not found and failed:
            return {"status": "not checked", "record": None,
                    "reason": "some built modules could not be loaded: "
                              + ", ".join(sorted(failed)[:3])}
        rec = found[0] if found else None
        body = {"status": "checked" if rec else "not found",
                "record": _clean(rec) if rec else None,
                **({} if rec else {"reason": f"{theorem} is not in the Lean project"})}
        graph: dict[str, list[str]] = {}
        for gr in graphs(recs).values():
            graph.update(gr)
        st.put(KIND, key, st.environment([rec["module"]] if rec and rec.get("module")
                                         else mods, graph), body=body)
    return body


def statement_text(rec: dict | None) -> str | None:
    """The declaration's statement as Lean prints it, from its probe record."""
    st = (rec or {}).get("statement") or {}
    for k in ("text", "exact"):
        v = st.get(k)
        if isinstance(v, dict):
            v = v.get("text")
        if isinstance(v, str) and v:
            return v
    return None


def equivalence(eq: dict, root, check_now: bool = False) -> dict:
    """An equivalence's state: `discharged` when Lean's record of its declaration is a theorem,
    with no `sorry` and only the allowed axioms; `pending` otherwise (not in the build yet, not
    proved, another axiom, or not checked), with `reason`; and the declaration's exact statement
    when Lean gave it. A discharged equivalence moves no verdict between the readings."""
    out = {"theorem": eq["theorem"], "readings": list(eq.get("readings") or [])}
    if root is None:
        return {**out, "state": "pending", "statement": None,
                "reason": "no Lean project to check it against"}
    from .simple import ViewError
    try:
        body = check(Path(root), eq["theorem"], cached_only=not check_now)
    except ViewError as e:
        body = {"status": "not checked", "record": None, "reason": str(e)}
    rec = body.get("record")
    out["statement"] = statement_text(rec)
    if body.get("status") != "checked" or rec is None:
        return {**out, "state": "pending", "reason": body.get("reason") or body.get("status")}
    if rec.get("kind") != "theorem":
        return {**out, "state": "pending", "reason": f"{eq['theorem']} is not a theorem"}
    if rec.get("sorry"):
        return {**out, "state": "pending", "reason": f"the proof of {eq['theorem']} uses sorry"}
    if rec.get("errors"):
        return {**out, "state": "pending",
                "reason": f"{eq['theorem']} fails a check: " + ", ".join(map(str, rec["errors"]))}
    return {**out, "state": "discharged", "reason": None}


# -- views -----------------------------------------------------------------------------------

def dependents(records, key: tuple[str, str]) -> list[dict]:
    """The requirements and findings that cite the choice `key` (claim, local id), each once."""
    want = {"claim": key[0], "choice": key[1]}
    return [{"claim": r["claim"], "record": r["id"], "kind": r["kind"],
             **({"requirement": r["local_id"]} if r.get("kind") == "requirement" else {})}
            for r in sorted(records, key=lambda r: (r.get("created_at") or "", r["id"]))
            if r.get("kind") in ("requirement", "finding")
            and want in (r.get("reading_choices") or [])]


def view(rec: dict, records, root=None, check_now: bool = False) -> dict:
    """A reading choice as the informed views show it: its readings, the one chosen and why,
    the requirements and findings that cite it, and its equivalence's state."""
    out = {"claim": rec["claim"], "choice": rec["local_id"], "record": rec["id"],
           "text": rec.get("text"), "readings": rec.get("readings") or [],
           "chosen": rec.get("chosen"), "reason": rec.get("reason"),
           "dependents": dependents(records, (rec["claim"], rec["local_id"])),
           "by": rec.get("created_by")}
    if rec.get("equivalence"):
        out["equivalence"] = equivalence(rec["equivalence"], root, check_now)
    return out


def views(records, root=None, check_now: bool = False) -> list[dict]:
    """Every reading choice of a workspace's records (`view`)."""
    records = list(records)
    return [view(r, records, root, check_now)
            for _, r in sorted(choices(records).items())]


def chosen_text(v: dict) -> str:
    return next((r["text"] for r in v.get("readings") or [] if r["id"] == v.get("chosen")),
                v.get("chosen") or "")


def equivalence_line(eq: dict) -> str:
    """An equivalence in words: pending or discharged, with its declaration and statement."""
    a, b = (eq.get("readings") or ["?", "?"])[:2]
    head = (f"discharged by {eq['theorem']}" if eq["state"] == "discharged"
            else f"pending {eq['theorem']}" + (f" ({eq['reason']})" if eq.get("reason") else ""))
    return (f"equivalence of readings {a} and {b}: {head}"
            + (f"; it states: {eq['statement']}" if eq.get("statement") else "")
            + ". No verdict moves between the readings: what it justifies is what it states.")


def lines(v: dict, pad: str = "  ") -> list[str]:
    """A reading choice for the terminal."""
    out = [f"{pad}reading choice {v['choice']} of {v['claim']}"
           + (f" ({v['text']})" if v.get("text") else "")
           + f": {v['chosen']}, {chosen_text(v)}. Reason: {v.get('reason')}"]
    for r in v.get("readings") or []:
        if r["id"] != v.get("chosen"):
            out.append(f"{pad}  not chosen: {r['id']}, {r['text']}")
    if v.get("equivalence"):
        out.append(f"{pad}  {equivalence_line(v['equivalence'])}")
    for d in v.get("dependents") or []:
        out.append(f"{pad}  depended on by {d['claim']}, "
                   + (f"requirement {d['requirement']}" if d.get("requirement")
                      else f"{d['kind']} {d['record']}"))
    return out


def cite_line(c: dict, v: dict | None) -> str:
    """A requirement's or finding's dependence on a choice, in words."""
    if v is None:
        return f"depends on reading choice {c['choice']} of {c['claim']}, not in this workspace"
    eq = v.get("equivalence")
    return (f"depends on the reading of {c['claim']} chosen in {c['choice']}: {v['chosen']}, "
            f"{chosen_text(v)}"
            + (f"; {STATE_WORDS[eq['state']]} {eq['theorem']}" if eq else ""))
