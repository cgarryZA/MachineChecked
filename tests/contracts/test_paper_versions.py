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


def test_a_paper_page_offers_its_versions_with_their_own_labels(tmp_path):
    """#121: the site gives a page every version of its paper; the page labels each from its kind
    and identifier, offers only addresses on the site, and shows only audits of its version."""
    from published_fixture import REPO, snapshot
    from prooflens.paper import apply_audits, page_versions, write_paper_site
    later = "abc1234" + "0" * 33
    entries = [{"id": "arxiv:2601.01234v1", "kind": "published", "href": "/papers/2601.01234/v1/",
                "pdf": "https://arxiv.org/pdf/2601.01234v1", "label": "anything",
                "audits": [{"url": BASE, "author": "A. Author", "repository": REPO},
                           {"url": "javascript:alert(1)"}]},
               {"id": "manuscript:abc1234", "kind": "manuscript", "revision": later,
                "href": "../latest/", "label": "arXiv v2"}]
    out = page_versions(entries, "manuscript:abc1234")
    assert [v["label"] for v in out] == ["arXiv v1", "Latest manuscript (commit abc1234)"]
    assert out[0]["audits"] == [{"url": BASE, "author": "A. Author", "repository": REPO}]
    for bad in ("https://elsewhere.example/v1/", "//elsewhere.example/", "javascript:x", ""):
        with pytest.raises(ValueError, match="href"):
            page_versions([{**entries[0], "href": bad}], entries[0]["id"])
    with pytest.raises(ValueError, match="include this page's"):
        page_versions(entries, "arxiv:2601.01234v2")
    with pytest.raises(ValueError, match="Invalid manuscript version"):
        page_versions([{**entries[1], "id": "manuscript:v2"}], "manuscript:v2")

    d = files()
    for part in (d["audit.json"]["papers"][0], d["data/index.json"]["papers"][0]):
        part["paper_version"] = versions.published_version("arXiv:2601.01234v1")
    audit = load_published_audit(PAPER, PAPER["formalisations"][0], {"url": BASE}, fetcher(d))
    claims = [{"key": "theorem-1", "number": "Theorem 1", "kind": "theorem", "links": [],
               "anchor": None}]
    apply_audits(claims, {REPO: audit})
    index = write_paper_site(tmp_path / "v1", PAPER, claims, None, None, audits={REPO: audit},
                             versions=entries, version="arxiv:2601.01234v1")
    assert index["version"] == "arxiv:2601.01234v1" and len(index["versions"]) == 2
    assert index["audits"][REPO]["paper_version"]["label"] == "arXiv v1"
    with pytest.raises(ValueError, match="does not pin manuscript:abc1234"):
        write_paper_site(tmp_path / "latest", PAPER, claims, None, None, audits={REPO: audit},
                         versions=entries, version="manuscript:abc1234")


def test_a_claim_map_relates_the_claims_of_two_versions_and_changes_no_status(tmp_path):
    """#225: the map of a paper's claims between two versions, computed from their inventories
    (by label, else by statement text) or given by a listing, is written into each version's page
    on the claims it names; the statuses are those of the pages written without it."""
    from prooflens.paper import check_claim_map, claim_map, paper_claims, write_paper_site
    v1, latest = "arxiv:2601.01234v1", "manuscript:abc1234"
    entries = [{"id": v1, "kind": "published", "href": "/v1/"},
               {"id": latest, "kind": "manuscript", "revision": "abc1234" + "0" * 33,
                "href": "/latest/"}]

    def inv(*rows):
        return [{"key": k, "number": n, "label": l, "statement": t} for k, n, l, t in rows]
    m = claim_map(v1, inv(("theorem-1", "Theorem 1", "thm:a", "A bound."),
                          ("theorem-2", "Theorem 2", None, "An  identity."),
                          ("theorem-3", "Theorem 3", "rem:old", "A remark."),
                          ("theorem-4", "Theorem 4", None, None)),
                  latest, inv(("lemma-1", "Lemma 1", None, "An identity."),
                              ("theorem-2", "Theorem 2", "thm:new", "Another."),
                              ("theorem-3", "Theorem 3", "thm:a", "A sharper bound.")))
    assert [(e["change"], [r["key"] for r in e["from"]], [r["key"] for r in e["to"]])
            for e in m["claims"]] == [("changed", ["theorem-1"], ["theorem-3"]),
                                      ("renumbered", ["theorem-2"], ["lemma-1"]),
                                      ("removed", ["theorem-3"], []),
                                      ("new", [], ["theorem-2"])]
    # A listing states a split; a change that does not fit its claims is refused.
    split = {"from": [{"key": "theorem-4", "number": "Theorem 4"}],
             "to": [{"key": "lemma-2", "number": "Lemma 2"}, {"key": "lemma-3", "number": "Lemma 3"}],
             "change": "split"}
    listed = check_claim_map({**m, "claims": m["claims"] + [split]})
    for bad in ({**split, "change": "same"}, {**split, "change": "moved"},
                {**split, "to": [{"key": "a b", "number": "Lemma 2"}]}):
        with pytest.raises(ValueError, match="claim map"):
            check_claim_map({**m, "claims": [bad]})

    def page(version, keys, maps):
        anchors = [{"env": k.split("-")[0], "number": k.split("-")[1], "page": 1} for k in keys]
        claims = paper_claims(anchors, "T", [])
        return write_paper_site(tmp_path / version.split(":")[0], {"title": "T"}, claims, None,
                                None, versions=entries, version=version, claim_maps=maps)
    one = page(v1, ["theorem-1", "theorem-2", "theorem-3", "theorem-4", "theorem-5"], [listed])
    two = page(latest, ["lemma-1", "lemma-2", "lemma-3", "theorem-2", "theorem-3"], [listed])
    by = {c["id"]: c.get("counterparts") for c in one["claims"]}
    assert by["P:theorem-1"] == [{"version": latest, "later": True, "change": "changed",
                                  "claims": [{"id": "P:theorem-3", "number": "Theorem 3"}]}]
    assert by["P:theorem-3"] == [{"version": latest, "later": True, "change": "removed",
                                  "claims": []}]
    assert [c["id"] for c in by["P:theorem-4"][0]["claims"]] == ["P:lemma-2", "P:lemma-3"]
    assert by["P:theorem-5"] is None  # a claim the map does not name shows nothing
    by = {c["id"]: c.get("counterparts") for c in two["claims"]}
    assert by["P:theorem-2"] == [{"version": v1, "later": False, "change": "new", "claims": []}]
    assert by["P:lemma-3"][0]["claims"] == [{"id": "P:theorem-4", "number": "Theorem 4"}]
    stored = json.loads((tmp_path / "manuscript" / "data" / "index.json").read_text())
    assert [c.get("counterparts") for c in stored["claims"]] == [c.get("counterparts")
                                                                for c in two["claims"]]
    plain = page(latest, ["lemma-1", "lemma-2", "lemma-3", "theorem-2", "theorem-3"], None)
    assert [(c["status_code"], c["status"]) for c in plain["claims"]] == \
        [(c["status_code"], c["status"]) for c in two["claims"]]
    # A map of versions the page does not offer is not written.
    assert not any(c.get("counterparts") for c in page(
        latest, ["theorem-2"], [{**listed, "from": "arxiv:2601.01234v2"}])["claims"])
    with pytest.raises(ValueError, match="relate versions"):
        write_paper_site(tmp_path / "x", {"title": "T"}, [], None, None, claim_maps=[listed])


