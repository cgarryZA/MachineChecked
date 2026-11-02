"""A project whose built modules cannot all be loaded together, and one with an unbuilt module.

Synthetic: a `Challenge` library states `Twin.target` with `sorry` (a statement left for others
to prove) and a `Solution` library proves the same name, so the two cannot be imported into one
Lean session; a `Later` library is never built. MachineChecked must probe them apart, tell the
solution from the challenge by module, call a link without a module ambiguous rather than
guess, and say a declaration in an unbuilt module is not built, not "not found".
"""

import json
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
    """The linked names are answered in the sessions that build the index; a second build reuses
    the stored facts and starts no session; with the index stored but not a name's record, the
    name is checked by loading only the modules that declare it; a name whose source is in an
    unbuilt module is never asked of Lean. The statuses do not change."""
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
    # One session per library, each building the index (with the reverse references) and answering the linked names.
    assert len(sessions) == 2 and all(kinds == {"index", "refs", "link", "modules"}
                                      for _, kinds, _ in sessions)
    assert all("Twin.target" in names for *_, names in sessions)
    assert not any("Later.result" in names for *_, names in sessions)

    sessions.clear()
    assert statuses() == first
    assert sessions == []

    # Without the stored records of the links, only the modules declaring a name are loaded.
    from prooflens.facts import Store
    Store(twins, [], out / "build", []).drop("link")
    assert statuses() == first
    target = [mods for mods, _, names in sessions if "Twin.target" in names]
    assert sorted(target) == [["Challenge.Main"], ["Solution.Main"]]
    assert not any("Later.result" in names for *_, names in sessions)


