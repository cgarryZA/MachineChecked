"""Where a declaration is used, and how (#144), on the synthetic project tests/fixtures/uses.

`Uses.half_lt` has an extra condition `Good n`. `caller_assumes` passes its own hypothesis for
it; `caller_proves` applies it to the number `2 * (m + 1)` it constructs and proves the
condition with `good_double`. The specialised helper `half_lt_four` is used by the general
wrapper `main_bound`, the declaration the paper's theorem is linked to. `twice` applies
`good_double` twice, each time to a variable printed `x` bound in its own scope; `uses_instance`
applies `length_pos` with an implicit type and an instance. `Good` is mentioned in statements
and in the body of `goodSet`; `Uses.Other` imports `Uses.Main` and uses nothing of it.
"""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean, needs_tex
from prooflens import uses as us
from prooflens.uses import uses

SRC = ROOT / "tests" / "fixtures" / "uses"


def _build(root):
    r = subprocess.run(["lake", "build"], cwd=root, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        pytest.skip(f"could not build the fixture: {r.stdout[-500:]}")


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("uses") / "uses"
    shutil.copytree(SRC, root)
    _build(root)
    return root


def app(out, caller, index=0):
    found = [a for a in out["applications"] if a["caller"] == caller]
    assert found, f"no application in {caller}: {[a['caller'] for a in out['applications']]}"
    return found[index]


def param(a, binder):
    return next(p for p in a["params"] if p["binder"] == binder)


@needs_lean
def test_a_premise_assumed_by_one_caller_and_proved_by_another(project):
    out = uses(project, "Uses.half_lt")
    assert out["ok"] and out["schema"] == "machinechecked/uses@1"
    assert out["declaration"]["module"] == "Uses.Main"
    assert out["complete"] and out["answer"] == "used"
    users = {u["name"]: u for u in out["users"]}
    assert set(users) == {"Uses.caller_assumes", "Uses.caller_proves", "Uses.half_lt_four",
                          "Uses.main_bound"}
    assert all(u["refs"] == ["proof"] for u in users.values())

    # The general lemma at a concrete parameter: the exact instantiated premise and conclusion,
    # and where each comes from.
    a = app(out, "Uses.caller_proves")
    assert a["available"] and a["location"]["precision"] == "declaration"
    assert a["location"]["range"]["line"] > 0 and a["location"]["path"]
    n = param(a, "n")
    assert n["role"] == "parameter" and n["argument"]["text"] == "2 * (m + 1)"
    h = param(a, "h")
    assert h["role"] == "premise" and h["type"]["text"] == "Uses.Good (2 * (m + 1))"
    assert h["discharge"] == "proved"
    assert h["origin"] == {"kind": "theorem application", "name": "Uses.good_double",
                           "owner": "Uses.good_double"}
    assert h["supplied"] == "by Uses.good_double"
    assert param(a, "hpos")["discharge"] == "proved"
    assert a["result"]["text"] == "2 * (m + 1) / 2 < 2 * (m + 1)"
    assert a["unsupplied"] == [] and a["extra_args"] == 0
    # The variable `m` of the caller is a reference to its binder, not a name.
    assert [s["var"] for s in n["argument"]["segments"] if "var" in s] == [0]
    assert a["locals"][0]["name"] == "m" and a["locals"][0]["parameter"] is True

    # The other caller assumes the condition: its own hypothesis `hm` is passed on.
    b = app(out, "Uses.caller_assumes")
    hb = param(b, "h")
    assert hb["discharge"] == "assumed" and hb["origin"]["kind"] == "caller hypothesis"
    assert hb["origin"]["name"] == "hm" and hb["type"]["text"] == "Uses.Good m"
    assert hb["supplied"] == "the caller's hypothesis hm"
    assert [p["discharge"] for p in b["premises"]] == ["assumed", "assumed"]
    assert {p["discharge"] for p in a["premises"]} == {"proved"}
    # The text the terminal shows says the same.
    t = us.text(out)
    assert "assumed by the caller: the caller's hypothesis hm" in t
    assert "proved in the caller: by Uses.good_double" in t
    # A module that imports the declaration's module and uses none of it is not a use.
    assert "Uses.Other" in out["imports_without_use"]


@needs_lean
def test_a_specialised_helper_leads_to_its_general_wrapper(project):
    out = uses(project, "Uses.half_lt_four")
    assert [u["name"] for u in out["users"]] == ["Uses.main_bound"]
    a = app(out, "Uses.main_bound")
    assert a["params"] == [] and a["result"]["text"] == "4 / 2 < 4"
    # From the general lemma, the wrapper is reached directly and through the helper.
    out = uses(project, "Uses.good_double")
    further = {f["name"]: f for f in out["further"]}
    assert further["Uses.main_bound"]["through"] == "Uses.half_lt_four"


@needs_lean
def test_implicit_and_instance_arguments_and_local_scopes_are_kept(project):
    a = app(uses(project, "Uses.length_pos"), "Uses.uses_instance")
    roles = [(p["binder"], p["role"], p["binder_info"]) for p in a["params"]]
    assert roles == [("α", "parameter", "implicit"), ("inst", "instance", "instance"),
                     ("xs", "parameter", "explicit"), ("x", "parameter", "explicit"),
                     ("h", "premise", "explicit")]
    assert param(a, "α")["argument"]["text"] == "Nat"
    inst = param(a, "inst")
    assert inst["type"]["text"] == "Inhabited Nat"
    assert inst["origin"] == {"kind": "instance", "name": "instInhabitedNat"}
    assert param(a, "h")["type"]["text"] == "y ∈ ys" and param(a, "h")["discharge"] == "assumed"

    # Two arguments printed `x`, bound in different scopes, are two variables.
    out = uses(project, "Uses.good_double")
    first, second = [x for x in out["applications"] if x["caller"] == "Uses.twice"]
    o1, o2 = param(first, "n")["origin"], param(second, "n")["origin"]
    assert o1["name"] == o2["name"] == "x" and o1["kind"] == "local variable"
    assert o1["id"] != o2["id"]
    assert first["locals"][0]["id"] != second["locals"][0]["id"]


@needs_lean
def test_statement_body_and_proof_references_are_kept_apart(project):
    out = uses(project, "Uses.Good")
    refs = {u["name"]: u["refs"] for u in out["users"]}
    assert refs["Uses.goodSet"] == ["definition body"]
    assert refs["Uses.good_zero"] == ["statement"]
    # A hypothesis `Good n` of the statement is not counted again in the proof.
    assert refs["Uses.half_lt"] == ["statement"]
    assert "proof" in refs["Uses.twice"]
    # Applications are looked for in values only.
    assert {a["caller"] for a in out["applications"]} == {"Uses.goodSet", "Uses.twice"}


@needs_lean
def test_a_repeat_query_starts_no_lean_session_and_a_change_reopens_it(tmp_path, monkeypatch):
    root = tmp_path / "uses"
    shutil.copytree(SRC, root)
    _build(root)
    first = uses(root, "Uses.half_lt")
    assert not first["cache"]["hit"]

    def no_lean(*a, **k):
        raise AssertionError("a Lean session was started")

    monkeypatch.setattr(us, "probe_modules", no_lean)
    again = uses(root, "Uses.half_lt")
    assert again["cache"]["hit"] and again["applications"] == first["applications"]
    monkeypatch.undo()
    # The reverse references are shared: another declaration needs only its own applications.
    seen = []
    real = us.probe_modules

    def spy(root_, mods, libs, requests, *a, **k):
        seen.append([r["kind"] for r in requests])
        return real(root_, mods, libs, requests, *a, **k)

    monkeypatch.setattr(us, "probe_modules", spy)
    uses(root, "Uses.good_double")
    assert seen == [["apps", "modules"]]
    # A change to a caller's proof reopens the answer: the condition is now assumed.
    p = root / "Uses" / "Main.lean"
    p.write_text(p.read_text().replace(
        "theorem caller_proves (m : Nat) : 2 * (m + 1) / 2 < 2 * (m + 1) :=\n"
        "  half_lt (2 * (m + 1)) (good_double (m + 1)) (by omega)",
        "theorem caller_proves (m : Nat) (hg : Good (2 * (m + 1))) :\n"
        "    2 * (m + 1) / 2 < 2 * (m + 1) :=\n"
        "  half_lt (2 * (m + 1)) hg (by omega)"))
    _build(root)
    changed = uses(root, "Uses.half_lt")
    assert not changed["cache"]["hit"]
    h = param(app(changed, "Uses.caller_proves"), "h")
    assert h["discharge"] == "assumed" and h["origin"]["name"] == "hg"


@needs_lean
def test_an_incomplete_or_ambiguous_scope_is_not_an_absence(tmp_path):
    root = tmp_path / "uses"
    shutil.copytree(SRC, root)
    _build(root)
    # A module of the library that is not built: nothing is asserted about it.
    (root / "Uses" / "Later.lean").write_text(
        "import Uses.Main\n\ntheorem Uses.later : 4 / 2 < 4 := Uses.half_lt_four\n")
    out = uses(root, "Uses.caller_assumes")
    assert out["ok"] and out["users"] == [] and not out["complete"]
    assert out["scope"]["unbuilt"] == ["Uses.Later"]
    assert out["answer"].startswith("not traced")
    out = uses(root, "Uses.half_lt_four")
    assert out["answer"] == "used" and not out["complete"]
    # Two modules declaring the name: ambiguous until the module is given.
    (root / "Uses" / "Later.lean").write_text("theorem Uses.half_lt : True := trivial\n")
    out = uses(root, "Uses.half_lt")
    assert not out["ok"] and out["status"] == "ambiguous"
    assert out["modules"] == ["Uses.Later", "Uses.Main"]
    assert uses(root, "Uses.half_lt", module="Uses.Main")["ok"]


@needs_lean
@needs_tex
def test_the_build_writes_the_reverse_references_and_compare_answers(project, tmp_path,
                                                                     monkeypatch):
    from prooflens import compare as cmp
    from prooflens.cli import main
    monkeypatch.chdir(project)
    main(["build", "--site", str(tmp_path / "site")])
    import json
    data = tmp_path / "site" / "data"
    idx = json.loads((data / "index.json").read_text())
    assert idx["uses"] == "data/uses.json"
    by = json.loads((data / "uses.json").read_text())["by_name"]
    (entry,) = by["Uses.half_lt"]
    assert entry["module"] == "Uses.Main"
    assert {u["name"] for u in entry["users"]} == {"Uses.caller_assumes", "Uses.caller_proves",
                                                   "Uses.half_lt_four", "Uses.main_bound"}
    site = cmp.Site(project / ".machinechecked" / "site" / "data")
    q = cmp.query(site, "uses", "Uses.half_lt_four", root=project)
    assert q["available"] and q["provenance"].startswith("Lean")
    (doc,) = q["results"]
    assert doc["users"][0]["name"] == "Uses.main_bound"
    assert doc["users"][0]["claims"] == ["P:thm:main"]
    assert doc["linked_users"] == ["Uses.main_bound"]
    # The reader's local server gives the same document.
    get = us.route(project, project / ".machinechecked" / "site" / "data")
    assert get({"name": ["Uses.half_lt_four"]})["applications"] == doc["applications"]


@needs_lean
@pytest.mark.parametrize("toolchain", ["leanprover/lean4:v4.24.0"])
def test_the_extraction_runs_on_an_older_lean(tmp_path, toolchain):
    if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                      text=True).stdout.find(toolchain) < 0:
        pytest.skip(f"{toolchain} is not installed")
    root = tmp_path / "uses"
    shutil.copytree(SRC, root)
    (root / "lean-toolchain").write_text(toolchain + "\n")
    _build(root)
    out = uses(root, "Uses.half_lt")
    assert param(app(out, "Uses.caller_assumes"), "h")["discharge"] == "assumed"
    assert param(app(out, "Uses.caller_proves"), "h")["discharge"] == "proved"
    assert out["further"] == [] and "Uses.Other" in out["imports_without_use"]
