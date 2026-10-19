"""The Lean probe's budgets (#114), on a synthetic project: a declaration whose closure is too
large for one heartbeat budget still gets its link record, because each member is printed
under its own; a request that fails with a runtime exception (here the recursion depth) emits
its own error record, and the requests after it are answered, the index and a dependency
walk through the same declaration among them."""

import json
import subprocess

import pytest

from conftest import needs_lean
from prooflens import probe

CHAIN = 2000   # Big.top's closure: Big.d0 … Big.d1999
BUDGET = 5000  # heartbeats (thousands) per request: enough for any one member, not for printing
               # the whole closure under one budget


def project(root, toolchain):
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "big"\ndefaultTargets = ["Big"]\n\n'
                                        '[[lean_lib]]\nname = "Big"\n')
    (root / "lean-toolchain").write_text(toolchain + "\n")
    lines = ["def Big.d0 : Nat := 0"]
    lines += [f"def Big.d{i} : Nat := Big.d{i - 1} + 1" for i in range(1, CHAIN)]
    lines.append(f"theorem Big.top : Big.d{CHAIN - 1} = Big.d{CHAIN - 1} := rfl")
    sum_ = " + ".join(["Big.d0"] * 2000)  # too deep to print
    lines.append(f"theorem Big.huge : {sum_} = {sum_} := rfl")
    lines.append("theorem Big.small : Big.d0 = Big.d0 := rfl")
    (root / "Big.lean").write_text("\n".join(lines) + "\n")
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)


@needs_lean
@pytest.mark.parametrize("toolchain", ["leanprover/lean4:v4.32.0", "leanprover/lean4:v4.24.0"])
def test_a_large_closure_and_a_failing_request_do_not_stop_the_probe(tmp_path, toolchain):
    if subprocess.run(["elan", "toolchain", "list"], capture_output=True,
                      text=True).stdout.find(toolchain) < 0:
        pytest.skip(f"{toolchain} is not installed")
    root = tmp_path / "big"
    project(root, toolchain)
    query = {"scope_roots": ["Big"], "spec_prefix": "", "accept_prefix": "",
             "allowed_axioms": [], "max_heartbeats": BUDGET,
             "requests": [{"kind": "link", "name": n} for n in ("Big.top", "Big.huge", "Big.small")]
             + [{"kind": "index", "name": ""}, {"kind": "deps", "name": "Big.huge"}]}
    recs = probe.lean_session(root, ["Big"], query, lambda ls: [json.loads(l) for l in ls])
    links = {r["name"]: r for r in recs if r["record"] == "link"}
    assert links["Big.top"]["errors"] == [] and len(links["Big.top"]["closure"]) == CHAIN
    (err,) = links["Big.huge"]["errors"]
    assert err.startswith("probe-error: ") and "closure" not in links["Big.huge"]
    assert links["Big.small"]["errors"] == [] and links["Big.small"]["closure"] == ["Big.d0"]
    index = {r["name"]: r for r in recs if r["record"] == "index"}
    assert index["Big.small"]["type"] == "Big.d0 = Big.d0" and len(index) == CHAIN + 3
    nodes = {r["name"]: r for r in recs if r["record"] == "depnode"}
    assert set(nodes) == {"Big.huge", "Big.d0"} and nodes["Big.d0"]["type"] == "Nat"
    (deps,) = [r for r in recs if r["record"] == "deps"]
    assert deps["errors"] == [] and deps["reached"] == 2
    assert recs[-1]["record"] == "done"


def test_a_split_names_the_error_of_the_session(monkeypatch):
    """When a group of modules fails in one session, the message splitting it says why."""
    from prooflens import simple

    def fail(root, group, *a, **k):
        if len(group) > 1:
            raise simple.ViewError(
                "the Lean probe failed (1):\n/tmp/p/Probe.lean:617:0: error: (deterministic) "
                "timeout at `transform`, maximum number of heartbeats (200000) has been reached"
                "\n\nNote: Use `set_option maxHeartbeats <num>` to set the limit.\n")
        return [{"record": "link", "name": group[0]}]
    monkeypatch.setattr(simple, "run_simple_probe", fail)
    said = []
    recs, failed = simple.probe_modules(None, ["A.x", "A.y"], ["A"], [], log=said.append)
    assert said == ["lean: A could not be loaded in one session ((deterministic) timeout at "
                    "`transform`, maximum number of heartbeats (200000) has been reached); "
                    "splitting it"]
    assert [r["name"] for r in recs] == ["A.x", "A.y"] and not failed
