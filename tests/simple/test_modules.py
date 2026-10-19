"""A project whose built modules cannot all be loaded together, and one with an unbuilt module.

Synthetic: a `Challenge` library states `Twin.target` with `sorry` (a statement left for others
to prove) and a `Solution` library proves the same name, so the two cannot be imported into one
Lean session; a `Later` library is never built. MachineChecked must probe them apart, tell the
solution from the challenge by module, call a link without a module ambiguous rather than
guess, and say a declaration in an unbuilt module is not built, not "not found".
"""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens.simple import build_view

PAPER = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:a} One plus one is two. \end{theorem}
\begin{theorem}\label{thm:b} One plus one is two, again. \end{theorem}
\begin{theorem}\label{thm:c} A later result. \end{theorem}
\begin{theorem}\label{thm:d} A result nobody wrote. \end{theorem}
\end{document}
"""

YAML = """version: "v0.4"
sources:
  - title: "Twin statements"
    relationship: "formalizes"
alignment:
  statements:
    - source: "Theorem 1"
      lean: "Twin.target"
      module: "Solution.Main"
    - source: "Theorem 2"
      lean: "Twin.target"
    - source: "Theorem 3"
      lean: "Later.result"
    - source: "Theorem 4"
      lean: "Nowhere.result"
"""


@pytest.fixture(scope="module")
def twins(tmp_path_factory):
    root = tmp_path_factory.mktemp("twins")
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text(
        'name = "twins"\n\n[[lean_lib]]\nname = "Challenge"\n\n'
        '[[lean_lib]]\nname = "Solution"\n\n[[lean_lib]]\nname = "Later"\n')
    for lib, body in [("Challenge", "namespace Twin\ntheorem target : 1 + 1 = 2 := by sorry\nend Twin\n"),
                      ("Solution", "namespace Twin\ntheorem target : 1 + 1 = 2 := rfl\nend Twin\n"),
                      ("Later", "theorem Later.result : True := trivial\n")]:
        (root / lib).mkdir()
        (root / lib / "Main.lean").write_text(body)
        (root / f"{lib}.lean").write_text(f"import {lib}.Main\n")
    (root / "paper.tex").write_text(PAPER)
    (root / "formalization.yaml").write_text(YAML)
    r = subprocess.run(["lake", "build", "Challenge", "Solution"], cwd=root,
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")
    return root


@needs_lean
@needs_tex
def test_modules_that_cannot_load_together_are_told_apart(twins):
    view = build_view(twins, twins / "paper.tex", twins / ".machinechecked", log=lambda m: None)
    st = {c["number"]: c for c in view["body"]["claims"]}
    # The solution, named by its module, is the proved one; the challenge never stands in.
    a = st["Theorem 1"]["links"][0]
    assert a["status"] == "linked: Lean proof checked"
    assert (a["record"]["decl"] or {}).get("module") == "Solution.Main"
    # Without a module the name is ambiguous, and nothing is claimed.
    b = st["Theorem 2"]["links"][0]
    assert b["status"].startswith("linked: Lean name is ambiguous")
    assert "Challenge.Main" in b["status_detail"] and "Solution.Main" in b["status_detail"]
    # A declaration in a module that is not built is not built, not missing.
    assert st["Theorem 3"]["links"][0]["status_code"] == "link.module-unbuilt"
    assert st["Theorem 3"]["links"][0]["status_detail"] == "Module Later.Main is not built."
    # Only a declaration absent from the inspected modules is not found.
    assert st["Theorem 4"]["links"][0]["status"] == "linked: Lean declaration not found"
    assert not any("could not be loaded" in n for n in view["body"]["notes"])


@needs_lean
@needs_tex
def test_lean_loads_only_what_it_must(twins, tmp_path, monkeypatch):
    """The linked names are answered in the sessions that build the index; with the index
    reused, a name is checked by loading only the modules that declare it; a name whose source
    is in an unbuilt module is never asked of Lean. The statuses do not change."""
    from prooflens import simple
    sessions, real = [], simple.run_simple_probe

    def spy(root, modules, libs, requests, *a, **k):
        sessions.append((list(modules), {r["kind"] for r in requests},
                         {r["name"] for r in requests if r["kind"] == "link"}))
        return real(root, modules, libs, requests, *a, **k)
    monkeypatch.setattr(simple, "run_simple_probe", spy)
    out = tmp_path / "work"

    def statuses():
        view = build_view(twins, twins / "paper.tex", out, log=lambda m: None)
        return {c["number"]: [l["status"] for l in c["links"]] for c in view["body"]["claims"]}

    first = statuses()
    # One session per library, each building the index and answering the linked names.
    assert len(sessions) == 2 and all(kinds == {"index", "link"} for _, kinds, _ in sessions)
    assert all("Later.result" in names and "Twin.target" in names for *_, names in sessions)

    sessions.clear()
    assert statuses() == first
    target = [mods for mods, _, names in sessions if "Twin.target" in names]
    assert sorted(target) == [["Challenge.Main"], ["Solution.Main"]]
    assert not any("Later.result" in names for *_, names in sessions)


@needs_lean
def test_the_full_assessment_probes_each_library_apart(twins, tmp_path):
    """The full assessment's probe (`probe.run_probe`) runs one session per library too: the
    challenge and the solution are never loaded together, a name both declare differently is
    reported ambiguous (an error, never a choice), and a name both see alike is one record."""
    import dataclasses
    from prooflens.probe import run_probe
    from prooflens.simple import view_config
    cfg = dataclasses.replace(view_config(twins, twins / "paper.tex", tmp_path, ["Challenge", "Solution"]),
                              modules=["Challenge.Main", "Solution.Main"])
    res = run_probe(cfg, [{"kind": "witness", "name": "Twin.target"},
                          {"kind": "witness", "name": "Nat.add_comm"}], build=False)
    assert res["complete"]
    twin = res["proofs"]["witness:Twin.target:"]
    assert any(e.startswith("ambiguous: declared in") and "Challenge.Main" in e
               and "Solution.Main" in e for e in twin["errors"])
    assert not any(e.startswith("ambiguous") for e in res["proofs"]["witness:Nat.add_comm:"]["errors"])


@needs_lean
def test_a_long_session_reports_its_progress(twins, monkeypatch):
    """A Lean session announces itself and, while it runs, says how long it has run."""
    from prooflens import probe
    from prooflens.simple import run_simple_probe
    monkeypatch.setattr(probe, "HEARTBEAT", 1)
    said = []
    run_simple_probe(twins, ["Solution.Main"], ["Solution"], [{"kind": "index", "name": ""}],
                     log=said.append, label="Solution")
    assert said[0] == "lean: Solution: loading 1 module(s)"
    assert any(m.startswith("lean: Solution: 0 min") for m in said[1:])


@needs_lean
def test_a_request_out_of_heartbeats_reports_itself_and_the_probe_goes_on():
    """A request that runs out of heartbeats (a runtime exception, which `try` does not catch)
    emits a probe-error record for itself; the session still answers the others and finishes."""
    import json
    from prooflens.probe import lean_session
    from prooflens.simple import built_modules
    plain = ROOT / "examples" / "plain-paper"
    if not built_modules(plain, ["Plain"])[0]:
        pytest.skip("the plain example is not built")
    query = {"scope_roots": ["Plain"], "spec_prefix": "", "accept_prefix": "",
             "allowed_axioms": ["propext", "Classical.choice", "Quot.sound"],
             "requests": [{"kind": "link", "name": "Plain.oddSum_eq_sq"},
                          {"kind": "link", "name": "Plain.notDeclared"}],
             "max_heartbeats": 1}
    recs = lean_session(plain, ["Plain"], query, lambda lines: [json.loads(l) for l in lines])
    links = {r["name"]: r for r in recs if r.get("record") == "link"}
    assert any(e.startswith("probe-error:") and "heartbeats" in e
               for e in links["Plain.oddSum_eq_sq"]["errors"])
    assert links["Plain.notDeclared"]["errors"] == ["missing"]
    assert recs[-1]["record"] == "done"


def test_a_session_that_is_split_says_why(monkeypatch):
    """When a group of modules cannot be probed in one session, the message names the error."""
    from prooflens import simple
    calls = []

    def fail(root, group, *a, **k):
        calls.append(group)
        if len(group) > 1:
            raise simple.ViewError("the Lean probe failed (1):\nProbe.lean:9:0: error: "
                                   "(deterministic) timeout at `whnf`\nmore")
        return []
    monkeypatch.setattr(simple, "run_simple_probe", fail)
    said = []
    simple.probe_modules(ROOT, ["A.One", "A.Two"], ["A"], [], log=said.append)
    assert said[0] == ("lean: A could not be loaded in one session "
                       "((deterministic) timeout at `whnf`); splitting it")
