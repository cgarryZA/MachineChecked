"""`build --reuse-lean` reuses the probe records of the newest stored release made from the same
Lean inputs, by the same probe, with the same probe settings and read by the same version of
MachineChecked, whichever releases came after it, and gives the statuses and site data of a
fresh build. With no such release it refuses, and says which condition the closest release fails
(#309, #356)."""

import json
import re

import pytest

from conftest import build, edit, needs_lean, needs_tex
from prooflens import cli, config as cfgmod, evidence as ev, pipeline

OTHER_PROBE = "0" * 64


def latest(cfg):
    return json.loads(ev.releases(cfg.out_dir)[-1].read_text())["release"]


def reuse(toy):
    """A build from stored probe records: its index, evidence body, and log."""
    said = []
    res = pipeline.build(cfgmod.load(toy / "machinechecked.toml"), reuse_lean=True,
                         log=said.append)
    return res["index"], ev.load(res["site"].parent, res["evidence"])["body"], said


def site_data(cfg, index):
    """The preview site's data of the build whose manifest index is `index`, with its release's
    own names in placeholders and without its comparison with the releases before it: these
    differ between any two builds."""
    data = cfg.out_dir / "site" / "data"
    out = {}
    for p in sorted(data.rglob("*.json")):
        if p.name in ("changes.json", "review-queue.json"):
            continue
        d = json.loads(p.read_text().replace(index["release"], "RELEASE")
                       .replace(index["evidence"], "EVIDENCE"))
        if p == data / "index.json":
            for k in ("created", "changes"):
                d.pop(k, None)
        out[str(p.relative_to(data))] = d
    return out


def statuses(index):
    return {c["id"]: c["status"] for c in index["claims"]}


@needs_lean
@needs_tex
def test_reuse_finds_the_matching_release_after_another_probe(toy, monkeypatch, capsys):
    """Probe P1, then P2, then P1 again: the third build reproduces the first evidence record, so
    it names no new release and the latest release is P2's. Reuse with P1 takes the first
    release's records, and gives what the fresh build gave."""
    first, body1, cfg = build(toy)
    p1 = pipeline.probe_digest()
    monkeypatch.setattr(pipeline, "probe_digest", lambda: OTHER_PROBE)
    second, body2, _ = build(toy)
    assert body2["provenance"]["probe_sha256"] == OTHER_PROBE
    monkeypatch.setattr(pipeline, "probe_digest", lambda: p1)
    third, _, _ = build(toy)
    assert third["evidence"] == first["evidence"] and third["release"] == first["release"]
    assert latest(cfg) == second["release"]
    fresh = site_data(cfg, third)

    index, body, said = reuse(toy)
    assert any(f"reusing the probe records of release {first['release']}" in m for m in said)
    assert body["provenance"]["lean_reused"] and body["provenance"]["probe_sha256"] == p1
    assert body["lean"] == body1["lean"]
    assert body["assessment"] == body1["assessment"]
    assert statuses(index) == statuses(first)
    assert site_data(cfg, index) == fresh

    # With P2, the records of P2's own release are reused.
    monkeypatch.setattr(pipeline, "probe_digest", lambda: OTHER_PROBE)
    _, _, said = reuse(toy)
    assert any(f"reusing the probe records of release {second['release']}" in m for m in said)

    # A probe no stored release was made with is refused, with the probe named.
    monkeypatch.setattr(pipeline, "probe_digest", lambda: "1" * 64)
    with pytest.raises(pipeline.StaleEvidence, match="the Lean probe changed"):
        reuse(toy)
    monkeypatch.chdir(toy)
    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--reuse-lean"])
    assert e.value.code == 2
    assert capsys.readouterr().err.strip().splitlines() == [
        "machinechecked: the Lean probe changed since the stored Lean results; run "
        "`machinechecked build` without `--reuse-lean`"]


