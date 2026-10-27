"""The commands the agent guides show run as the guides say (#131).

`docs/AGENTS.md` and `skills/machinechecked/SKILL.md` show commands in `sh` blocks, and the worked
investigation names more in its prose. Each of them is either run here, on a copy of the toy
example (the worked investigation, then the reference's toy queries) or of the plain example (the
reference's check, review and recording examples), with the exit code and the output the guide
shows; or listed in ILLUSTRATIVE with the reason it is not run. The guide's `json` blocks are
either output a command here must give or operations a step here applies. A command or block
added to the guides that is in neither fails `test_every_documented_command_is_run_or_illustrative`,
which builds nothing.

The commands run one at a time, in bash, with `machinechecked` the engine this test imports; the
working directory and the environment carry from one command to the next, as in one shell. The
toy scenario builds its Lean once (the guide's `lake build`); every later command reuses it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest

import prooflens
from conftest import ROOT, edit, needs_lean, needs_tex

DOCS = {"AGENTS.md": ROOT / "docs" / "AGENTS.md",
        "SKILL.md": ROOT / "skills" / "machinechecked" / "SKILL.md"}
WORKED = "A worked investigation"


def norm(s: str) -> str:
    return " ".join(s.split())


def guide(doc: str) -> str:
    return DOCS[doc].read_text(encoding="utf-8")


# --- The commands the guides show --------------------------------------------------------------

@dataclass(frozen=True)
class Doc:
    """One command of a guide: `key` identifies it (whitespace collapsed, a trailing comment
    left out); `text` is what runs."""
    doc: str
    key: str
    text: str
    heredoc: bool


def section(text: str, title: str) -> str:
    start = text.index(f"\n## {title}\n")
    end = text.find("\n## ", start + 1)
    return text[start:end if end >= 0 else len(text)]


def fenced(text: str, lang: str) -> list[str]:
    return re.findall(rf"^```{lang}\n(.*?)^```$", text, re.M | re.S)


def sh_commands(block: str) -> list[tuple[str, bool]]:
    """Each command of an `sh` block, with its continuation lines and its here-document."""
    lines, out, i = block.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cmd = line
        while cmd.endswith("\\") and i < len(lines):
            cmd += "\n" + lines[i]
            i += 1
        here = re.search(r"<<-?\s*'?(\w+)'?", cmd)
        if here:
            while i < len(lines) and lines[i] != here.group(1):
                cmd += "\n" + lines[i]
                i += 1
            cmd += "\n" + here.group(1)
            i += 1
        out.append((cmd, bool(here)))
    return out


def command_key(text: str, heredoc: bool) -> str:
    if heredoc:
        return norm(text)
    return norm(re.sub(r"\s+#\s.*$", "", text.replace("\\\n", " "), flags=re.M))


def documented() -> list[Doc]:
    """Every command of the guides' `sh` blocks, and each `machinechecked ...` the worked
    investigation names in its prose."""
    out = []
    for name in DOCS:
        text = guide(name)
        for block in fenced(text, "sh"):
            out += [Doc(name, command_key(c, h), c, h) for c, h in sh_commands(block)]
        if name == "AGENTS.md":
            prose = re.sub(r"^```.*?^```$", "", section(text, WORKED), flags=re.M | re.S)
            for span in map(norm, re.findall(r"`([^`]+)`", prose)):
                if span.startswith("machinechecked "):
                    out.append(Doc(name, span, span, False))
    return out


def find(doc: str, key: str) -> Doc:
    """The documented command `key` names: the command itself, or for a command with a
    here-document, a part of it that only it has."""
    hits = {d for d in documented() if d.doc == doc
            and (d.key == key or (d.heredoc and norm(key) in d.key))}
    assert len({d.text for d in hits}) == 1, (
        f"{doc} shows {'no' if not hits else 'more than one'} command {key!r}")
    return next(iter(hits))


# The guide's `json` blocks, each named by a part only it has.
JSON_OUTPUT_INFORMED = '"schema": "machinechecked/review-next@1"'
JSON_OP_SUPERSEDE = '"op": "supersede"'


def json_block(marker: str):
    (block,) = [b for b in fenced(guide("AGENTS.md"), "json") if marker in b]
    return json.loads(block)


# --- Running them ------------------------------------------------------------------------------

@dataclass
class Run:
    """Run the documented command `key` of `doc`; check its exit code, that each of `shows`
    (output the guide quotes) is in the guide and in what the command printed, and `check`."""
    key: str
    doc: str = "AGENTS.md"
    rc: int = 0
    shows: tuple[str, ...] = ()
    check: Callable | None = None
    fill: dict[str, str] = field(default_factory=dict)   # placeholder -> attribute of the state
    timeout: int = 900


@dataclass
class Do:
    """A step that is not a command of the guides: a file the guide says the user writes, an
    edit it describes in words, or a check of what an earlier command left."""
    what: Callable


@dataclass
class Result:
    rc: int
    out: str
    err: str

    def json(self):
        return json.loads(self.out)


class Shell:
    """One shell session: its working directory and environment, carried from command to
    command, and what the scenario learns on the way."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.cwd = tmp
        bin_ = tmp / "bin"
        bin_.mkdir()
        shim = bin_ / "machinechecked"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m prooflens "$@"\n')
        shim.chmod(0o755)
        engine = str(Path(prooflens.__file__).resolve().parents[1])
        path = [engine] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
        self.env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": os.pathsep.join(path)}
        self.env.pop("MACHINECHECKED_REVIEWER", None)
        self.state = tmp / ".shell"
        self.state.mkdir()
        self.log: list[str] = []

    def sh(self, text: str, timeout: int = 900) -> Result:
        script = (f"{text}\n__rc=$?\npwd > '{self.state}/cwd'\n"
                  f"env -0 > '{self.state}/env'\nexit $__rc\n")
        r = subprocess.run(["bash", "-c", script], cwd=self.cwd, env=self.env,
                           capture_output=True, text=True, timeout=timeout)
        self.cwd = Path((self.state / "cwd").read_text().strip())
        self.env = dict(kv.split("=", 1) for kv in
                        (self.state / "env").read_text().split("\0") if "=" in kv)
        self.log.append(f"$ {text}\n[exit {r.returncode}]\n{r.stdout}\n{r.stderr}")
        return Result(r.returncode, r.stdout, r.stderr)

    def json(self, rel: str):
        return json.loads((self.cwd / rel).read_text(encoding="utf-8"))


