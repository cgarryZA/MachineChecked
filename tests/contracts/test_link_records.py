"""Links recorded from the command line and from the reader (#123) go through one check and one
write (`authoring.plan`, `authoring.write`): the claim and each declaration resolve against the
last build before anything is written, a refused request writes nothing, and both record the
same entry. test_workspace's synthetic build stands in for a real one, in a project whose Lean
is not built, so these tests run no Lean."""

import json
import threading

import pytest

from conftest import needs_tex
from test_workspace import _call, make_build

from prooflens import authoring, cli, simple
from prooflens.server import make_server
from prooflens.targets import Snapshot

PAPER = "paper.tex"


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """A project with the paper "Synthetic" and its last build: two modules declare `Ex.twin`,
    which Lemma 2.3 is suggested, and Theorem 1 shows, besides `Ex.main`, a link Lean found
    outside the project."""
    root = tmp_path / "proj"
    root.mkdir()
    (root / "lakefile.toml").write_text('name = "ex"\n[[lean_lib]]\nname = "Ex"\n')
    (root / PAPER).write_text("\\documentclass{article}\n\\title{Synthetic}\n"
                              "\\begin{document}\n\\end{document}\n")
    data = root / ".machinechecked" / "site" / "data"
    make_build(root / ".machinechecked")
    idx = json.loads((data / "lean-index.json").read_text())
    idx += [{"name": "Ex.twin", "kind": "theorem", "module": m} for m in ("Ex.A", "Ex.B")]
    (data / "lean-index.json").write_text(json.dumps(idx))
    main = data / "claims" / "thm_main.json"
    ch = json.loads(main.read_text())
    ch["links"].append({"name": "Nat.le_refl", "module": "Init.Prelude",
                        "status_code": "link.checked"})
    main.write_text(json.dumps(ch))
    bound = data / "claims" / "lem_bound.json"
    ch = json.loads(bound.read_text())
    ch["suggestions"] = [{"name": "Ex.twin", "status_code": "link.suggested"}]
    bound.write_text(json.dumps(ch))
    monkeypatch.chdir(root)
    return root


def link(capsys, *args):
    """Run `link --json`; return its exit code and document."""
    try:
        cli.main(["link", *args, "--json"])
        code = 0
    except SystemExit as e:
        code = e.code
    return code, json.loads(capsys.readouterr().out)


def entry(root, key):
    e = dict(simple.load_links(root)["papers"].get(PAPER, {}).get(key) or {})
    e.pop("at", None)
    return e


@pytest.fixture
def reader(proj):
    """POST to `/api/link` of a local server answering as `machinechecked view`'s does."""
    data = proj / ".machinechecked" / "site" / "data"

    def on_link(req):
        ch = authoring.from_reader(proj, PAPER, Snapshot(data), req)
        return {"claim": ch["claim"], "changed": ch["changed"]}

    httpd = make_server(data.parent, 0, on_link)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield lambda req: _call(f"http://127.0.0.1:{httpd.server_address[1]}/api/link", req)
    httpd.shutdown()


@needs_tex
def test_the_command_line_and_the_reader_record_the_same_entries(proj, reader, capsys):
    links = simple.links_file(proj)
    cases = [
        (["Lemma 2.3", "Ex.inverse_bound", "Ex.inverse_solves", "--as", "A. Auditor"],
         {"key": "lem:bound", "lean": ["Ex.inverse_bound", "Ex.inverse_solves"],
          "by": "A. Auditor"}),
        (["Theorem 1", "--reject", "Ex.tri"], {"key": "thm:main", "reject": ["Ex.tri"]}),
        # A suggestion is declined by its name, whichever module declares it.
        (["Lemma 2.3", "--reject", "Ex.twin"], {"key": "lem:bound", "reject": ["Ex.twin"]}),
        (["P:thm:main", "Nat.le_refl"], {"key": "thm:main", "lean": ["Nat.le_refl"]}),
    ]
    for args, req in cases:
        links.unlink(missing_ok=True)
        code, out = link(capsys, *args)
        assert code == 0 and out["written"], out
        by_cli = entry(proj, req["key"])
        links.unlink()
        code, ack = reader(req)
        assert code == 200 and ack["changed"]
        assert entry(proj, req["key"]) == by_cli, args
    # A name the build shows on the claim, which Lean found outside the project, is kept as the
    # build shows it.
    assert out["declarations"] == [{"name": "Nat.le_refl", "module": "Init.Prelude",
                                    "build": "as shown", "status_code": "link.checked"}]
    # Clearing from either removes the confirmed list and keeps the rejections.
    links.unlink()
    link(capsys, "Theorem 1", "--reject", "Ex.tri")
    link(capsys, "Theorem 1", "Ex.main")
    code, out = link(capsys, "thm:main", "--clear")
    assert code == 0 and entry(proj, "thm:main") == {"rejected": ["Ex.tri"]}
    reader({"key": "thm:main", "lean": ["Ex.main"]})
    code, ack = reader({"key": "thm:main", "lean": None})
    assert code == 200 and entry(proj, "thm:main") == {"rejected": ["Ex.tri"]}