@needs_lean
@needs_tex
def test_reuse_requires_the_same_probe_settings(toy):
    """The probe's records depend on the allowed axioms, the layer prefixes, the scope roots and
    the modules: records made under other settings are not reused, and records made under the
    current ones are, however old."""
    first, _, cfg = build(toy)
    axioms = 'allowed_axioms = ["propext", "Classical.choice", "Quot.sound"]'
    edit(toy / "machinechecked.toml", axioms, 'allowed_axioms = ["propext", "Quot.sound"]')
    with pytest.raises(pipeline.StaleEvidence, match=r"the probe's settings \(`modules`, "
                       r"`scope_roots`, `spec_prefix`, `accept_prefix` or `allowed_axioms` in the "
                       r"configuration\) changed since the stored Lean results; run "):
        reuse(toy)
    second, _, _ = build(toy)
    assert second["release"] != first["release"]
    _, _, said = reuse(toy)
    assert any(f"release {second['release']}" in m for m in said)
    edit(toy / "machinechecked.toml", 'allowed_axioms = ["propext", "Quot.sound"]', axioms)
    index, _, said = reuse(toy)
    assert any(f"release {first['release']}" in m for m in said)
    assert statuses(index) == statuses(first)


def test_the_closest_release_names_the_refusal(toy):
    """Over stored records alone (no Lean): the newest release that qualifies is reused, past
    newer ones that differ or do not answer every request; with none, the refusal names the
    condition that the release which came closest fails."""
    cfg = cfgmod.load(toy / "machinechecked.toml")
    want = (pipeline.lean_inputs_digest(cfg), pipeline.probe_digest(),
            pipeline.probe_settings_digest(cfg), pipeline.records_engine())
    requests = [{"kind": "spec", "name": "Toy.PaperSpec.thm_even_add"}]
    answers = {"specs": {"Toy.PaperSpec.thm_even_add": {}}, "defs": {}, "proofs": {}}
    made = []

    def store(name, inputs, probe, settings, engine=want[3], lean=answers):
        eid = ev.store(cfg.out_dir, {
            "provenance": {"tool": {}, "project": {}, "papers": {}, "lean_inputs_sha256": inputs,
                           "probe_sha256": probe, "probe_settings_sha256": settings,
                           "lean_records_engine": engine},
            "inventory": {"claims": []}, "reviews": {"files": {}, "records": []}, "tex": {},
            "lean": lean, "assessment": {"claims": [], "findings": [], "release": name}})
        ev.record_release(cfg.out_dir, name, eid)
        made.append(name)
        path = cfg.out_dir / "releases" / f"{name}.json"
        path.write_text(json.dumps({**json.loads(path.read_text()),
                                    "created": f"2026-01-01T00:00:{len(made):02d}+00:00"}))

    def outcome():
        try:
            return pipeline.reusable_lean(cfg, requests)[0]
        except pipeline.StaleEvidence as e:
            return str(e).removesuffix("; " + pipeline.RUN_PROBE)

    assert outcome() == "no stored Lean results to reuse"
    store("other-inputs", "1" * 64, want[1], want[2])
    assert outcome() == ("Lean inputs changed since the stored Lean results (here or in a path "
                         "dependency)")
    store("other-probe", want[0], OTHER_PROBE, want[2])
    assert outcome() == "the Lean probe changed since the stored Lean results"
    store("other-settings", want[0], want[1], "2" * 64)
    store("newer-other-probe", want[0], OTHER_PROBE, want[2])
    assert outcome().startswith("the probe's settings (`modules`, ")
    store("no-engine", *want[:3], None)
    assert outcome() == ("the stored Lean results do not record the version of MachineChecked "
                         "that read them (an earlier version stored them)")
    store("other-engine", *want[:3], {**want[3], "version": "0.0.1"})
    fp, version = want[3]["fingerprint"], want[3]["version"]
    assert outcome() == ("the stored Lean results were read by another version of MachineChecked "
                         f"(0.0.1, fingerprints {fp}; this is {version}, fingerprints {fp})")
    store("answers", *want)
    store("answers-less", *want, lean={"specs": {}, "defs": {}, "proofs": {}})
    store("no-settings", want[0], want[1], None)
    store("other-fingerprints", *want[:3], {**want[3], "fingerprint": "pl-fp-v0"})
    assert outcome() == "answers"
    (cfg.out_dir / "releases" / "answers.json").unlink()
    assert outcome() == "the stored Lean results do not cover Toy.PaperSpec.thm_even_add"


