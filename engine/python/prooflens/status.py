"""Stable status codes and their shared presentation vocabulary.

Assessment selects a code. Labels and coarse colours are presentation only.
"""
from importlib.resources import files
import json

CATALOG = json.loads(files("prooflens").joinpath("data/statuses.json").read_text())
STATUSES = CATALOG["statuses"]


def fields(code: str, detail: str | None = None) -> dict:
    """The canonical status fields for an assessed claim or link."""
    row = STATUSES[code]
    return {"status_code": code, "status": row["label"], "class": row["class"],
            **({"status_detail": detail} if detail else {})}


def source_evidence(anchor, mode, matches=None, paper=None) -> dict:
    """Source identity and placement are independent of proof and correspondence review."""
    paper = paper or {}
    placement = (anchor or {}).get("kind", "unlocated")
    state = "fail" if matches is False else "pass" if matches is True else "none"
    if mode == "pdf":
        state = "pdf-only"
    elif placement == "ambiguous" and state != "fail":
        state = "open"
    result = {"state": state, "placement": placement}
    if mode == "pdf":
        pinned, actual = paper.get("pdf_pinned"), paper.get("pdf_sha256")
        result["pdf_integrity"] = ("unpinned" if not pinned else "unknown" if not actual
                                   else "matched" if pinned == actual else "mismatch")
    return result