def test_a_claim_map_calls_a_claim_removed_or_new_only_when_it_has_no_counterpart():
    """#296: a claim whose counterpart has no statement text, an unlabelled claim whose statement
    was edited, and a statement that only gains or renames a `\\label` keep their counterpart; a
    claim is removed (or new) only when the other version certainly has none."""
    from prooflens.paper import claim_map
    v1, v2 = "arxiv:2601.01234v1", "arxiv:2601.01234v2"

    def inv(*rows):
        return [{"key": k, "number": n, "label": l, "statement": t} for k, n, l, t in rows]

    def changes(earlier, later):
        return [(e["change"], [r["key"] for r in e["from"]], [r["key"] for r in e["to"]])
                for e in claim_map(v1, earlier, v2, later)["claims"]]

    # The counterpart has no statement text: nothing says whether the claim changed, and it is
    # not removed (nor new, the other way), whether the counterpart has its label or none.
    bound = inv(("theorem-1", "Theorem 1", "thm:a", "A bound."))
    for other in (inv(("theorem-1", "Theorem 1", "thm:a", None)),
                  inv(("theorem-1", "Theorem 1", None, ""))):
        assert changes(bound, other) == [] and changes(other, bound) == []

    # An unlabelled claim whose statement was edited is its own counterpart, changed.
    assert changes(inv(("remark-1", "Remark 1", None, "A remark."),
                       ("eq-1", "(1)", None, "\\begin{equation}\n  a = b\n\\end{equation}")),
                   inv(("remark-1", "Remark 1", None, "A remark, edited."),
                       ("eq-1", "(1)", None, "\\begin{equation}\n  a = c\n\\end{equation}"))) \
        == [("changed", ["remark-1"], ["remark-1"]), ("changed", ["eq-1"], ["eq-1"])]

    # A `\label` is not printed: a statement that only gains or renames one is the same text.
    assert changes(
        inv(("eq-2", "(2)", None, "\\begin{equation}\n  x \\le y\n\\end{equation}"),
            ("eq-3", "(3)", "eq:old", "\\begin{equation}\\label{eq:old}\n  y \\le z\n\\end{equation}")),
        inv(("eq-2", "(2)", "eq:two", "\\begin{equation}\\label{eq:two}\n  x \\le y\n\\end{equation}"),
            ("eq-4", "(4)", "eq:new", "\\begin{equation}\\label {eq:new}  y \\le z\n\\end{equation}"))) \
        == [("same", ["eq-2"], ["eq-2"]), ("renumbered", ["eq-3"], ["eq-4"])]

    # Removed and new when certain: the claim has a label the other version does not give, and
    # every claim there under its number has a statement and a counterpart.
    earlier = inv(("lemma-1", "Lemma 1", "lem:gone", "Gone."),
                  ("lemma-2", "Lemma 2", "lem:kept", "Kept."))
    later = inv(("lemma-1", "Lemma 1", "lem:kept", "Kept."))
    assert changes(earlier, later) == [("removed", ["lemma-1"], []),
                                       ("renumbered", ["lemma-2"], ["lemma-1"])]
    assert changes(later, earlier) == [("renumbered", ["lemma-1"], ["lemma-2"]),
                                       ("new", [], ["lemma-1"])]
    # Without a label, its counterpart may be an edited claim under another number.
    unlabelled = inv(("lemma-1", "Lemma 1", None, "Gone."), ("lemma-2", "Lemma 2", "lem:kept", "Kept."))
    assert changes(unlabelled, later) == [("renumbered", ["lemma-2"], ["lemma-1"])]
    # A claim of the other version under its number that is unmatched (here: its label is given
    # to two claims, so it matches neither) may be its counterpart.
    assert changes(inv(("lemma-1", "Lemma 1", "lem:gone", "Gone."),
                       ("lemma-2", "Lemma 2", "lem:dup", "Two."),
                       ("lemma-3", "Lemma 3", "lem:dup", "Three.")),
                   inv(("lemma-1", "Lemma 1", "lem:dup", "One."))) == []