@needs_lean
@needs_tex
def test_records_without_probe_settings_are_not_reused(toy):
    """An evidence record stored before the probe settings were recorded does not say what the
    probe was told, so its records are not reused."""
    first, body, cfg = build(toy)
    body["provenance"].pop("probe_settings_sha256")
    eid = ev.store(cfg.out_dir, body)
    (cfg.out_dir / "releases" / f"{first['release']}.json").unlink()
    ev.record_release(cfg.out_dir, "earlier", eid)
    with pytest.raises(pipeline.StaleEvidence, match="the stored Lean results do not record the "
                       r"probe's settings \(an earlier version of MachineChecked stored them\)"):
        reuse(toy)


@needs_lean
def test_records_probed_without_building_are_not_reused(toy, monkeypatch, capsys):
    """`build --no-lean-build` probes the build files as they are, which may be older than the
    sources. It records no digest of the Lean inputs, so `--reuse-lean` never takes its records
    for those of the current sources: a proof edited since the last `lake build` does not read
    as checked (#355)."""
    monkeypatch.chdir(toy)
    cfg = cfgmod.load(toy / "machinechecked.toml")

    def reuse_without_tex():
        said = []
        res = pipeline.build(cfg, skip_tex=True, reuse_lean=True, log=said.append)
        return res["index"], ev.load(cfg.out_dir, res["evidence"])["body"], said

    def made(*args):
        """The release a build on the command line names, and its evidence."""
        before = set(ev.releases(cfg.out_dir))
        cli.main(["build", "--skip-tex", *args])
        (new,) = set(ev.releases(cfg.out_dir)) - before
        named = json.loads(new.read_text())
        return named["release"], ev.load(cfg.out_dir, named["evidence"])["body"]

    first, built = made()
    assert built["provenance"]["lean_inputs_sha256"] == pipeline.lean_inputs_digest(cfg)
    edit(toy / "lean/Toy/Acceptance.lean",
         "  rintro a b ⟨j, rfl⟩ ⟨k, rfl⟩\n  exact ⟨j + k, by omega⟩", "  sorry")
    _, stale = made("--no-lean-build")
    # The probe read the build files of the earlier proof, so the record describes that proof.
    proof = "accept:Toy.Acceptance.thm_even_add:Toy.PaperSpec.thm_even_add"
    assert stale["lean"]["proofs"][proof] == built["lean"]["proofs"][proof]
    assert stale["provenance"]["lean_inputs_sha256"] is None

    capsys.readouterr()
    with pytest.raises(SystemExit) as e:
        cli.main(["build", "--skip-tex", "--reuse-lean"])
    assert e.value.code == 2
    assert capsys.readouterr().err.strip().splitlines() == [
        "machinechecked: Lean inputs changed since the stored Lean results (here or in a path "
        "dependency); run `machinechecked build` without `--reuse-lean`"]
    # With only the records probed without building, the refusal says why they are not reused.
    (cfg.out_dir / "releases" / f"{first}.json").unlink()
    with pytest.raises(pipeline.StaleEvidence, match=r"^the stored Lean results do not record "
                       r"their Lean inputs \(a build with `--no-lean-build` records none: its "
                       r"build files may be older than the sources\); run "):
        reuse_without_tex()

    # A build that builds the project is reused, and gives the edited proof's result.
    fresh, fresh_body, _ = build(toy, skip_tex=True)
    assert fresh_body["lean"]["proofs"][proof] != built["lean"]["proofs"][proof]
    index, body, said = reuse_without_tex()
    assert any(f"reusing the probe records of release {fresh['release']}" in m for m in said)
    assert body["lean"]["proofs"][proof] == fresh_body["lean"]["proofs"][proof]
    assert statuses(index) == statuses(fresh)