@needs_lean
@needs_tex
def test_check_names_the_modules_of_links_lean_did_not_check(twins, monkeypatch, capsys):
    """`check` and `check --json` name the module that is not built and the modules that declare
    an ambiguous name, after the engine's own status words."""
    from prooflens import cli
    monkeypatch.chdir(twins)
    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        cli.main(["check"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert ("FAIL Theorem 2 -> Twin.target: linked: Lean name is ambiguous. "
            "Declared in Challenge.Main, Solution.Main.") in out
    assert ("FAIL Theorem 3 -> Later.result: linked: Lean not checked (module not built). "
            "Module Later.Main is not built.") in out
    assert "FAIL Theorem 4 -> Nowhere.result: linked: Lean declaration not found\n" in out
    with pytest.raises(SystemExit):
        cli.main(["check", "--json"])
    links = {c["number"]: c["links"][0] for c in json.loads(capsys.readouterr().out)["claims"]}
    assert links["Theorem 2"]["status_code"] == "link.ambiguous"
    assert links["Theorem 2"]["status_detail"] == "Declared in Challenge.Main, Solution.Main."
    assert links["Theorem 3"]["status_code"] == "link.module-unbuilt"
    assert links["Theorem 3"]["status_detail"] == "Module Later.Main is not built."
    assert "status_detail" not in links["Theorem 1"] and "status_detail" not in links["Theorem 4"]


# How a session fails that cannot load `Broken.Main`, as `probe_modules` stores it.
BROKEN = ("the Lean probe failed (1):\nProbe.lean:3:0: error: object file Broken/Main.olean of "
          "module Broken.Main does not exist\n")


def synthetic_view(root):
    """A view with one claim per state Lean did not check a link in, each state and its detail
    as `resolve_link` gives them."""
    from prooflens.simple import resolve_link
    cases = [("Theorem 1", "Later.result", "Later.Main", [], ["Later.Main"], {}),
             ("Theorem 2", "Broken.result", "Broken.Main", [], [], {"Broken.Main": BROKEN}),
             ("Theorem 3", "Twin.target", None,
              [{"module": "Challenge.Main"}, {"module": "Solution.Main"}], [], {})]
    claims = []
    for k, (number, name, module, recs, unbuilt, failed) in enumerate(cases, 1):
        rec, state = resolve_link(name, recs, module, root, unbuilt, failed)
        assert rec is None
        claims.append({"id": f"P:thm:{k}", "key": f"thm:{k}", "number": number, "title": None,
                       **state, "links": [{"name": name, **state, "source": "formalization.yaml",
                                           "record": None}],
                       "suggestions": [], "reviews": [], "references": []})
    return {"body": {"mode": "simple", "paper": "P", "title": "Synthetic", "commit": None,
                     "notes": [], "module_docs": [], "project": {"built": 2, "unbuilt": 1},
                     "claims": claims}}


@pytest.mark.parametrize("number, code, detail", [
    ("Theorem 1", "link.module-unbuilt", "Module Later.Main is not built."),
    ("Theorem 2", "link.module-failed", "Module Broken.Main could not be loaded on its own: "
                                        "object file Broken/Main.olean of module Broken.Main "
                                        "does not exist"),
    ("Theorem 3", "link.ambiguous", "Declared in Challenge.Main, Solution.Main."),
])
def test_check_names_the_module_behind_each_unchecked_state(tmp_path, monkeypatch, capsys,
                                                             number, code, detail):
    """Each of the three states: `check` prints the module (and for one that could not be
    loaded, what Lean reported) after the status words, which stay the engine's, and
    `check --json` gives it as the link's `status_detail`."""
    from prooflens import cli
    from prooflens.status import STATUSES
    view = synthetic_view(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_simple_target", lambda a: (tmp_path, tmp_path / "paper.tex"))
    monkeypatch.setattr(cli, "_simple_view", lambda *a, **k: view)
    name = next(c["links"][0]["name"] for c in view["body"]["claims"] if c["number"] == number)
    with pytest.raises(SystemExit) as exc:
        cli.main(["check"])
    assert exc.value.code == 1
    assert f"FAIL {number} -> {name}: {STATUSES[code]['label']}. {detail}\n" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--json"])
    assert exc.value.code == 1
    doc = json.loads(capsys.readouterr().out)
    claim = next(c for c in doc["claims"] if c["number"] == number)
    assert claim["links"] == [{"name": name, "status": STATUSES[code]["label"],
                               "status_code": code, "class": "unspecified",
                               "status_detail": detail, "source": "formalization.yaml"}]
    # The detail adds to the status: the claim's status is the link's, unchanged.
    assert (claim["status_code"], claim["status"]) == (code, STATUSES[code]["label"])


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


def lean_fails_on(monkeypatch, bad, message, records=()):
    """Make every Lean session that loads a module of `bad` fail with `message` (an error Lean
    reported, so the same inputs fail again); the others finish with a copy of `records` (none
    by default). Returns the modules of each session started."""
    from prooflens import simple
    calls = []

    def probe(root, group, *a, **k):
        calls.append(list(group))
        if set(group) & set(bad):
            raise simple.ViewError(message, deterministic=True)
        return [dict(r) for r in records] + [{"record": "done"}]
    monkeypatch.setattr(simple, "run_simple_probe", probe)
    return calls


def many_errors(work, module, n=40):
    """What Lean prints when it cannot load `module`: `n` errors, each at a position in the
    probe's temporary file, longer in all than what is kept of a failure."""
    probe = work / "prooflens-probe-k2x9" / "Probe.lean"
    return ("the Lean probe failed (1):\n"
            + "".join(f"{probe}:{i + 2}:0: error: unknown constant '{module}.missing{i}'\n"
                      for i in range(n)))


def test_a_module_that_fails_alone_is_named_with_its_error(tmp_path, monkeypatch):
    """A library of one module that Lean cannot load: the link's detail says it could not be
    loaded on its own and gives the first errors Lean reported, without the probe's temporary
    file and trimmed to a few, though Lean printed more than the failure keeps."""
    from prooflens import simple
    from prooflens.status import STATUSES
    calls = lean_fails_on(monkeypatch, ["Solo"], many_errors(tmp_path / "work", "Solo"))
    split = {}
    recs, failed = simple.probe_modules(tmp_path, ["Solo"], ["Solo"], [], log=lambda m: None,
                                        split=split)
    assert calls == [["Solo"]] and list(failed) == ["Solo"] and split == {}
    # The first errors are kept, not only the end of Lean's output.
    assert "Solo.missing0'" in failed["Solo"] and "Solo.missing39'" in failed["Solo"]
    assert len(failed["Solo"]) < 1300
    rec, state = simple.resolve_link("Solo.result", [], "Solo", tmp_path, [], failed, split)
    assert rec is None
    assert state == {"status_code": "link.module-failed",
                     "status": STATUSES["link.module-failed"]["label"], "class": "unspecified",
                     "status_detail": "Module Solo could not be loaded on its own: unknown "
                                      "constant 'Solo.missing0'; unknown constant "
                                      "'Solo.missing1'; unknown constant 'Solo.missing2'; …"}


def test_a_module_that_fails_within_a_split_group_says_so(tmp_path, monkeypatch):
    """A library whose modules cannot be loaded in one session is loaded apart; the module that
    still fails on its own is named with the library's session it was split from and with what
    Lean reported, its paths given from the project's root, as is the line that says why the
    library was split. The others load."""
    from prooflens import simple
    olean = tmp_path / ".lake" / "build" / "lib" / "lean" / "Pair" / "Bad.olean"
    calls = lean_fails_on(monkeypatch, ["Pair.Bad"],
                          f"the Lean probe failed (1):\nProbe.lean:2:0: error: failed to read "
                          f"file '{olean}', invalid header\n")
    split, said = {}, []
    recs, failed = simple.probe_modules(tmp_path, ["Pair", "Pair.Bad", "Pair.Good"], ["Pair"],
                                        [], log=said.append, split=split)
    assert calls[0] == ["Pair", "Pair.Bad", "Pair.Good"] and ["Pair.Bad"] in calls
    assert list(failed) == ["Pair.Bad"]
    assert split == {"Pair.Bad": {"library": "Pair", "modules": 3}}
    assert said[0] == ("lean: Pair could not be loaded in one session (failed to read file "
                       "'.lake/build/lib/lean/Pair/Bad.olean', invalid header); splitting it")
    (tmp_path / "Pair").mkdir()
    (tmp_path / "Pair" / "Bad.lean").write_text("theorem Pair.result : True := trivial\n")
    _, state = simple.resolve_link("Pair.result", [], None, tmp_path, [], failed, split)
    assert state["status_code"] == "link.module-failed"
    assert state["status_detail"] == (
        "Module Pair.Bad could not be loaded on its own, after 3 modules of Pair could not be "
        "loaded in one Lean session: failed to read file "
        "'.lake/build/lib/lean/Pair/Bad.olean', invalid header")


def test_the_split_line_gives_the_first_error_without_the_probe_file(tmp_path, monkeypatch):
    """The line that says why a library was split gives Lean's first error as `loading_error`
    does: without the position in the probe's temporary file, and with "…" when Lean reported
    more."""
    from prooflens import simple
    lean_fails_on(monkeypatch, ["Pair.Bad"], many_errors(tmp_path / "work", "Boom"))
    said = []
    simple.probe_modules(tmp_path, ["Pair.Bad", "Pair.Good"], ["Pair"], [], log=said.append)
    assert said == ["lean: Pair could not be loaded in one session (unknown constant "
                    "'Boom.missing0'; …); splitting it"]


def test_a_failure_with_no_error_line_says_what_ended_it():
    """A session that ran out of a resource, or that ended with no message: the detail says what
    there is, one line each."""
    from prooflens.simple import loading_error
    assert loading_error("the Lean probe failed (1):\nINTERNAL PANIC: out of memory\n") == \
        "INTERNAL PANIC: out of memory"
    assert loading_error("the Lean probe failed (-9):\n\n") == "the Lean probe failed (-9)"
    assert loading_error("the Lean probe (Solo) timed out after 3600 s") == \
        "the Lean probe (Solo) timed out after 3600 s"
    assert loading_error("") == ""


LOADS = r"""\documentclass{article}
\usepackage{amsthm}
\newtheorem{theorem}{Theorem}
\begin{document}
\begin{theorem}\label{thm:a} Something true. \end{theorem}
\begin{theorem}\label{thm:b} Something else true. \end{theorem}
\end{document}
"""


@needs_tex
def test_check_and_the_reader_give_the_loading_error(tmp_path, monkeypatch, capsys):
    """A module that fails alone and one that fails within a split group, through `check`,
    `check --json` (the second from the stored failures, with no Lean session) and the site's
    data: each link's detail gives what Lean reported, and the build's note names each module
    with its first error. The status words are the engine's."""
    from prooflens import cli
    from prooflens.status import STATUSES
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copyfile(ROOT / "examples" / "plain-paper" / "lean-toolchain", root / "lean-toolchain")
    (root / "lakefile.toml").write_text('name = "proj"\n\n[[lean_lib]]\nname = "Solo"\n\n'
                                        '[[lean_lib]]\nname = "Pair"\n')
    (root / "Solo.lean").write_text("theorem Solo.result : True := trivial\n")
    (root / "Pair").mkdir()
    (root / "Pair.lean").write_text("import Pair.Bad\n")
    (root / "Pair" / "Bad.lean").write_text("theorem Pair.result : True := trivial\n")
    built = root / ".lake" / "build" / "lib" / "lean"
    (built / "Pair").mkdir(parents=True)
    for m in ["Solo", "Pair", "Pair/Bad"]:
        (built / f"{m}.olean").write_bytes(b"")
    (root / "paper.tex").write_text(LOADS)
    (root / "formalization.yaml").write_text(
        'version: "v0.4"\nsources:\n  - title: "Loads"\n    relationship: "formalizes"\n'
        'alignment:\n  statements:\n    - source: "Theorem 1"\n      lean: "Solo.result"\n'
        '      module: "Solo"\n    - source: "Theorem 2"\n      lean: "Pair.result"\n')
    work = root / ".machinechecked" / "build"
    calls = lean_fails_on(monkeypatch, ["Solo", "Pair.Bad"], many_errors(work, "Boom"))
    monkeypatch.chdir(root)
    label = STATUSES["link.module-failed"]["label"]
    errors = ("unknown constant 'Boom.missing0'; unknown constant 'Boom.missing1'; "
              "unknown constant 'Boom.missing2'; …")
    alone = f"Module Solo could not be loaded on its own: {errors}"
    apart = ("Module Pair.Bad could not be loaded on its own, after 2 modules of Pair could not "
             f"be loaded in one Lean session: {errors}")
    note = ("2 built module(s) could not be loaded by MachineChecked and are not indexed: "
            "Pair.Bad (unknown constant 'Boom.missing0'; …), "
            "Solo (unknown constant 'Boom.missing0'; …)")

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        cli.main(["check"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert f"FAIL Theorem 1 -> Solo.result: {label}. {alone}\n" in out
    assert f"FAIL Theorem 2 -> Pair.result: {label}. {apart}\n" in out
    assert f"note: {note}\n" in out
    assert "prooflens-probe-" not in out and str(root) not in out

    # The failures are stored: the next check asks Lean nothing about those modules.
    calls.clear()
    with pytest.raises(SystemExit) as exc:
        cli.main(["check", "--json"])
    assert exc.value.code == 1
    assert not any({"Solo", "Pair.Bad"} & set(g) for g in calls)
    doc = json.loads(capsys.readouterr().out)
    links = {c["number"]: c["links"][0] for c in doc["claims"]}
    assert {n: (l["status_code"], l["status"], l["status_detail"]) for n, l in links.items()} == {
        "Theorem 1": ("link.module-failed", label, alone),
        "Theorem 2": ("link.module-failed", label, apart)}
    assert note in doc["notes"]

    # The reader's data: the note in the index, the detail on each claim's link.
    capsys.readouterr()
    cli.main(["build"])
    data = root / ".machinechecked" / "site" / "data"
    index = json.loads((data / "index.json").read_text())
    assert note in index["notes"]
    shown = {}
    for c in index["claims"]:
        chunk = json.loads((data / "claims" / c["file"]).read_text())
        shown[c["number"]] = [(l["status"], l["status_detail"]) for l in chunk["links"]]
    assert shown == {"Theorem 1": [(label, alone)], "Theorem 2": [(label, apart)]}
    assert "prooflens-probe-" not in (data / "index.json").read_text()


def test_uses_inspect_and_proof_facts_give_the_loading_error(tmp_path, monkeypatch, capsys):
    """A module that Lean cannot load, beside a library that loads: `uses` lists it in its
    scope, and `inspect`, proof facts and a certificate check stop on it, each with what Lean
    reported as `check` gives it, without the probe's temporary file or the project's path."""
    from prooflens import cli
    from prooflens.deps import inspect
    from prooflens.estimates import check
    from prooflens.proof_facts import extract
    from prooflens.simple import ViewError
    from prooflens.uses import uses
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "proj"\n\n[[lean_lib]]\nname = "Solo"\n\n'
                                        '[[lean_lib]]\nname = "Good"\n')
    (root / "Solo.lean").write_text("theorem Solo.result : True := trivial\n")
    (root / "Good.lean").write_text("theorem Good.base : True := trivial\n")
    built = root / ".lake" / "build" / "lib" / "lean"
    built.mkdir(parents=True)
    for m in ["Solo", "Good"]:
        (built / f"{m}.olean").write_bytes(b"")
    lean_fails_on(monkeypatch, ["Solo"], many_errors(root / ".machinechecked" / "build", "Boom"),
                  [{"record": "uses", "name": "Good.base", "module": "Good", "kind": "theorem",
                    "searched": 1}])
    errors = ("unknown constant 'Boom.missing0'; unknown constant 'Boom.missing1'; "
              "unknown constant 'Boom.missing2'; …")
    alone = f"Module Solo could not be loaded on its own: {errors}"

    doc = uses(root, "Good.base")
    assert doc["ok"] and not doc["complete"]
    assert doc["scope"]["failed"] == {"Solo": errors}
    for ask in [lambda: inspect(root, "Solo.result"), lambda: extract(root, "Solo.result"),
                lambda: check(root, "Solo.result", "Solo.claim", "proves")]:
        with pytest.raises(ViewError) as e:
            ask()
        assert str(e.value) == alone

    # The commands print the same.
    monkeypatch.chdir(root)
    capsys.readouterr()
    cli.main(["inspect", "--used-by", "Good.base", "--json"])
    out = capsys.readouterr().out
    assert json.loads(out)["scope"]["failed"] == {"Solo": errors}
    with pytest.raises(SystemExit) as exc:
        cli.main(["inspect", "Solo.result", "--json"])
    assert exc.value.code == 2
    said = capsys.readouterr()
    assert json.loads(said.out)["error"] == {"kind": "error", "message": alone}
    assert f"machinechecked: {alone}\n" in said.err
    for text in [out, said.out, said.err]:
        assert "prooflens-probe-" not in text and str(tmp_path) not in text