def play(sh: Shell, steps: list) -> None:
    for step in steps:
        if isinstance(step, Do):
            step.what(sh)
            continue
        text = find(step.doc, step.key).text
        for placeholder, attr in step.fill.items():
            text = text.replace(placeholder, getattr(sh, attr))
        r = sh.sh(text, step.timeout)
        where = f"`{step.key}` ({step.doc})"
        assert r.rc == step.rc, (f"{where} exited {r.rc}, not {step.rc}\n"
                                 f"{r.out[-3000:]}\n{r.err[-3000:]}")
        for s in step.shows:
            assert norm(s) in norm(guide(step.doc)), f"{where}: the guide no longer shows {s!r}"
            assert norm(s) in norm(r.out + "\n" + r.err), f"{where} does not print {s!r}:\n{r.out}"
        if step.check:
            step.check(sh, r)


def scenario(tmp_path, steps):
    sh = Shell(tmp_path)
    try:
        play(sh, steps)
    finally:
        # Every command with what it printed, for reading a failure.
        (tmp_path / "commands.log").write_text("\n".join(sh.log), encoding="utf-8")


# --- The toy example: the worked investigation, then the reference's toy queries ---------------

def records(show: dict, claim: str):
    c = show["claims"][claim]
    for group in ("evidence", "findings", "questions", "compositions", "counterexamples"):
        for r in c.get(group) or []:
            yield group, r


def results(out: str) -> list[str]:
    """The declarations a search printed, in order."""
    return re.findall(r"^(\S+)  \((?:theorem|def|lemma)", out, re.M)


def query(r: Result, op: str) -> list:
    d = r.json()
    assert d["op"] == op and d["available"] is True, d
    assert {"target", "context", "results", "provenance", "retrieval"} <= set(d)
    assert d["results"], d
    return d["results"]