@needs_lean
def test_reuse_requires_the_engine_that_read_the_records(toy, monkeypatch):
    """The Lean records are this engine's reading of the probe's output (`probe.parse_records`,
    `merge_records`, `attach_sources`, the fingerprints). Records read by another version of
    MachineChecked, or under other fingerprints, are not reused, even after that version
    reassesses them; nor is a record that does not say which version read it (#356)."""
    first, body, cfg = build(toy, skip_tex=True)
    engine = pipeline.records_engine()
    assert body["provenance"]["lean_records_engine"] == engine

    def reuse_without_tex():
        said = []
        res = pipeline.build(cfg, skip_tex=True, reuse_lean=True, log=said.append)
        return res["index"], ev.load(cfg.out_dir, res["evidence"])["body"], said

    index, reused, _ = reuse_without_tex()
    assert reused["lean"] == body["lean"] and statuses(index) == statuses(first)
    assert reused["provenance"]["lean_records_engine"] == engine

    other = re.escape(f"read by another version of MachineChecked ({engine['version']}, "
                      f"fingerprints {engine['fingerprint']}; this is 999.0, fingerprints "
                      f"{engine['fingerprint']})")
    monkeypatch.setattr(pipeline, "tool_version", lambda: "999.0")
    with pytest.raises(pipeline.StaleEvidence, match=other):
        reuse_without_tex()
    # A reassessment carries the Lean records unchanged, so it keeps the engine that read them.
    rel = pipeline.reassess(cfg, log=lambda *a: None)["release"]
    named = json.loads((cfg.out_dir / "releases" / f"{rel}.json").read_text())
    again = ev.load(cfg.out_dir, named["evidence"])["body"]["provenance"]
    assert again["tool"]["version"] == "999.0" and again["lean_records_engine"] == engine
    with pytest.raises(pipeline.StaleEvidence, match=other):
        reuse_without_tex()
    monkeypatch.undo()
    monkeypatch.setattr(pipeline, "FINGERPRINT_VERSION", "pl-fp-v0")
    with pytest.raises(pipeline.StaleEvidence, match="read by another version of MachineChecked"):
        reuse_without_tex()
    monkeypatch.undo()
    _, _, said = reuse_without_tex()
    assert any("reusing the probe records of release" in m for m in said)

    # A record stored before the engine was recorded is not reused.
    body["provenance"].pop("lean_records_engine")
    eid = ev.store(cfg.out_dir, body)
    for rel in ev.releases(cfg.out_dir):
        rel.unlink()
    ev.record_release(cfg.out_dir, "earlier", eid)
    with pytest.raises(pipeline.StaleEvidence, match="the stored Lean results do not record the "
                       r"version of MachineChecked that read them \(an earlier version stored "
                       r"them\)"):
        reuse_without_tex()


def test_the_work_directory_is_not_a_lean_input(tmp_path):
    """A probe stopped mid-run leaves its Probe.lean in the work directory; that file is no Lean
    input of the project, so it leaves the Lean-inputs digest, and with it `--reuse-lean`, alone.
    The work directory is left out under any of its names, and when configured elsewhere."""
    import types
    root = tmp_path / "lean"
    (root / "Syn").mkdir(parents=True)
    (root / "lakefile.toml").write_text('name = "syn"\n[[lean_lib]]\nname = "Syn"\n')
    (root / "Syn" / "Main.lean").write_text("theorem t : True := trivial\n")
    work = root / "audit-work"
    cfg = types.SimpleNamespace(lean_root=root, out_dir=work)
    before = pipeline.lean_inputs_digest(cfg)
    for folder in (".machinechecked", ".prooflens", "audit-work"):
        left = root / folder / "build" / "prooflens-probe-x" / "Probe.lean"
        left.parent.mkdir(parents=True)
        left.write_text("theorem probe : True := trivial\n")
        assert pipeline.lean_inputs_digest(cfg) == before, folder
    (root / "Syn" / "Extra.lean").write_text("theorem u : True := trivial\n")
    assert pipeline.lean_inputs_digest(cfg) != before, "a real Lean input still counts"
    # A work directory that is the project itself does not leave the project out: there the
    # files under audit-work count again, as any other folder's would.
    same = types.SimpleNamespace(lean_root=root, out_dir=root)
    assert pipeline.lean_inputs_digest(same) != pipeline.lean_inputs_digest(cfg)
    empty = types.SimpleNamespace(lean_root=tmp_path / "none", out_dir=None)
    (tmp_path / "none").mkdir()
    assert pipeline.lean_inputs_digest(same) != pipeline.lean_inputs_digest(empty)
