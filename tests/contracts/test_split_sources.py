"""A paper whose main file `\\input`s or `\\include`s its sections (#297): each claim's printed
statement is read from the file that holds it, as in a single-file paper, both for a statement
environment (placed exactly) and for a passage located by line (placed approximately)."""

import json
import re
import shutil

from conftest import build, needs_tex
from prooflens.compare import passage
from prooflens.manifest import claim_file
from prooflens.source_regions import SCHEME, extract

# Claims located by line that are not proof steps: a display inside a theorem, stated formally,
# and a sentence of the discussion.
LINE_CLAIMS = [
    {"id": "T:eq:gauss", "paper": "T", "kind": "equation", "number": "(1)", "title": "",
     "match": r"\begin{equation}\label{eq:gauss}", "scope": "formal", "scope_note": "",
     "scope_reviewed": True, "clauses": []},
    {"id": "T:history", "paper": "T", "kind": "sentence", "number": "", "title": "",
     "match": "is traditionally attributed to Gauss", "scope": "expository",
     "scope_note": "a historical remark", "scope_reviewed": True, "clauses": []},
]
SECTIONS = ["definitions", "results", "discussion"]
# The first section is `\input` without its extension, the second `\include`d, the third
# `\input` with its extension.
COMMANDS = [r"\input{sections/definitions}", r"\include{sections/results}",
            r"\input{sections/discussion.tex}"]


def add_line_claims(root):
    """Add `LINE_CLAIMS` to the toy's inventory, each pinned at the line that holds `match`."""
    inv_path = root / "claims.json"
    inv = json.loads(inv_path.read_text())
    lines = (root / "paper" / "toy.tex").read_text().split("\n")
    for spec in LINE_CLAIMS:
        c = {k: v for k, v in spec.items() if k != "match"}
        n = next(i + 1 for i, l in enumerate(lines) if spec["match"] in l)
        c["location"] = f"toy.tex:{n}"
        region = extract(root / "paper", c)
        c.update(source_hash_scheme=SCHEME, source_sha256=region.sha256)
        inv["claims"].append(c)
    inv_path.write_text(json.dumps(inv, indent=1))


def split(root):
    """Move each section of `toy.tex` to `sections/<name>.tex` and rewrite the inventory's
    locations to the file and line that now hold them; return where each label now is."""
    paper = root / "paper"
    lines = (paper / "toy.tex").read_text().split("\n")
    starts = [i for i, l in enumerate(lines) if l.startswith(r"\section{")]
    end = lines.index(r"\end{document}")
    assert len(starts) == len(SECTIONS)
    where = {}                          # line of toy.tex -> (file, line)
    main = lines[:starts[0]]
    (paper / "sections").mkdir()
    for name, command, a, b in zip(SECTIONS, COMMANDS, starts, starts[1:] + [end]):
        (paper / "sections" / f"{name}.tex").write_text("\n".join(lines[a:b]) + "\n")
        where.update({j + 1: (f"sections/{name}.tex", j - a + 1) for j in range(a, b)})
        main.append(command)
    (paper / "toy.tex").write_text("\n".join(main + lines[end:]))
    labels = {m.group(1): where[i + 1][0] for i, l in enumerate(lines)
              for m in re.finditer(r"\\label\{([^}]*)\}", l)}

    inv_path = root / "claims.json"
    inv = json.loads(inv_path.read_text())
    for c in inv["claims"]:
        path, _, line = c["location"].rpartition(":")
        if line.isdigit():
            f, n = where[int(line)]
            c["location"] = f"{f}:{n}"
            if "source_region" in c:
                c["source_region"]["end_line"] = where[c["source_region"]["end_line"]][1]
        elif c.get("label"):
            c["location"] = labels[c["label"]]
    inv_path.write_text(json.dumps(inv, indent=1))
    return labels


def chunks(root, cfg, index):
    return {c["id"]: json.loads((cfg.out_dir / "site" / "data" / "claims" /
                                 claim_file(c["id"])).read_text()) for c in index["claims"]}


@needs_tex
def test_a_split_paper_gives_each_claim_its_statement_from_the_file_that_holds_it(toy, tmp_path):
    add_line_claims(toy)
    other = tmp_path / "split"
    shutil.copytree(toy, other, ignore=shutil.ignore_patterns(".lake", ".machinechecked",
                                                              ".prooflens"))
    labels = split(other)
    assert (other / "paper" / "sections" / "results.tex").exists()

    index, _, cfg = build(toy, skip_lean=True)
    single = chunks(toy, cfg, index)
    index, body, cfg = build(other, skip_lean=True)
    parts = chunks(other, cfg, index)
    inv = {c["id"]: c for c in body["inventory"]["claims"]}

    assert set(parts) == set(single)
    for cid, ch in parts.items():
        # Every claim has its printed statement, and it is the single-file paper's.
        assert ch["statement_tex"], cid
        assert ch["statement_tex"] == single[cid]["statement_tex"], cid
        if ":" in inv[cid]["location"]:
            # A passage located by line: read from the section file its location names.
            assert inv[cid]["location"].startswith("sections/")
            assert ch["anchor"]["kind"] == "approximate", cid
            assert ch["source_matches"] is True, cid
            assert ch["statement_tex"] == extract(other / "paper", inv[cid]).text
        else:
            # A statement environment: placed exactly, in the file that holds it.
            assert ch["anchor"]["kind"] == "exact", cid
            assert ch["anchor"]["file"] == labels[inv[cid]["label"]], cid

    # A claim located by line that is not a proof step has its passage, in the reader's data,
    # the search and the review packet.
    gauss = parts["T:eq:gauss"]
    assert gauss["unit"] == "statement" and gauss["statement_tex"].startswith(
        r"\begin{equation}\label{eq:gauss}")
    assert parts["T:history"]["statement_tex"].endswith("is traditionally attributed to Gauss.")
    p = passage(gauss, "informed")
    assert p["available"] and p["text"] == gauss["statement_tex"]
    assert p["source"]["file"] == "sections/results.tex"
    search = json.loads((cfg.out_dir / "site" / "data" / "search.json").read_text())
    assert next(c for c in search["claims"] if c["id"] == "T:eq:gauss")["statement"] == \
        gauss["statement_tex"]