@needs_tex
def test_refused_requests_name_the_candidates_and_write_nothing(proj, reader, capsys):
    link(capsys, "Theorem 1", "Ex.main", "--note", "Direct.")
    links = simple.links_file(proj)
    before = links.read_bytes()

    code, out = link(capsys, "Lemma 9", "Ex.main")
    assert code == 1 and not out["ok"] and not out["written"]
    assert "P:lem:bound" in [c["id"] for c in out["error"]["candidates"]]
    code, out = link(capsys, "2.3", "Ex.main")
    assert code == 1 and out["error"]["kind"] == "ambiguous"
    assert {c["id"] for c in out["error"]["candidates"]} == {"P:lem:bound", "P:rem-2.3"}
    assert {c["kind"] for c in out["error"]["candidates"]} == {"lemma", "remark"}
    code, out = link(capsys, "Q:thm:main", "Ex.main")
    assert code == 1 and [c["id"] for c in out["error"]["candidates"]][:1] == ["P:thm:main"]

    code, out = link(capsys, "Theorem 1", "main")
    assert code == 1 and out["error"]["candidates"] == [{"name": "Ex.main"}]
    code, out = link(capsys, "Theorem 1", "Ex.nothing")
    assert code == 1 and "not a declaration of the project" in out["error"]["message"]
    code, out = link(capsys, "Theorem 1", "Nat.add_comm")
    assert code == 1 and "--external" in out["error"]["message"]
    code, out = link(capsys, "Theorem 1", "Ex.twin")
    assert code == 1 and out["error"]["kind"] == "ambiguous"
    assert "MODULE:NAME" in out["error"]["message"]
    assert out["error"]["candidates"] == [{"name": "Ex.twin", "module": "Ex.A"},
                                          {"name": "Ex.twin", "module": "Ex.B"}]
    code, out = link(capsys, "Lemma 2.3", "Ex.twin", "--add")      # suggested, all the same
    assert code == 1 and out["error"]["kind"] == "ambiguous"
    code, out = link(capsys, "Theorem 1", "Ex.C:Ex.twin")
    assert code == 1 and "declared in Ex.A, Ex.B" in out["error"]["message"]
    code, out = link(capsys, "Theorem 1", "Ex.A:Ex.twin", "Ex.B:Ex.twin")
    assert code == 1 and "two modules" in out["error"]["message"]
    # A refused request among good names writes none of them.
    code, out = link(capsys, "Theorem 1", "Ex.main", "Ex.inverse_bound", "Ex.nothing")
    assert code == 1
    # A paper the project does not have is named with the ones it has.
    code, out = link(capsys, "--paper", "nope.tex", "Theorem 1", "Ex.main")
    assert code == 2 and not out["ok"] and "paper.tex" in out["error"]["message"]

    # The reader's requests are checked as the command line's are.
    code, err = reader({"key": "thm:main", "lean": ["Ex.main", "Ex.nothing"]})
    assert code == 400 and "not a declaration of the project" in err["error"]
    code, err = reader({"key": "thm:main", "lean": ["Ex.twin"]})
    assert code == 400 and err["kind"] == "ambiguous" and len(err["candidates"]) == 2
    code, err = reader({"key": "lem:none", "lean": ["Ex.main"]})
    assert code == 400 and err["candidates"]
    assert links.read_bytes() == before


@needs_tex
def test_a_module_says_which_declaration_and_stays_with_the_link(proj, capsys):
    link(capsys, "Theorem 1", "Ex.main", "--coverage", "full", "--note", "Direct.")
    code, out = link(capsys, "Theorem 1", "Ex.A:Ex.twin", "--add")
    assert code == 0 and out["declarations"] == [{"name": "Ex.twin", "module": "Ex.A",
                                                  "build": "built"}]
    e = entry(proj, "thm:main")
    assert e["lean"] == ["Ex.main", "Ex.twin"] and e["modules"] == {"Ex.twin": "Ex.A"}
    # The reading was written for the list before: it is kept, no longer shown.
    assert "note" not in e and e["earlier_notes"][0]["lean"] == ["Ex.main"]
    # Giving the linked name again without its module keeps the module recorded.
    code, out = link(capsys, "Theorem 1", "Ex.main", "Ex.twin")
    assert code == 0 and not out["written"] and entry(proj, "thm:main")["modules"] == \
        {"Ex.twin": "Ex.A"}
    # Another module is another declaration: the reading written for the first moves aside.
    link(capsys, "Theorem 1", "--coverage", "partial", "--note", "Only the bound.")
    code, out = link(capsys, "Theorem 1", "Ex.main", "Ex.B:Ex.twin")
    e = entry(proj, "thm:main")
    assert code == 0 and e["modules"] == {"Ex.twin": "Ex.B"} and "note" not in e
    assert e["earlier_notes"][-1]["modules"] == {"Ex.twin": "Ex.A"}
    # A rejection is by name; the module only checks it.
    code, out = link(capsys, "Lemma 2.3", "--reject", "Ex.B:Ex.twin")
    assert code == 0 and entry(proj, "lem:bound")["rejected"] == ["Ex.twin"]
    assert "modules" not in entry(proj, "lem:bound")
    # Unlinking the declaration drops its module.
    link(capsys, "Theorem 1", "Ex.main")
    assert "modules" not in entry(proj, "thm:main")


@needs_tex
def test_a_key_in_another_case_is_recorded_under_the_claims_key(proj, capsys):
    code, out = link(capsys, "LEM:Bound", "Ex.inverse_bound")
    assert code == 0 and out["claim"]["key"] == "lem:bound"
    assert list(simple.load_links(proj)["papers"][PAPER]) == ["lem:bound"]


def test_links_under_keys_the_paper_does_not_have_are_named():
    """Entries written by hand under a key no claim has are not shown; the build says so."""
    keys = ["lem:bound", "thm:main", "eq:sum"]
    assert simple.unknown_link_keys({"lem:bound": {}, "thm:main": {}}, keys) is None
    note = simple.unknown_link_keys({"LEM:Bound": {}, "thm:gone": {}, "eq:sum": {}}, keys)
    assert note.startswith("machinechecked.links.json has links for 2 claim key(s) this paper "
                           "does not have, which are not shown: LEM:Bound (the paper has "
                           "lem:bound), thm:gone;")