def _check_json(sh, r):
    d = sh.json("check.json")
    assert d["ok"] and d["schema"] == "machinechecked/check@1"
    # Exit 0: every linked declaration is proved.
    assert all(ln["status_code"] == "link.checked" for c in d["claims"] for ln in c["links"])
    (t25,) = [c for c in d["claims"] if c["number"] == "Theorem 2.5"]
    first = t25["suggestions"][0]
    assert first["name"] == "ToyAudit.bound_range_corrected_holds"
    assert any(x["signal"] == "number" for x in first["reasons"]), first
    (w,) = [w for w in d["warnings"] if w["kind"] == "paper-reference"
            and "Toy.PaperSpec.thm_bound" in w["message"]]
    assert w["reference"] == "Theorem 2.4" and w["status"] == "other-kind"
    assert "Remark 2.4" in w["message"]
    assert any(x["reference"] == "Theorem 2.4" and x["status"] == "other-kind"
               for x in d["numbering"]["references"])


def _read_stage(sh, r):
    d = r.json()
    assert d["stage"] == "read" and d["paper"]["passages"] and "lean" not in d
    assert {"lean", "interpretations"} <= {w["section"] for w in d["retrieval"]["withheld"]}


def _search_claim(sh, r):
    assert results(r.out) == ["ToyAudit.bound_range_corrected_holds", "Toy.Acceptance.thm_bound",
                              "ToyAudit.bound_range_at_one_false"], r.out


def _search_expression(sh, r):
    found = results(r.out)
    assert found[:2] == ["Toy.Acceptance.thm_triangle", "Toy.Acceptance.thm_bound"], r.out


def _packet(sh, r):
    d = sh.json("packet.json")
    statements = {c["name"]: c["statement"]["text"] for c in d["lean"]["candidates"]}
    assert statements["ToyAudit.bound_range_corrected_holds"] == \
        "∀ (n k : Nat), 1 ≤ k → n ≤ k * n ^ 2"
    assert statements["Toy.Acceptance.thm_bound"] == \
        "∃ (C : Nat), ∀ (n : Nat), Toy.triangle n ≤ C * (n * n)"


def _deps(sh, r):
    (d,) = sh.json("deps.json")["results"]
    assert d["schema"] == "machinechecked/inspect@1"
    assert "Toy.Acceptance.thm_triangle" in d["proof_dependencies"]


def _linked(number):
    def check(sh, r):
        d = r.json()
        assert d["schema"] == "machinechecked/link@1" and d["written"], d
        assert d["claim"]["number"] == number
    return check


def cited(out: str) -> dict:
    """The reference the terminal text of `uses` or `proof-facts` offers to cite."""
    (line,) = re.findall(r"^  cite as evidence: (\{.*\})(?: \(or another .*\))?$", out, re.M)
    return json.loads(line)


def _uses(sh, r):
    assert re.findall(r"^  application (app:\S+) in ", r.out, re.M) == [
        "app:Toy.Acceptance.thm_bound:0"], r.out
    sh.app = cited(r.out)


def _facts(sh, r):
    assert re.findall(r"^  (f\d+) ", r.out, re.M)[0] == "f2", r.out
    sh.fact = cited(r.out)


def _main_saved(sh, r):
    assert re.search(r"main results saved by llm:MODEL at \S+, against release v-", r.out), r.out
    assert "P:thm:bound (Theorem 2.5), its linked Lean" in r.out


def _impact_saved(sh, r):
    assert re.search(r"Main results \(saved in workspace ws-\w+ by llm:MODEL at ", r.out), r.out
    assert "Theorem 2.5  [P:thm:bound]  Toy.Acceptance.thm_bound: used by its proof" in r.out


def _evidence_cites_what_step_4_gave(sh):
    """Step 5 cites the application and the fact as step 4's answers print them."""
    text = find("AGENTS.md", '"op_id": "t25-evidence"').text
    ops = json.loads(text.split("\n", 1)[1].rsplit("\n", 1)[0])["ops"]
    refs = {op["record"].get("id"): op["record"].get("ref") for op in ops}
    assert (refs["e-gauss"], refs["e-square"]) == (sh.app, sh.fact)


