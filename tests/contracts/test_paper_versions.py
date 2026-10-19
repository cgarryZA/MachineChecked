"""#119: an audit pins one version of its paper, published (arXiv vN) or an unpublished manuscript
at a commit; its descriptor says which, and an inventory pinned to another version is refused."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import build, edit, needs_lean, needs_tex
from published_fixture import PAPER, files, fetcher, BASE
from prooflens import cli, versions
from prooflens.published import AuditError, load_published_audit

V1 = "2601.01234v1"
LATER = "1234567" + "8" * 33


def paper(**kw):
    src = kw.pop("source", {"git": "paper", "rev": "x"})
    return SimpleNamespace(**{"id": "T", "version": None, "published": None, "source": src,
                              **kw})


def snap(kind="git", revision=LATER):
    return SimpleNamespace(kind=kind, revision=revision)


def inventory(pin=None, claim_pin=None):
    claims = [{"id": "T:a", "paper": "T"}, {"id": "T:b", "paper": "T",
                                            **({"commit": claim_pin} if claim_pin else {})}]
    return {"papers": {"T": {"commit": pin}} if pin else {}, "claims": claims}


def pinned(p, s, inv):
    rec, declared = versions.declared(p, s, Path("/nonexistent"))
    return versions.check(p, rec, declared, inv)


def test_a_published_version_is_named_by_its_identifier():
    p = paper(published=f"arXiv:{V1}")
    rec = pinned(p, snap(), inventory(V1, claim_pin=f"arXiv:{V1}"))
    assert (rec["kind"], rec["id"], rec["label"]) == ("published", f"arxiv:{V1}", "arXiv v1")
    # The inventory frozen at a later manuscript commit is not arXiv v1.
    with pytest.raises(versions.VersionError, match=r"arXiv v1.*commit 1234567 \(2 claims"):
        pinned(p, snap(), inventory(LATER[:7]))
    with pytest.raises(versions.VersionError, match="2601.01234v2"):
        pinned(p, snap(), inventory(V1, claim_pin="2601.01234v2"))
    # An arXiv source pins its own version.
    rec = pinned(paper(source={"arxiv": V1}), snap("arxiv", V1), inventory(V1))
    assert rec["label"] == "arXiv v1"
    with pytest.raises(versions.VersionError, match="the source is arXiv"):
        pinned(paper(source={"arxiv": V1}, published="arXiv:2601.01234v2"), snap("arxiv", V1),
               inventory())


def test_an_unpublished_manuscript_is_named_by_its_commit_and_never_numbered():
    p = paper(version="manuscript", published=f"arXiv:{V1}")
    rec = pinned(p, snap(), inventory(LATER[:7]))
    assert rec == {"kind": "manuscript", "id": "manuscript:1234567", "revision": LATER,
                   "label": "Latest manuscript (commit 1234567)", "checked": True}
    with pytest.raises(versions.VersionError, match="pinned to 2601.01234v1"):
        pinned(p, snap(), inventory(V1))
    with pytest.raises(versions.VersionError, match="pinned to commit abcdef0"):
        pinned(p, snap(), inventory(LATER, claim_pin="abcdef0"))
    with pytest.raises(versions.VersionError, match="needs `published`"):
        pinned(paper(version="published"), snap(), inventory())
    with pytest.raises(versions.VersionError, match="give the source a `rev`"):
        pinned(paper(version="manuscript", source={"path": "p"}), snap("path", None), inventory())


def test_an_undeclared_version_the_pins_disagree_with_is_not_claimed():
    assert pinned(paper(), snap(), inventory(LATER[:7]))["id"] == "manuscript:1234567"
    assert pinned(paper(), snap(), inventory(V1)) is None
    # Nothing pinned: nothing disagrees.
    assert pinned(paper(published=f"arXiv:{V1}"), snap(), inventory())["label"] == "arXiv v1"


def test_a_version_is_checked_only_when_every_claim_is_pinned_to_it():
    declared = paper(published=f"arXiv:{V1}")
    assert pinned(declared, snap(), inventory(V1))["checked"] is True
    assert pinned(declared, snap(), inventory(claim_pin=V1))["checked"] is False
    assert pinned(declared, snap(), inventory())["checked"] is False
    assert pinned(declared, snap(), {"claims": []})["checked"] is False


def test_a_site_reads_the_pinned_version_and_never_the_audits_own_label():
    d = files()
    rec = versions.manuscript_record("d" * 40)
    for part in (d["audit.json"]["papers"][0], d["data/index.json"]["papers"][0]):
        part["paper_version"] = {**rec, "label": "arXiv v3"}
    load = lambda listing: load_published_audit(PAPER, PAPER["formalisations"][0],
                                                {"url": BASE, **listing}, fetcher(d))
    # An audit that does not say its version was checked is read as unchecked.
    assert load({})["paper_version"] == {**rec, "checked": False}
    for part in (d["audit.json"]["papers"][0], d["data/index.json"]["papers"][0]):
        part["paper_version"] = {**rec, "label": "arXiv v3", "checked": True}
    assert load({})["paper_version"] == {**rec, "checked": True}
    assert load({"version": "manuscript:" + "d" * 12})["paper_version"]["label"] == \
        "Latest manuscript (commit ddddddd)"
    with pytest.raises(AuditError, match="another version"):
        load({"version": f"arxiv:{V1}"})
    d["data/index.json"]["papers"][0]["paper_version"] = versions.manuscript_record("e" * 40)
    with pytest.raises(AuditError, match="different paper versions"):
        load({})
    d["audit.json"]["papers"][0]["paper_version"] = {"kind": "manuscript", "id": "v2",
                                                     "revision": "d" * 40}
    with pytest.raises(AuditError, match="Invalid manuscript version"):
        load({})


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@needs_lean
@needs_tex
def test_one_project_publishes_a_v1_audit_and_a_latest_manuscript_audit(toy, tmp_path,
                                                                         monkeypatch):
    """The toy's manuscript gets its own history: v1 (arXiv 2601.01234v1), then a later
    commit. One audit pins each; each descriptor names its version, and the statuses agree."""
    ms = toy / "paper"
    git(ms, "init", "-q")
    git(ms, "-c", "user.name=t", "-c", "user.email=t@example.org", "add", "-A")
    git(ms, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qm", "v1")
    v1 = git(ms, "rev-parse", "HEAD")
    with open(ms / "toy.tex", "a") as f:
        f.write("% a later revision of the manuscript\n")
    git(ms, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-qam", "later")
    later = git(ms, "rev-parse", "HEAD")
    cfg = (toy / "machinechecked.toml").read_text()
    inv = json.loads((toy / "claims.json").read_text())
    monkeypatch.chdir(toy)

    def audit(source, version, pin, site, *extra):
        (toy / "machinechecked.toml").write_text(cfg.replace(
            'source = { path = "paper" }', f"{source}\n{version}"))
        (toy / "claims.json").write_text(json.dumps({**inv, "papers": {"T": {"commit": pin}}}))
        cli.main(["build", "--site", str(tmp_path / "site" / site), *extra])
        return json.loads((tmp_path / "site" / site / "audit.json").read_text())["papers"][0]

    one = audit(f'source = {{ git = "paper", rev = "{v1}" }}', f'published = "arXiv:{V1}"', V1,
                "v1")
    latest = audit(f'source = {{ git = "paper", rev = "{later}" }}',
                   f'version = "manuscript"\npublished = "arXiv:{V1}"', later[:7], "latest",
                   "--reuse-lean")
    assert (one["id"], one["version"], one["revision"]) == ("arxiv:2601.01234", "v1", v1)
    assert one["paper_version"] == {"kind": "published", "id": f"arxiv:{V1}",
                                    "arxiv": "arxiv:2601.01234", "number": "v1",
                                    "label": "arXiv v1", "revision": v1,
                                    "checked": True}
    assert (latest["id"], latest["version"], latest["revision"]) == \
        ("arxiv:2601.01234", None, later)
    assert latest["paper_version"] == {**versions.manuscript_record(later), "checked": True}
    assert latest["paper_version"]["label"] == f"Latest manuscript (commit {later[:7]})"
    statuses = [[c["status_code"] for c in json.loads(
        (tmp_path / "site" / s / "data" / "index.json").read_text())["claims"]]
        for s in ("v1", "latest")]
    assert statuses[0] == statuses[1]


@needs_lean
@needs_tex
def test_a_version_the_inventory_does_not_pin_is_refused_before_lean_runs(toy, monkeypatch):
    from prooflens import pipeline
    monkeypatch.setattr(pipeline, "run_probe", lambda *a, **k: pytest.fail("Lean ran"))
    edit(toy / "machinechecked.toml", 'root = "toy.tex"\n',
         f'root = "toy.tex"\npublished = "arXiv:{V1}"\n')
    inv = json.loads((toy / "claims.json").read_text())
    inv["claims"][0]["commit"] = "abcdef0"
    (toy / "claims.json").write_text(json.dumps(inv))
    with pytest.raises(versions.VersionError, match="pins arXiv v1, but its inventory is pinned "
                                                    "to commit abcdef0"):
        build(toy)
