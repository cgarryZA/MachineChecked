"""Write cases.json: the corpus's exported retrieval index (`retrieval.Retrieval.export`) and,
for each query, what the engine's search returns. The reader's search
(web/src/lib/retrieval.js) must return the same (web/tests/retrieval.test.mjs);
tests/contracts/test_retrieval.py checks that this file is current.

    PYTHONPATH=engine/python python3 tests/fixtures/retrieval/make_cases.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from corpus import CLAIMS, DECLS, QUERIES  # noqa: E402
from prooflens.retrieval import Retrieval, paper_quantifiers, terms  # noqa: E402

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
    return {"index": ret.export(), "cases": out}


if __name__ == "__main__":
    (HERE / "cases.json").write_text(json.dumps(cases(), ensure_ascii=False, indent=None,
                                                sort_keys=True) + "\n", encoding="utf-8")