def _step(sh, r):
    d = sh.json("step.json")
    roles = {x["name"]: x["role"] for x in d["lean"]["declarations"]}
    assert roles["Toy.Acceptance.thm_bound"] == "formal route used instead"


def _workspace_file(sh) -> Path:
    return sh.cwd / ".machinechecked" / "review-work" / "llm_MODEL.json"


def _step_reading_only(sh):
    """Step 6 says what `workspace suggest` proposes when run before the step's fragment is
    recorded: record the step's requirements alone, in a copy of the workspace put back after."""
    sh.saved_ws = _workspace_file(sh).read_bytes()
    ops = json.loads(find("AGENTS.md", '"op_id": "eq3"').text.split("\n", 1)[1]
                     .rsplit("\n", 1)[0])["ops"]
    reqs = [op for op in ops if op["record"]["kind"] == "requirement"
            and op["record"]["local_id"] in ("n", "n.k")]
    (sh.cwd / "ops.json").write_text(json.dumps({"ops": reqs}, ensure_ascii=False),
                                     encoding="utf-8")
    r = sh.sh("machinechecked workspace update ops.json")
    assert r.rc == 0, r.out + r.err


def _suggested(sh, r):
    (op,) = [op for op in r.json()["ops"]
             if (op["record"].get("region") or {}).get("start_line") == 75]
    rec = op["record"]
    assert (rec["kind"], rec["requirement"], rec["role"]) == ("fragment", "n.k",
                                                              "quantifier domain"), rec
    assert rec["region"]["file"] == "toy.tex"


def _put_back(sh):
    _workspace_file(sh).write_bytes(sh.saved_ws)


def _published(sh, r):
    work = sh.tmp / "site" / "data" / "work"
    text = " ".join(p.read_text(encoding="utf-8") for p in work.rglob("*.json"))
    for x in ("f-bound", "f-power", "f-step", "c-bound", "c.1.1", "llm:MODEL"):
        assert x in text, x
    index = json.loads((sh.tmp / "site" / "data" / "index.json").read_text(encoding="utf-8"))
    (c,) = [c for c in index["claims"] if c["id"] == "P:thm:bound"]
    assert c["status"] == "linked: Lean proof checked"


def _other_copy(sh):
    """Another agent's copy of the project, under its own name, with no workspace yet."""
    other = sh.tmp / "other"
    shutil.copytree(sh.tmp / "toy", other, symlinks=True,
                    ignore=shutil.ignore_patterns("review-work"))
    sh.ws = json.loads((sh.tmp / "t25-work.json").read_text(encoding="utf-8"))["id"]
    sh.cwd = other
    sh.env["MACHINECHECKED_REVIEWER"] = "llm:OTHER"


def _resumed(sh, r):
    d = r.json()
    assert d["resume"]["claim"] == "P:thm:bound" and d["resume"]["question"] == "q-domain"
    states = {rec["currency"]["state"] for _, rec in records(d, "P:thm:bound")}
    assert states == {"current"}, states


def _informed_order(sh, r):
    """The answer the reference shows for the toy example, release and mode left out."""
    shown, got = json_block(JSON_OUTPUT_INFORMED), r.json()
    assert {k: got[k] for k in shown if k != "unit"} == {k: v for k, v in shown.items()
                                                          if k != "unit"}
    assert {k: got["unit"][k] for k in shown["unit"]} == shown["unit"]


def _change_paper(sh):
    sh.cwd = sh.tmp / "toy"
    sh.env["MACHINECHECKED_REVIEWER"] = "llm:MODEL"
    edit(sh.cwd / "paper" / "toy.tex", "for every natural number\n$n$.",
         "for every positive natural number\n$n$.")


def _stale(sh, r):
    d = sh.sh("machinechecked workspace show --json").json()
    c = d["claims"]["P:thm:bound"]
    assert {q["local_id"]: q["currency"]["state"] for q in c["reading"]["requirements"]} == {
        "c": "stale", "c.1": "stale", "c.1.1": "stale"}
    for group, rec in records(d, "P:thm:bound"):
        if group != "questions":
            want = "current" if group == "evidence" else "stale"
            assert rec["currency"]["state"] == want, (group, rec["id"], rec["currency"])
    f = {x["id"]: x for x in c["findings"]}["f-bound"]
    assert (f["basis"], f["recorded_basis"]) == ("reviewed_composition", "checked_bridge")
    shown = sh.sh('machinechecked workspace show --claim "Theorem 2.5"').out
    assert norm("out of date: the paper's passage is not the version the auditor read") in \
        norm(shown)
    sh.show8 = d


