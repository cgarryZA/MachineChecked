"""Synthetic contradictory assurance states, serialized by the engine for browser tests."""
import sys
from pathlib import Path

from prooflens.assess import Assessor
from prooflens.manifest import build
from prooflens.paper import apply_audits, write_paper_site
from prooflens.pipeline import write_preview
from prooflens.status import fields

root, reader = map(Path, sys.argv[1:])
CASES = [
    ("pending", "pending", "not-run", "latex"),
    ("author", "author-reviewed", "not-run", "latex"),
    ("accepted", "reviewed", "not-run", "latex"),
    ("replayed", "pending", "pass", "latex"),
    ("stale-replay", "reviewed", "unverified", "latex"),
    ("pdf", "reviewed", "pass", "pdf"),
    ("source-mismatch", "reviewed", "pass", "latex"),
]
claims, assessed, tex, papers = [], [], {}, {}
for i, (name, review, replay, mode) in enumerate(CASES, 1):
    cid = f"{name}:claim"
    claim = {"id": cid, "paper": name, "scope": "formal", "kind": "theorem",
             "number": f"Theorem {i}", "source_sha256": "a", "clauses": []}
    cl = {"name": "main", "state": "proved", "spec": "Synthetic.Spec", "accept_ok": True,
          "review": review, "checks": {"spec": {"ok": True},
          "accept": {"ok": True, "errors": [], "sorry": False, "axioms": []},
          "replay": {"state": replay}}}
    claims.append(claim)
    assessed.append({"id": cid, **fields(Assessor.claim_code(claim, [cl])), "clauses": [cl]})
    tex[name] = {"mode": mode, "pdf_pinned": "a", "pdf_sha256": "a", "anchors": [
        {"label": cid, "begin": [1, 0, 100], "end": [1, 0, 150],
         "source_sha256": "b" if name == "source-mismatch" else "a"}]}
    papers[name] = {"mode": mode, "title": name}
evidence = {"id": "a" * 64, "created": "2026-01-01", "body": {
    "inventory": {"claims": claims}, "lean": {}, "tex": tex,
    "assessment": {"claims": assessed, "findings": []},
    "provenance": {"project": {}, "tool": {}, "papers": papers}}}
index, chunks, store = build(evidence, "states")
# Labels and colours from an older producer cannot override the structured facts.
for c in [*index["claims"], *chunks.values()]:
    c["status"], c["class"] = "deliberately misleading display copy", "malformed"
write_preview(root / "states", index, chunks, store, {}, reader)

public = [{"key": c["id"], "number": c["number"], "kind": "theorem", "anchor": None,
           "links": [{"name": "Synthetic.theorem", "repository": "a/project"}]} for c in claims]
public.append({"key": "unlisted", "number": "Theorem 8", "kind": "theorem", "anchor": None,
               "links": [{"name": "Synthetic.unlisted", "repository": "b/project"}]})
apply_audits(public, {"a/project": {"author": "Synthetic reviewer", "url": "https://example.org/audit/",
    "claims": [{**a, "number": c["number"]} for c, a in zip(claims, assessed)]}})
write_paper_site(root / "states-public", {"title": "Synthetic assurance cases", "formalisations": [
    {"repository": "a/project"}, {"repository": "b/project"}]}, public, None, None, reader)
