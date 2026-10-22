"""#216: the statement layer and the proof layer may each span several namespace prefixes. A
statement or a proof under any listed prefix is in its layer, and a statement module under any of
them that imports a proof module under any of them breaks the layering."""

import shutil
import subprocess

import pytest

from conftest import ROOT, needs_lean
from prooflens import config as cfgmod
from prooflens.probe import lean_session, parse_records

REQUESTS = [{"kind": "spec", "name": "Base.PaperSpec.one_eq"},
            {"kind": "spec", "name": "Ext.PaperSpec.two_eq"},
            {"kind": "accept", "name": "Base.Acceptance.one_eq", "spec": "Base.PaperSpec.one_eq"},
            {"kind": "accept", "name": "Ext.Acceptance.two_eq", "spec": "Ext.PaperSpec.two_eq"}]
MODULES = ["Base.PaperSpec", "Base.Acceptance", "Ext.PaperSpec", "Ext.Acceptance"]


@pytest.fixture(scope="module")
def layers(tmp_path_factory):
    root = tmp_path_factory.mktemp("layers") / "layers"
    shutil.copytree(ROOT / "tests" / "fixtures" / "layers", root)
    subprocess.run(["lake", "build"], cwd=root, check=True, capture_output=True, timeout=900)
    return root


def probe(root, modules, **prefixes):
    query = {"scope_roots": ["Base", "Ext"], "spec_prefix": "Base.PaperSpec",
             "accept_prefix": "Base.Acceptance", "allowed_axioms": [], "requests": REQUESTS,
             **prefixes}
    return lean_session(root, modules, query, parse_records)


def errors(res):
    recs = {**res["specs"], **{r["name"]: r for r in res["proofs"].values()}}
    return {n: r["errors"] for n, r in recs.items() if r["errors"]}


@needs_lean
def test_one_prefix_per_layer_leaves_the_other_library_outside(layers):
    res = probe(layers, MODULES)
    assert errors(res) == {"Ext.PaperSpec.two_eq": ["outside-spec-layer"],
                           "Ext.Acceptance.two_eq": ["outside-accept-layer"]}
    assert res["layering"] == []


@needs_lean
def test_every_listed_prefix_is_in_its_layer(layers):
    lists = {"spec_prefixes": ["Base.PaperSpec", "Ext.PaperSpec"],
             "accept_prefixes": ["Base.Acceptance", "Ext.Acceptance"]}
    res = probe(layers, MODULES, **lists)
    assert errors(res) == {} and res["layering"] == []
    # A statement module under the second prefix that imports a proof module under the first.
    res = probe(layers, MODULES + ["Ext.PaperSpec.Leak"], **lists)
    assert res["layering"] == [{"module": "Ext.PaperSpec.Leak", "imports": "Base.Acceptance"}]


BASE = ('[project]\nname = "t"\nmodules = []\nscope_roots = []\ninventory = "claims.json"\n'
        'accept_prefix = "A"\n')


def test_a_layer_is_one_prefix_or_a_list_of_them(tmp_path):
    path = tmp_path / "machinechecked.toml"
    path.write_text(BASE + 'spec_prefix = "S"\n')
    cfg = cfgmod.load(path)
    assert (cfg.spec_prefix, cfg.spec_prefixes) == ("S", ["S"])
    assert (cfg.accept_prefix, cfg.accept_prefixes) == ("A", ["A"])
    path.write_text(BASE + 'spec_prefix = ["S", "T.Spec"]\n')
    cfg = cfgmod.load(path)
    assert (cfg.spec_prefix, cfg.spec_prefixes) == ("S", ["S", "T.Spec"])
    for bad in ("[]", "[1]", "3"):
        path.write_text(BASE + f"spec_prefix = {bad}\n")
        with pytest.raises(cfgmod.ConfigError, match="string or a non-empty list"):
            cfgmod.load(path)
