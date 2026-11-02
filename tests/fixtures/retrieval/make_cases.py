"""Write cases.json: the corpus's exported retrieval index (`retrieval.Retrieval.export`) and,
for each query and each declaration searched from, what the engine's search returns, and the
parts (`lean_shape`) of each statement. The reader's search
(web/src/lib/retrieval.js) must return the same (web/tests/retrieval.test.mjs);
tests/contracts/test_retrieval.py checks that this file is current.

    PYTHONPATH=engine/python python3 tests/fixtures/retrieval/make_cases.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import CLAIMS, DECLS, LIKE, QUERIES, SHAPES  # noqa: E402
from prooflens.retrieval import (Retrieval, lean_shape, normal_parts,  # noqa: E402
                                 paper_quantifiers, terms)

KINDS = {"theorem": lambda k: k == "theorem", "definition": lambda k: k != "theorem", None: None}


def project(r: dict) -> dict:
    """What both implementations must agree on in a result (its statement is the index's)."""
    return {k: r[k] for k in ("name", "kind", "score", "content", "reasons")}


def cases() -> dict:
    ret = Retrieval.build(DECLS)
    out = []
    for key, text, _ in CLAIMS:
        out.append({"query": text, "kinds": "theorem", "paper": True, "limit": 5})
    for q in QUERIES:
        out.append({"query": q, "kinds": None, "paper": False, "limit": 8})
    out.append({"query": QUERIES[0], "kinds": None, "paper": False, "limit": 2,
                "after": "Fn.deriv_inv_bound_aux"})
    for c in out:
        order = paper_quantifiers(c["query"]) if c["paper"] else None
        c["paper_order"] = order
        c["terms"] = terms(c["query"])
        res = ret.search(c["query"], kinds=KINDS[c["kinds"]], limit=c["limit"],
                         after=c.get("after"), paper_order=order)
        c["expect"] = {**res, "results": [project(r) for r in res["results"]]}
    like = []
    for name in LIKE:
        res = ret.search_like(name, limit=5)
        like.append({"name": name, "limit": 5,
                     "expect": {**res, "results": [project(r) for r in res["results"]]}})
    shapes = [{"type": t, "shape": lean_shape(t),
               "parts": [normal_parts(lean_shape(t), typed) for typed in (True, False)]}
              for t in SHAPES + [d["type"] for d in DECLS]]
    return {"index": ret.export(), "cases": out, "like": like, "shapes": shapes}


if __name__ == "__main__":
    (HERE / "cases.json").write_text(json.dumps(cases(), ensure_ascii=False, indent=None,
                                                sort_keys=True) + "\n", encoding="utf-8")
