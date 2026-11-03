"""What a change to the notation macros would reopen (`machinechecked inventory notation`).

A reading of a passage that uses a notation macro the configuration lists (`notation_macros`)
records the digest of the macro's definitions with the passage's pin
(`review_sources.reading_digest`). Listing a macro therefore changes the digest a reading of
every passage that uses it must record: each review marker that recorded the passage's pin alone
no longer counts, although neither the passage nor the definition changed. Removing a listed
macro reopens, the same way, the readings that recorded its definitions.

The plan reads the latest release's evidence and the paper as the configuration gives it, and
reports, for a proposed list, the passages whose reading digest changes, the review markers that
would no longer count (and any that would count again), and the claims whose status would
change. It writes nothing and records no reading: a reopened review is renewed by a new reading
of the passage with its notation (`review promote`)."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from .assess import Assessor
from .review_sources import reading_digest
from .source_regions import RegionError, collect, macro_name

CURRENT = ("reviewed", "author-reviewed")


class _Recording(Assessor):
    """An assessment that keeps each review state it computes, by declaration and claim."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.recorded: dict[tuple, dict] = {}

    def review_state(self, target, name, rec, claim=None):
        out = super().review_state(target, name, rec, claim)
        self.recorded[(target, name, claim)] = out
        return out


def lists(cfg, papers: list[str], add: list[str], remove: list[str]) -> dict[str, tuple]:
    """The notation macros of each paper in `papers`, now and with `add` listed and `remove`
    left out, as control sequences."""
    add, remove = [macro_name(n) for n in add], [macro_name(n) for n in remove]
    out = {}
    for pid in papers:
        now = list(cfg.paper(pid).notation_macros)
        out[pid] = (now, [m for m in dict.fromkeys(now + add) if m not in remove])
    for m in remove:
        if not any(m in now for now, _ in out.values()):
            raise RegionError(f"{m} is not a notation macro of "
                              + ", ".join(f"paper {p}" for p in papers))
    return out


def plan(cfg, inventory: dict, body: dict, reviews, dismissals, comparator: str | None,
         snapshots: dict[str, Path], macros: dict[str, tuple]) -> dict:
    """The effect of the notation lists `macros` (paper to the lists now and proposed) on the
    evidence `body` (the latest release's), with the current `reviews` and `dismissals`;
    `snapshots` holds each paper's manuscript. Raises RegionError when the release's source
    evidence was not made with the present list and manuscript, whose effect it would then
    mix in."""
    tex = body["tex"]
    now_tex, new_tex = deepcopy(tex), deepcopy(tex)
    passages = []
    for pid, (now, new) in macros.items():
        stored = (tex.get(pid) or {}).get("regions")
        if stored is None:
            raise RegionError(f"paper {pid}: the latest release holds no source evidence of its "
                              "LaTeX passages")
        a = collect(inventory, pid, snapshots[pid], now)
        b = collect(inventory, pid, snapshots[pid], new)
        for c in inventory["claims"]:
            if c.get("paper") != pid or not c.get("source_sha256") or c["id"] not in stored:
                continue
            if reading_digest(c, stored[c["id"]]) != reading_digest(c, a.get(c["id"])):
                raise RegionError(
                    f"{c['id']}: the latest release read its passage or its notation otherwise "
                    "than the paper and the configuration give it now; run `machinechecked "
                    "build` first")
            if reading_digest(c, a.get(c["id"])) != reading_digest(c, b.get(c["id"])):
                passages.append({"claim": c["id"], "notation": {
                    "now": [m["macro"] for m in (a.get(c["id"]) or {}).get("notation") or []],
                    "proposed": [m["macro"] for m in
                                 (b.get(c["id"]) or {}).get("notation") or []]}})
        now_tex[pid]["regions"], new_tex[pid]["regions"] = a, b
    commit = body["provenance"]["project"].get("commit")
    before = _Recording(cfg, inventory, body["lean"], now_tex, reviews, dismissals, comparator,
                        commit)
    after = _Recording(cfg, inventory, body["lean"], new_tex, reviews, dismissals, comparator,
                       commit)
    was, will = before.run(), after.run()
    return {"passages": passages,
            "reopened": _markers(before.recorded, after.recorded),
            "restored": _markers(after.recorded, before.recorded),
            "statuses": [{"claim": x["id"], "now": x["status"], "proposed": y["status"]}
                         for x, y in zip(was["claims"], will["claims"])
                         if x["status_code"] != y["status_code"]]}


