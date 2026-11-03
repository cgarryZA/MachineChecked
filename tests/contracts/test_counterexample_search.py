"""A bounded search proposes counterexample families for a supported reduced obligation (#539,
part of #111; the owner's decision D2 on #498 puts it in scope as a proposer).

The search reads a requirement's reduced obligation (`reduced`) against its reading's order of
quantifiers, domains and constants, tries endpoints and limits and then families in the constants
chosen before each variable, and checks each with exact rational arithmetic. A proposal is a
candidate only: nothing records it, it never says that an estimate holds, and no status changes.
The command-line tests run on the structure fixture's built data (no Lean).
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from prooflens import cli
from prooflens import estimates as est
from prooflens import requirements as rq
from prooflens import review_cli as rc
from prooflens import workspace as wsp
from prooflens.targets import Snapshot

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "web" / "tests" / "fixtures" / "structure" / "data"
PAPER = ROOT / "tests" / "fixtures" / "structure" / "paper" / "main.tex"
WHO = rc.parse_reviewer("human:A-Auditor")
CLAIM = "P:thm:bound-once"


def req(lid, form, text, **more):
    return {"id": f"r-{lid}", "kind": "requirement", "claim": "X", "local_id": lid, "form": form,
            "text": text, **more}


def young(reduced=r"2 \le \frac{C}{\varepsilon}", **more):
    """For every ε > 0 there is C ≥ 0, independent of ε, with an estimate that reduces to
    `reduced`: the reading chooses C before ε."""
    return [req("e", "for every", "for every ε > 0", binds=["ε"], domain="ε > 0"),
            req("c", "constant dependence", "C is independent of ε", parent="e", binds=["C"],
                domain="C ≥ 0", independent_of=["ε"]),
            req("e.1", "conclusion", "the estimate", parent="e", reduced=reduced, **more)]


# -- the search ----------------------------------------------------------------------------------

def test_for_2_le_C_over_eps_it_proposes_eps_equal_C_plus_1():
    s = est.search(young(), "e.1")
    # The quantifier order is the reading's: C is chosen before ε and kept fixed.
    assert s["reading"] == ("there is C (C ≥ 0), independent of ε; for every ε (ε > 0): the "
                            "estimate")
    assert [(o["var"], o["quantifier"]) for o in s["order"]] == \
        [("C", "there is"), ("ε", "for every")]
    assert (s["supported"], s["result"]) == (True, "proposed")
    [p] = s["proposals"]
    assert (p["form"], p["assign"], p["family"]) == ("family", {"ε": "C + 1"}, ["C"])
    assert p["reduced"] == "2 ≤ C/(C + 1)"
    assert p["violation"] == "left − right = (C + 2)/(C + 1) > 0 for every C ≥ 0"
    assert p["domain"] == ["ε = C + 1 > 0 for every C ≥ 0"]
    assert (p["standing"], p["by"]) == ("candidate", ["a family in C"])
    # Endpoints and limits come first, each refuted at a value of C or left undecided; the
    # family is the first value violated for every C.
    assert [a["assign"]["ε"] for a in s["attempts"]] == \
        ["1/2", "1/4", "1/8", "1", "2", "4", "8", "16", "C + 1"]
    assert s["attempts"][0] == {"assign": {"ε": "1/2"}, "by": ["towards ε → 0⁺"],
                                "result": "not violated", "at": "2 ≤ 2·C",
                                "why": "not violated at C = 1"}
    assert s["budget"] == {"checks": 64, "used": 9, "exhausted": False}
    assert s["obligation_sha256"] == est.obligation(young(), "e.1")["sha256"]


def test_a_reading_without_a_constant_gets_an_instance():
    recs = [req("n", "for every", "for every n ≥ 0", binds=["n"], domain="n ≥ 0"),
            req("n.k", "for every", "for every k ≥ 0", parent="n", binds=["k"],
                domain=r"k \ge 0"),
            req("n.k.1", "conclusion", "n ≤ k n²", parent="n.k", reduced="n ≤ k n²")]
    [p] = est.search(recs, "n.k.1")["proposals"]
    assert (p["form"], p["assign"], p["family"], p["reduced"]) == \
        ("instance", {"n": "1", "k": "0"}, [], "1 ≤ 0")


def test_the_budget_is_reported_and_its_exhaustion_said():
    s = est.search(young(), "e.1", budget=2)
    assert s["budget"] == {"checks": 2, "used": 2, "exhausted": True}
    assert (s["result"], s["proposals"]) == ("budget exhausted", [])
    text = "\n".join(est.search_lines(s))
    assert "budget: 2 of 2 checks used; exhausted before a candidate was found" in text
    assert "no candidate within the budget" in text


def test_a_corrected_reading_gets_no_candidate_and_no_verdict():
    recs = young() + [req("e2", "for every", "for every 0 < ε ≤ 1", binds=["ε"],
                          domain=r"0 < \varepsilon \le 1", origin="correction", corrects="e")]
    printed, corrected = est.searches(recs)
    assert printed["result"] == "proposed" and corrected["corrections"] == ["e2"]
    assert (corrected["result"], corrected["proposals"]) == ("none found", [])
    assert corrected["budget"] == {"checks": 64, "used": 10, "exhausted": False}
    # ε = C + 1 leaves the corrected domain; nothing says the estimate holds.
    fam = next(a for a in corrected["attempts"] if a["assign"]["ε"] == "C + 1")
    assert fam["result"] == "domain not shown"
    said = json.dumps(corrected, ensure_ascii=False) + "\n".join(est.search_lines(corrected))
    for word in ("verified", "holds", "admissible counterexample", "proved"):
        assert word not in said
    assert "Finding no candidate establishes nothing about the estimate." in said


@pytest.mark.parametrize("reduced, said", [
    (r"\sum_k a_k \le C", ["unsupported: \\sum"]),
    (r"|\varepsilon| \le C", ["unsupported: |·| (an absolute value)"]),
    (r"2 \le C \mathrm{e}", ["unsupported: \\mathrm"]),
    (r"2 \le C/\delta", ["\\delta is not a variable of this reading"]),
    ("2 C", ["unsupported: no relation (≤, <, ≥, >, =) between two sides"]),
    (r"0 < \varepsilon \le C", ["unsupported: more than one relation (<, ≤): give one"]),
    (r"2 \le C^{\varepsilon}", ["unsupported: a power whose exponent is not a whole number "
                                "up to 32"]),
])
def test_each_construct_it_does_not_support_is_named(reduced, said):
    s = est.search(young(reduced), "e.1")
    assert (s["supported"], s["result"], s["unsupported"]) == (False, "not supported", said)
    assert s["budget"]["used"] == 0 and s["proposals"] == []


def test_a_domain_it_cannot_read_and_a_missing_obligation_are_named():
    recs = young()
    recs[0] = {**recs[0], "domain": "ε ∈ (0, 1]"}
    assert est.search(recs, "e.1")["unsupported"] == [
        "the domain of ε (ε ∈ (0, 1]) is not read: the search reads bounds such as 0 < ε ≤ 1"]
    recs[0] = {k: v for k, v in recs[0].items() if k != "domain"}
    assert est.search(recs, "e.1")["unsupported"] == [
        "ε has no domain in this reading: the search does not choose its values"]
    plain = [r if r["local_id"] != "e.1" else {k: v for k, v in r.items() if k != "reduced"}
             for r in young()]
    assert est.search(plain, "e.1")["unsupported"] == [
        "e.1 records no reduced obligation (`reduced`), which is what the search reads"]
    # A constant with no bound leaves every family undecided: nothing is proposed.
    loose = young()
    loose[1] = {k: v for k, v in loose[1].items() if k != "domain"}
    s = est.search(loose, "e.1")
    assert s["result"] == "none found"
    fam = next(a for a in s["attempts"] if a["assign"]["ε"] == "C + 1")
    assert (fam["result"], fam["why"]) == \
        ("domain not shown", "ε = C + 1 > 0 is not shown (C with no bound in this reading)")


def test_a_candidate_recorded_by_the_auditor_reads_as_a_family():
    [p] = est.search(young(), "e.1")["proposals"]
    cx = {"specialisation": {"assign": p["assign"]}, "reduced": p["reduced"],
          "violation": p["violation"]}
    a = est.analyse(cx, est.obligation(young(), "e.1"))
    assert (a["form"], a["decisive"], a["standing"]) == ("family", True, "candidate")


# -- the reduced obligation on a requirement ------------------------------------------------------

def test_a_reduced_obligation_belongs_to_the_requirement_a_reading_ends_in():
    ws = {"records": {}}
    out = rq.requirement_content({"claim": "X"}, {"local_id": "e.1", "form": "conclusion",
                                                  "text": "t", "reduced": " 2 ≤ C/ε "}, ws, None)
    assert out["reduced"] == "2 ≤ C/ε"
    with pytest.raises(wsp.WorkspaceError, match="not to one that binds variables"):
        rq.requirement_content({"claim": "X"}, {"local_id": "e", "form": "for every",
                                                "text": "t", "reduced": "2 ≤ C"}, ws, None)
    # It is part of what a reading reads, and a requirement without one reads as before.
    r = req("e.1", "conclusion", "the estimate", parent="e")
    before = {k: r.get(k) for k in ("form", "text", "binds", "independent_of", "origin",
                                    "parent", "corrects")}
    before["fragments"] = []
    assert rq.reading_digest(r, []) == "reading-v1:" + hashlib.sha256(json.dumps(
        before, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert rq.reading_digest({**r, "reduced": "2 ≤ C/ε"}, []) != rq.reading_digest(r, [])


# -- on request, from the command line ------------------------------------------------------------

@pytest.fixture
def work(tmp_path):
    w = tmp_path / ".machinechecked"
    shutil.copytree(DATA, w / "site" / "data")
    (w / "sources" / "P").mkdir(parents=True)
    (w / "sources" / "P" / "main.tex").write_text(PAPER.read_text(encoding="utf-8"),
                                                  encoding="utf-8")
    return w


def _digests(root: Path) -> dict[str, str]:
    return {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(root.rglob("*")) if f.is_file()}


def _run(argv, capsys):
    try:
        cli.main(argv)
        code = 0
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


def test_the_search_runs_on_request_and_records_nothing(work, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_built_work", lambda a: (work, tmp_path))
    snap = Snapshot(work / "site" / "data")
    p = wsp.open_for(work, WHO, "informed", sources=snap.sources())
    wsp.update(p, [{"op": "put", "record": {**r, "claim": CLAIM}} for r in young()], snap)
    wid = wsp.read(p)["id"]
    before = _digests(work.parent)
    status = snap.chunk(CLAIM)["status_code"]

    code, out, _ = _run(["compare", "--query", "counterexamples", "Theorem 24", "--json"], capsys)
    doc = json.loads(out)
    assert code == 0 and doc["op"] == "counterexamples" and doc["available"]
    assert doc["subject"]["claim"] == CLAIM and doc["subject"]["budget"] == 64
    [s] = doc["results"]
    assert (s["id"], s["workspace"], s["reviewer"], s["requirement"]) == \
        (f"{wid}:e.1", wid, "human:A-Auditor", "e.1")
    assert s["proposals"][0]["assign"] == {"ε": "C + 1"}
    assert s["proposals"][0]["standing"] == "candidate"
    code, out, _ = _run(["compare", "--query", "counterexamples", "Theorem 24", "--budget", "3"],
                        capsys)
    assert code == 0 and "budget: 3 of 3 checks used; exhausted" in out
    # The matching flag of `workspace suggest`, for one requirement.
    code, out, _ = _run(["workspace", "suggest", "--claim", "Theorem 24", "--requirement", "e.1",
                         "--counterexamples", "--id", wid], capsys)
    doc = json.loads(out)
    assert code == 0 and doc["searches"][0]["proposals"][0]["assign"] == {"ε": "C + 1"}
    code, out, _ = _run(["workspace", "suggest", "--claim", "Theorem 24", "--requirement", "e.1",
                         "--counterexamples", "--apply", "--id", wid], capsys)
    assert code == 1 and "only proposes candidates" in json.loads(out)["error"]
    code, out, _ = _run(["compare", "--query", "search", "Theorem 24", "--budget", "3"], capsys)
    assert code == 1
    # Nothing was written: no counterexample is recorded, and the claim's status is the engine's.
    assert _digests(work.parent) == before
    assert not [r for r in wsp.read(p)["records"].values() if r["kind"] == "counterexample"]
    assert Snapshot(work / "site" / "data").chunk(CLAIM)["status_code"] == status