def _repin(sh):
    """Put the reading again against the new text and record the composition anew, as step 8
    says in words; then the supersession the guide shows."""
    ws = json.loads(_workspace_file(sh).read_text(encoding="utf-8"))["records"]
    ops = []
    for q in sh.show8["claims"]["P:thm:bound"]["reading"]["requirements"]:
        rec = {k: v for k, v in ws[q["id"]].items()
               if k in ("id", "kind", "claim", "local_id", "parent", "form", "binds", "domain",
                        "independent_of", "text")}
        if rec["local_id"] == "c.1":
            rec.update(domain="n ≥ 1", text="for every positive natural number n")
        ops.append({"op": "put", "base_rev": ws[q["id"]]["rev"], "record": {**rec, "repin": True}})
        for f in q["fragments"]["governing"]:
            fr = ws[f["id"]]
            rec = {k: fr[k] for k in ("id", "kind", "claim", "requirement", "role")}
            if "region" in fr:
                rec["region"] = {k: fr["region"][k] for k in ("file", "start_line")}
            else:
                rec["passage"] = {"claim": "Theorem 2.5"}
            ops.append({"op": "put", "base_rev": fr["rev"], "record": {**rec, "repin": True}})
    cb = ws["c-bound"]
    new = {k: cb[k] for k in ("claim", "coverage", "steps", "identifications", "obligations")}
    new["bridge"] = {k: cb["bridge"][k] for k in ("theorem", "target")}
    ops.append({"op": "put", "record": {"id": "c-bound-2", "kind": "composition", **new}})
    for body in ({"op_id": "t25-repin", "ops": ops},
                 {"op_id": "t25-supersede", "ops": [json_block(JSON_OP_SUPERSEDE)]}):
        (sh.cwd / "ops.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        r = sh.sh("machinechecked workspace update ops.json")
        assert r.rc == 0 and r.json()["ok"], r.out + r.err
    d = sh.sh("machinechecked workspace show --json").json()
    findings = {f["id"]: f for f in d["claims"]["P:thm:bound"]["findings"]}
    assert findings["f-bound-2"]["supersedes"] == "f-bound"
    assert findings["f-bound-2"]["currency"]["state"] == "current"
    assert findings["f-bound-2"]["in_force"] and not findings["f-bound"]["in_force"]
    assert {r["currency"]["state"] for r in d["claims"]["P:thm:bound"]["reading"]
            ["requirements"]} == {"current"}


def _definition(sh, r):
    found = query(r, "definition")
    assert [(d["name"], d["signature"]) for d in found[:1]] == [("Toy.triangle", "Nat → Nat")]
    assert "Toy.triangle._f" in {d["name"] for d in found}


def _mentions(sh, r):
    found = {x["name"]: x for x in query(r, "mentions")}
    assert set(found) == {"Toy.Acceptance.thm_bound", "Toy.Acceptance.thm_triangle"}, found
    assert all(x["complete"] for x in found.values())


def _search(first):
    def check(sh, r):
        assert query(r, "search")[0]["name"] == first
    return check


def _proof_facts(sh, r):
    facts = query(r, "proof-facts")
    assert {f["type"]["text"] for f in facts} >= {"n ≤ n * n", "2 * Toy.triangle n = n * (n + 1)"}
    assert {f["basis"] for f in facts} == {"established inside this proof under this context"}


def _ranked(sh, r):
    assert "inside its proof share symbols with 'n * n'" in r.out, r.out


def _used(sh, r):
    (d,) = query(r, "uses")
    assert d["schema"] == "machinechecked/uses@1" and d["answer"] == "used"


def _impact_json(sh, r):
    (d,) = query(r, "impact")
    assert d["schema"] == "machinechecked/impact@1" and d["selection"]["basis"] == "saved"
    assert d["selection"]["reviewer"] == "llm:MODEL"
    assert [m["name"] for m in d["main_results"]] == ["Toy.Acceptance.thm_bound"]


TOY_STEPS = [
    Run("cp -r examples/toy-paper/lean toy && mkdir toy/paper && "
        "cp examples/toy-paper/paper/toy.tex toy/paper/"),
    Run("cd toy && lake build Toy ToyAudit", timeout=1800),
    Run("export MACHINECHECKED_REVIEWER=llm:MODEL"),
    Run("machinechecked check --json > check.json", check=_check_json),
    Run("machinechecked build"),
    # 1. Read the claim and record its requirements.
    Run('machinechecked compare "Theorem 2.5" --stage read --json', check=_read_stage),
    Run("machinechecked workspace open --mode informed"),
    Run('"op_id": "t25-reading"'),
    Run('machinechecked workspace show --claim "Theorem 2.5"',
        shows=("witness C: the claim produces it; chosen before n; independent of n",)),
    # 2. Find the Lean by its mathematics.
    Run('machinechecked compare --query search "Theorem 2.5" --limit 3', check=_search_claim),
    Run("machinechecked compare --query search 'triangle n ≤ C * n ^ 2' --limit 3",
        shows=("its proof uses Toy.Acceptance.thm_triangle, a close match",),
        check=_search_expression),
    # 3. Inspect the statement and its definitions.
    Run('machinechecked compare "Theorem 2.5" --json > packet.json', check=_packet),
    Run("machinechecked compare --query definition Toy.triangle", shows=("Toy.triangle._f",)),
    Run("machinechecked compare --query dependencies Toy.Acceptance.thm_bound --json > deps.json",
        check=_deps),
    Run('machinechecked link "Theorem 2.5" Toy.Acceptance.thm_bound --as llm:MODEL --json',
        check=_linked("Theorem 2.5")),
    Run("machinechecked build"),
    # 4. Follow the objects through the proof.
    Run("machinechecked compare --query uses Toy.Acceptance.thm_triangle",
        shows=("app:Toy.Acceptance.thm_bound:0",
               "parameter n : Nat := n (the variable n introduced in the proof)",
               "2 * Toy.triangle n = n * (n + 1)",
               '{"app": {"callee": "Toy.Acceptance.thm_triangle", '
               '"id": "app:Toy.Acceptance.thm_bound:0"}}'),
        check=_uses),
    Run('machinechecked compare --query proof-facts Toy.Acceptance.thm_bound --match "n ≤ n * n"',
        shows=("hn : n ≤ n * n", "Toy/Acceptance.lean:44, at /1/1/2",
               "established inside this proof under its context",
               '{"fact": {"decl": "Toy.Acceptance.thm_bound", "at": "/1/1/2"}}'),
        check=_facts),
    Run('machinechecked workspace main "Theorem 2.5"', check=_main_saved),
    Run("machinechecked compare --query impact Toy.triangle",
        shows=("used by its proof, directly; also in its statement", "Toy.PaperSpec.thm_bound",
               "8 applications in Toy.Acceptance.thm_bound, with the same result: "
               "app:Toy.Acceptance.thm_bound:0 to app:Toy.Acceptance.thm_bound:7"),
        check=_impact_saved),
    # 5. Assemble the evidence.
    Do(_evidence_cites_what_step_4_gave),
    Run('"op_id": "t25-evidence"'),
    Run('machinechecked compare --query composition "Theorem 2.5"',
        shows=("every clause, through a checked bridge",)),
    # 6. Compare the estimate and the printed proof.
    Run('machinechecked compare "Equation (3)"'),
    Run('machinechecked link "Equation (3)" Toy.Acceptance.thm_bound --route --as llm:MODEL'),
    Run("machinechecked build"),
    Run('machinechecked compare "Equation (3)" --json > step.json', check=_step),
    Do(_step_reading_only),
    Run('machinechecked workspace suggest --claim "Equation (3)" --requirement n.k',
        check=_suggested),
    Do(_put_back),
    Run('"op_id": "eq3"'),
    Run('machinechecked workspace show --claim "Equation (3)"',
        shows=("for every n (n ≥ 0); for every k (k ≥ 0): n ≤ k n²",
               "an admissible counterexample to this reading", "ToyAudit.bound_range_at_one")),
    # 7. Record what is open, and hand the work on.
    Run('"op_id": "t25-question"'),
    Run("machinechecked workspace export --out ../t25-work.json"),
    Run("machinechecked build --site ../site", check=_published),
    Do(_other_copy),
    Run("machinechecked workspace import ../t25-work.json --as llm:OTHER"),
    Run("machinechecked workspace show --id ws-… --json", fill={"ws-…": "ws"}, check=_resumed),
    Run("machinechecked review next --order informed --json", check=_informed_order),
    # 8. Resume after a change.
    Do(_change_paper),
    Run("machinechecked build", check=_stale),
    Do(_repin),
    # The reference's queries on the toy example, against this build.
    Run('machinechecked compare "Theorem 2.5" --json'),
    Run("machinechecked compare --query definition Toy.triangle --json", check=_definition),
    Run("machinechecked compare --query mentions Toy.triangle --json", check=_mentions),
    Run("machinechecked compare --query dependencies Toy.Acceptance.thm_bound --json",
        check=lambda sh, r: query(r, "dependencies")),
    Run('machinechecked compare --query search "Theorem 2.5" --json',
        check=_search("ToyAudit.bound_range_corrected_holds")),
    Run("machinechecked compare --query search 'n ≤ C * n ^ 2' --json",
        check=lambda sh, r: query(r, "search")),
    Run("machinechecked compare --query proof-facts Toy.Acceptance.thm_bound --json",
        check=_proof_facts),
    Run('machinechecked compare --query proof-facts Toy.Acceptance.thm_bound --match "n * n"',
        check=_ranked),
    Run("machinechecked compare --query uses Toy.IsEven --json", check=_used),
    Run("machinechecked compare --query impact Toy.triangle --json", check=_impact_json),
    Run('machinechecked workspace main "Theorem 2.5" --as llm:MODEL', check=_main_saved),
]


@needs_lean
@needs_tex
def test_the_worked_investigation_and_the_toy_queries_run_as_documented(tmp_path):
    (tmp_path / "examples").symlink_to(ROOT / "examples")
    scenario(tmp_path, TOY_STEPS)


# --- The plain example: the reference's check, review and recording examples ------------------

def _plain_copy(sh):
    """A copy of the plain example, built, with the files the review and recording examples
    say the user writes."""
    dst = sh.tmp / "plain"
    shutil.copytree(ROOT / "examples" / "plain-paper", dst, symlinks=True,
                    ignore=shutil.ignore_patterns(".prooflens", ".machinechecked",
                                                  "prooflens.links.json",
                                                  "machinechecked.links.json"))
    r = subprocess.run(["lake", "build"], cwd=dst, capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stdout[-2000:]
    for name, text in {"reading.md": "The sum of two odd numbers is even.",
                       "comparison.md": "Lean states it for natural numbers, as the paper does.",
                       "none.md": "none",
                       "note.md": "The recursion states the paper's sum."}.items():
        (dst / name).write_text(text, encoding="utf-8")
    sh.cwd = dst


def _plain_check(sh, r):
    d = r.json()
    assert d["schema"] == "machinechecked/check@1" and d["ok"]
    assert all(ln["status_code"] == "link.checked" for c in d["claims"] for ln in c["links"])


def _record_copy(sh):
    """The recording examples run in a copy of this build: the review examples' independent
    workspace would make this reviewer's `workspace update` ask which workspace (`--id`)."""
    shutil.copytree(sh.cwd, sh.tmp / "plain-record", symlinks=True)


def _next(sh, r):
    assert r.json()["unit"]["id"] == "link:thm:odd-add"


def _paper_only(sh, r):
    d = r.json()
    assert d["stage"] == "read" and "lean" not in d


def _and_the_lean(sh, r):
    d = r.json()
    assert d["stage"] == "compare"
    assert [x["name"] for x in d["lean"]["declarations"]] == ["Plain.odd_add_odd"]


def _exported(sh, r):
    body = json.loads((sh.cwd / "machinechecked-reviews" / "my-reviews.json")
                      .read_text(encoding="utf-8"))
    reports = body["reports"] if isinstance(body, dict) else body
    (rep,) = reports
    assert rep["unit"]["id"] == "link:thm:odd-add"
    assert rep["correspondence"] == {"coverage": "full", "basis": "direct"}


def _to_record_copy(sh):
    sh.cwd = sh.tmp / "plain-record"


def _recorded(sh, r):
    d = r.json()
    c = d["claims"]["P:thm:sum-odd"]
    assert [e["id"] for e in c["evidence"]] == ["e-1"]
    (f,) = c["findings"]
    assert (f["id"], f["coverage"], f["evidence"]) == ("f-1", "full", ["e-1"])


PLAIN_STEPS = [
    Do(_plain_copy),
    Run("machinechecked check --json", check=_plain_check),
    # Reviewing from the terminal.
    Run("export MACHINECHECKED_REVIEWER=llm:MODEL"),
    Run("machinechecked build"),
    Do(_record_copy),
    Run("machinechecked review next --json", check=_next),
    Run("machinechecked review read link:thm:odd-add --json", check=_paper_only),
    Run("machinechecked review lock link:thm:odd-add reading.md"),
    Run("machinechecked review show link:thm:odd-add --json", check=_and_the_lean),
    Run("machinechecked review decide link:thm:odd-add faithful comparison.md --coverage full "
        "--basis direct"),
    Run("machinechecked review author link:thm:odd-add"),
    Run("machinechecked review submit link:thm:odd-add none.md"),
    Run("machinechecked review export --out machinechecked-reviews/my-reviews.json",
        check=_exported),
    # Recording links and findings.
    Do(_to_record_copy),
    Run('machinechecked link "Theorem 2" Plain.oddSum_eq_sq --coverage full --note-file note.md '
        '--as "llm:MODEL" --json', check=_linked("Theorem 2")),
    Run("machinechecked workspace open --mode informed --as llm:MODEL"),
    Run('"op_id": "req-1"'),
    Run("machinechecked workspace show --json", check=_recorded),
]


@needs_lean
@needs_tex
def test_the_review_and_recording_examples_run_as_documented(tmp_path):
    scenario(tmp_path, PLAIN_STEPS)


# --- Every command of the guides is run or illustrative ----------------------------------------

ILLUSTRATIVE = {
    ("AGENTS.md", "mkdir -p ~/.claude/skills"): "installs the skill in the user's home",
    ("AGENTS.md", "curl -sSfL https://raw.githubusercontent.com/cgarryZA/MachineChecked/main/"
                  "skills/machinechecked/SKILL.md --create-dirs -o "
                  "~/.claude/skills/machinechecked/SKILL.md"): "downloads the skill",
    ("SKILL.md", "lake build"): "the user's own project",
    ("SKILL.md", "uvx machinechecked check --json"): "installs MachineChecked from PyPI",
    ("AGENTS.md", "machinechecked inspect NAME --dependencies --json"):
        "NAME stands for a declaration",
    ("AGENTS.md", "machinechecked review"): "names the review commands",
    ("AGENTS.md", "machinechecked changes --workspace ID"):
        "a full assessment's command; ID stands for a workspace",
}

JSON_BLOCKS = (JSON_OUTPUT_INFORMED, JSON_OP_SUPERSEDE)


def test_every_documented_command_is_run_or_illustrative():
    shown = Counter((d.doc, d.key) for d in documented())
    have = Counter(ILLUSTRATIVE.keys())
    for s in TOY_STEPS + PLAIN_STEPS:
        if isinstance(s, Run):
            have[(s.doc, find(s.doc, s.key).key)] += 1
    missing, extra = shown - have, have - shown
    assert not missing, ("commands the guides show that this test neither runs nor marks "
                         f"illustrative: {sorted(missing)}")
    assert not extra, f"commands run more often here than the guides show them: {sorted(extra)}"
    for block in fenced(guide("AGENTS.md"), "json"):
        assert sum(m in block for m in JSON_BLOCKS) == 1, f"a json block this test does not use:\n{block}"