def _markers(counted: dict, then: dict) -> list[dict]:
    """The markers a review state rests on in `counted` whose review is not current in `then`,
    each with those reviews and why each is not current there."""
    out: dict[tuple, dict] = {}
    for key, r in sorted(counted.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        other = then.get(key) or {}
        if r["state"] not in CURRENT or other.get("state") in CURRENT or not r.get("rests_on"):
            continue
        m = r["rests_on"]
        entry = out.setdefault((m["file"], m["line"]), {
            "file": m["file"], "line": m["line"], "by": m["by"], "target": key[0],
            "name": key[1], "reviews": []})
        review = {"claim": key[2], "passages": m["passages"],
                  "state": other.get("state", "pending")}
        for k in ("why", "source_claim"):
            if other.get(k):
                review[k] = other[k]
        if review not in entry["reviews"]:
            entry["reviews"].append(review)
    return list(out.values())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Report, before the configuration changes, what a change to the notation "
                    "macros (notation_macros) would reopen: the passages whose reading digest "
                    "changes, the review markers that would no longer count, and the claims "
                    "whose status would change. Reads the latest release; writes nothing.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--paper", action="append",
                        help="the paper (repeat; default: every paper of the latest release "
                        "read from its LaTeX source)")
    parser.add_argument("--add", action="append", default=[], metavar="NAME",
                        help="a macro to list, as R or \\R (repeat)")
    parser.add_argument("--remove", action="append", default=[], metavar="NAME",
                        help="a listed macro to leave out (repeat)")
    args = parser.parse_args(argv)
    from . import evidence as ev
    from .config import load
    from .pipeline import inventory_changed
    from .reviews import load_reviews, load_dismissals
    from .sources import acquire
    try:
        if not args.add and not args.remove:
            raise RegionError("give the macros to list (--add) or to leave out (--remove)")
        cfg = load(args.config)
        last = ev.latest(cfg.out_dir)
        if last is None:
            raise RegionError("there is no release to read: run `machinechecked build` first")
        body = ev.load(cfg.out_dir, last["evidence"])["body"]
        why = inventory_changed(cfg, body)
        if why:
            raise RegionError(why)
        papers = args.paper or [p.id for p in cfg.papers
                                if (body["tex"].get(p.id) or {}).get("regions") is not None]
        if not papers:
            raise RegionError("the latest release read no paper from its LaTeX source")
        macros = lists(cfg, papers, args.add, args.remove)
        inventory = json.loads(cfg.inventory.read_text(encoding="utf-8"))
        reviews, _ = load_reviews(cfg.reviews, cfg.ai_reviewers, cfg.root)
        dismissals = load_dismissals(cfg.dismissals)
        comp = cfg.comparator_log
        comparator = comp.read_text(errors="replace") if comp and comp.exists() else None
        with tempfile.TemporaryDirectory(prefix="machinechecked-notation-") as temp:
            snapshots = {pid: acquire(cfg, cfg.paper(pid), Path(temp) / pid).dir
                         for pid in macros}
            result = plan(cfg, inventory, body, reviews, dismissals, comparator, snapshots,
                          macros)
        print(json.dumps({
            "release": last["release"], "evidence": last["evidence"],
            "notation_macros": {pid: {"now": now, "proposed": new}
                                for pid, (now, new) in macros.items()},
            **result,
            "counts": {k: len(result[k]) for k in ("passages", "reopened", "restored",
                                                   "statuses")}},
            indent=2, ensure_ascii=False))
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        parser.exit(2, f"notation: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
